"""Recover expired GIS execution leases without creating a new task id."""
from datetime import timedelta
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from environment.concurrency import dispatch_processing_task
from environment.models import EcologicalIndex, ProcessingTask


class Command(BaseCommand):
    help = '扫描 lease 已过期的 processing GIS 任务；同一行锁保证仅一个恢复者重投。'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100)
        parser.add_argument('--force-expire-seconds', type=int, default=0, help='演练用：将早于此秒数的 heartbeat 当作过期')

    def handle(self, *args, **options):
        now = timezone.now()
        expired = ProcessingTask.objects.filter(status='processing', lease_expires_at__lt=now).order_by('lease_expires_at')[:options['limit']]
        recovered = final_failed = skipped = 0
        for candidate in expired:
            with transaction.atomic():
                task = ProcessingTask.objects.select_for_update().get(pk=candidate.pk)
                if task.status != 'processing' or not task.lease_expires_at or task.lease_expires_at >= now:
                    skipped += 1; continue
                tmp_dir = Path(settings.MEDIA_ROOT) / 'ecological_indices' / '.tmp' / str(task.id)
                if task.retry_count >= task.max_retry_count:
                    task.status = 'failed'; task.failed_at = now; task.failure_code = 'LEASE_EXPIRED_MAX_RETRIES'
                    task.error_message = 'Worker 心跳/执行租约过期，已达到最大恢复次数。'
                    task.active_fingerprint = None; task.lease_expires_at = None; task.recovery_action = 'marked_final_failed'
                    task.save()
                    final_failed += 1; continue
                # 临时文件和未发布的部分 ORM 记录均不应进入下一次尝试。
                if tmp_dir.is_dir(): shutil.rmtree(tmp_dir, ignore_errors=True)
                final_dir = Path(settings.MEDIA_ROOT) / 'ecological_indices' / str(task.remote_sensing_image_id)
                if final_dir.exists():
                    # 已发布目录与 processing 同时出现属于不一致状态；恢复器不能
                    # 擅自删除可能已被用户查看的成果，应当留下可审计失败状态。
                    task.status = 'failed'; task.failed_at = now; task.failure_code = 'LEASE_EXPIRED_PUBLISHED_OUTPUT'
                    task.error_message = '执行租约过期，但检测到已发布结果目录；为保护成果未自动重投。'
                    task.active_fingerprint = None; task.lease_expires_at = None; task.recovery_action = 'manual_review_required'
                    task.save()
                    final_failed += 1
                    continue
                EcologicalIndex.objects.filter(remote_sensing_image=task.remote_sensing_image).delete()
                task.status = 'pending'; task.retry_count += 1; task.dispatch_status = 'pending'
                task.worker_identifier = ''; task.last_heartbeat_at = now; task.lease_expires_at = None
                task.recovery_action = 'lease_expired_requeue'; task.error_message = '检测到执行租约过期，保留原 task_id 重新投递。'
                task.save()
            dispatch_processing_task(task)
            recovered += 1
        self.stdout.write(self.style.SUCCESS(f'陈旧任务扫描完成：恢复 {recovered}，最终失败 {final_failed}，跳过 {skipped}。'))
