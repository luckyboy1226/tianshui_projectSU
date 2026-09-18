"""Capture an auditable snapshot for a GIS reliability drill.

This command deliberately does not kill processes.  A drill operator must start a
uniquely named worker and terminate only its verified PID outside this command.
That separation prevents a maintenance command from accidentally stopping a
normal production worker.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from environment.models import EcologicalIndex, ProcessingTask, RSEIResult


class Command(BaseCommand):
    help = '将指定 GIS 任务的状态、结果目录和数据库计数写入 JSON/CSV 审计快照。'

    def add_arguments(self, parser):
        parser.add_argument('--task-id', required=True)
        parser.add_argument('--label', required=True, help='例如 before_kill、after_recovery')
        parser.add_argument('--report-dir', required=True)

    def handle(self, *args, **options):
        try:
            task = ProcessingTask.objects.select_related('remote_sensing_image').get(pk=options['task_id'])
        except ProcessingTask.DoesNotExist as exc:
            raise CommandError(f'任务不存在：{options["task_id"]}') from exc

        image = task.remote_sensing_image
        tmp_dir = Path(settings.MEDIA_ROOT) / 'ecological_indices' / '.tmp' / str(task.id)
        final_dir = Path(settings.MEDIA_ROOT) / 'ecological_indices' / str(image.id) if image else None
        indices = EcologicalIndex.objects.filter(remote_sensing_image=image) if image else EcologicalIndex.objects.none()
        payload = {
            'captured_at': timezone.now().isoformat(),
            'label': options['label'],
            'task_id': str(task.id),
            'celery_task_id': task.celery_task_id,
            'image_id': str(image.id) if image else None,
            'image_name': image.name if image else None,
            'image_path': str(image.file_path) if image else None,
            'status': task.status,
            'dispatch_status': task.dispatch_status,
            'queue_name': task.queue_name,
            'worker_identifier': task.worker_identifier,
            'progress': task.progress,
            'current_step': task.current_step,
            'created_at': task.created_at.isoformat() if task.created_at else None,
            'started_at': task.started_at.isoformat() if task.started_at else None,
            'completed_at': task.completed_at.isoformat() if task.completed_at else None,
            'last_heartbeat_at': task.last_heartbeat_at.isoformat() if task.last_heartbeat_at else None,
            'lease_expires_at': task.lease_expires_at.isoformat() if task.lease_expires_at else None,
            'attempt_count': task.attempt_count,
            'retry_count': task.retry_count,
            'max_retry_count': task.max_retry_count,
            'failed_at': task.failed_at.isoformat() if task.failed_at else None,
            'failure_code': task.failure_code,
            'error_message': task.error_message,
            'recovery_action': task.recovery_action,
            'ecological_index_count': indices.count(),
            'rsei_result_count': RSEIResult.objects.filter(remote_sensing_image=image).count() if image else 0,
            'temporary_file_count': sum(1 for path in tmp_dir.rglob('*') if path.is_file()) if tmp_dir.is_dir() else 0,
            'final_file_count': sum(1 for path in final_dir.rglob('*') if path.is_file()) if final_dir and final_dir.is_dir() else 0,
            'temporary_directory': str(tmp_dir),
            'final_directory': str(final_dir) if final_dir else None,
        }
        report_dir = Path(options['report_dir'])
        report_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{options['label']}_{task.id}"
        json_path = report_dir / f'{stem}.json'
        csv_path = report_dir / f'{stem}.csv'
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        with csv_path.open('w', encoding='utf-8-sig', newline='') as fh:
            writer = csv.DictWriter(fh, fieldnames=list(payload))
            writer.writeheader()
            writer.writerow(payload)
        self.stdout.write(self.style.SUCCESS(f'JSON: {json_path}\nCSV: {csv_path}'))
