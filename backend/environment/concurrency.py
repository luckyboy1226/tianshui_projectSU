"""并发任务提交与可靠投递的业务基础设施。"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass

from django.db import IntegrityError, OperationalError, transaction
from django.utils import timezone

from .models import ProcessingTask
from .tasks import calculate_ecological_indices

logger = logging.getLogger(__name__)

IDEMPOTENCY_KEY_RE = re.compile(r'^[A-Za-z0-9._:-]{8,128}$')
QUEUE_BY_PRIORITY = {
    'high': ('geo.high', 9),
    'normal': ('geo.default', 5),
    'low': ('geo.low', 1),
}
# RSEI 会在同一任务中同时读取多波段、进行 PCA 并落盘 5 个栅格；它不能与
# 轻量 NDVI/NDWI 竞争同一组 Worker，否则大任务会拖长交互型任务的排队时间。
RSEI_COMPONENT_INDICES = frozenset({'greenness', 'wetness', 'dryness', 'heat'})


class IdempotencyConflict(ValueError):
    """同一幂等键被用于不同请求。"""


@dataclass(frozen=True)
class SubmissionResult:
    task: ProcessingTask
    created: bool
    deduplicated: bool


def normalize_indices(indices):
    """将指数集合转换为稳定、无重复的任务输入。"""
    return tuple(sorted({str(index).lower().strip() for index in indices if str(index).strip()}))


def select_queue(priority, indices):
    """按计算画像选择队列，同时保留 Celery priority 数值。"""
    queue_name, celery_priority = QUEUE_BY_PRIORITY[priority]
    if RSEI_COMPONENT_INDICES.issubset(set(normalize_indices(indices))):
        return 'geo.heavy', celery_priority
    return queue_name, celery_priority


def build_fingerprint(image_id, indices, user_id=None, priority=None):
    payload = {
        'image_id': str(image_id),
        'indices': list(normalize_indices(indices)),
        # 匿名用户共享同一计算，登录用户之间则相互隔离任务可见性。
        'user_id': str(user_id) if user_id else 'anonymous',
    }
    # 同一幂等键要求请求参数完全相同；优先级也属于请求参数。
    if priority is not None:
        payload['priority'] = priority
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def validate_idempotency_key(key):
    if key in (None, ''):
        return None
    key = str(key).strip()
    if not IDEMPOTENCY_KEY_RE.fullmatch(key):
        raise ValueError('X-Idempotency-Key 必须为 8-128 位字母、数字或 . _ : -')
    return key


def _submit_ecological_task_once(*, image, indices, user=None, idempotency_key=None, priority='normal'):
    """原子创建任务；高并发下相同业务请求只会成功创建一次。"""
    normalized_indices = normalize_indices(indices)
    if not normalized_indices:
        raise ValueError('至少选择一个生态指数')
    if priority not in QUEUE_BY_PRIORITY:
        priority = 'normal'

    key = validate_idempotency_key(idempotency_key)
    user_id = getattr(user, 'id', None) if getattr(user, 'is_authenticated', False) else None
    request_fingerprint = build_fingerprint(image.id, normalized_indices, user_id, priority)
    active_fingerprint = build_fingerprint(image.id, normalized_indices, user_id)
    queue_name, _ = select_queue(priority, normalized_indices)

    with transaction.atomic():
        if key:
            previous = ProcessingTask.objects.filter(idempotency_key=key).first()
            if previous:
                if previous.request_fingerprint != request_fingerprint:
                    raise IdempotencyConflict('该 X-Idempotency-Key 已用于不同的计算请求')
                return SubmissionResult(previous, created=False, deduplicated=True)

        try:
            with transaction.atomic():
                task = ProcessingTask.objects.create(
                    remote_sensing_image=image,
                    task_type=f'生态指数计算 - {", ".join(normalized_indices)}',
                    status='pending',
                    created_by=user if user_id else None,
                    idempotency_key=key,
                    request_fingerprint=request_fingerprint,
                    request_payload={'indices': list(normalized_indices)},
                    active_fingerprint=active_fingerprint,
                    priority=priority,
                    queue_name=queue_name,
                    dispatch_status='pending',
                )
            return SubmissionResult(task, created=True, deduplicated=False)
        except IntegrityError:
            # active_fingerprint 的唯一约束是跨多个 Web 实例的最终仲裁者。
            existing = ProcessingTask.objects.filter(active_fingerprint=active_fingerprint).first()
            if existing:
                return SubmissionResult(existing, created=False, deduplicated=True)
            if key:
                existing = ProcessingTask.objects.filter(idempotency_key=key).first()
                if existing:
                    if existing.request_fingerprint != request_fingerprint:
                        raise IdempotencyConflict('该 X-Idempotency-Key 已用于不同的计算请求')
                    return SubmissionResult(existing, created=False, deduplicated=True)
            raise


def submit_ecological_task(*, image, indices, user=None, idempotency_key=None, priority='normal'):
    """短暂数据库写锁可重试；其他数据库错误立即向上抛出。"""
    for attempt in range(4):
        try:
            return _submit_ecological_task_once(
                image=image,
                indices=indices,
                user=user,
                idempotency_key=idempotency_key,
                priority=priority,
            )
        except OperationalError as exc:
            # SQLite 开发环境会在多线程写入时抛出 database is locked；
            # PostgreSQL 的死锁/序列化错误也应由上层可控地重试。
            transient = any(token in str(exc).lower() for token in ('locked', 'deadlock', 'serialize'))
            if not transient or attempt == 3:
                raise
            time.sleep(0.025 * (2 ** attempt))


def dispatch_processing_task(task, *, recover_stale=False, stale_after_seconds=300):
    """投递任务并记录状态；失败任务可由管理命令安全补投。"""
    # 先将 outbox 记录原子地认领为 dispatching。该状态不依赖进程内锁，
    # 因而多个 Web 实例或多个补投命令不会同时向 Broker 发布同一条记录。
    with transaction.atomic():
        current = ProcessingTask.objects.select_for_update().get(pk=task.pk)
        stale_dispatch = (
            recover_stale
            and current.dispatch_status == 'dispatching'
            and (not current.dispatching_at or (timezone.now() - current.dispatching_at).total_seconds() >= stale_after_seconds)
        )
        if current.status in {'completed', 'failed', 'cancelled'} or (current.dispatch_status in {'dispatched', 'dispatching'} and not stale_dispatch):
            return current
        current.dispatch_status = 'dispatching'
        current.dispatch_attempts += 1
        current.dispatching_at = timezone.now()
        current.last_dispatch_error = ''
        current.save(update_fields=['dispatch_status', 'dispatch_attempts', 'dispatching_at', 'last_dispatch_error'])

    _, celery_priority = QUEUE_BY_PRIORITY.get(current.priority, QUEUE_BY_PRIORITY['normal'])
    indices = current.request_payload.get('indices', [])
    if not indices:
        # 兼容本次迁移前的生态指数任务记录。
        indices = list(normalize_indices(current.task_type.split(' - ', 1)[-1].split(', ')))
    try:
        celery_result = calculate_ecological_indices.apply_async(
            args=(str(current.remote_sensing_image_id), indices, str(current.id)),
            task_id=str(current.id),
            queue=current.queue_name,
            priority=celery_priority,
            retry=False,
        )
    except Exception as exc:
        ProcessingTask.objects.filter(pk=current.pk, dispatch_status='dispatching').update(
            dispatch_status='failed',
            last_dispatch_error=str(exc)[:2000],
        )
        current.refresh_from_db()
        logger.exception('任务 %s 投递失败，保留待补投记录', current.id)
        return current

    ProcessingTask.objects.filter(pk=current.pk, dispatch_status='dispatching').update(
        celery_task_id=str(celery_result.id),
        dispatch_status='dispatched',
        last_dispatch_error='',
    )
    current.refresh_from_db()
    return current


def release_active_task_lock(task):
    """任务结束后释放 single-flight 锁，允许用户重新发起一次计算。"""
    ProcessingTask.objects.filter(pk=task.pk).update(active_fingerprint=None)
