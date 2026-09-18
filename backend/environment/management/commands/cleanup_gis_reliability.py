"""Clean only an explicitly named, non-running GIS reliability drill task."""
from __future__ import annotations

import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from environment.models import EcologicalIndex, ProcessingTask, RemoteSensingImage


class Command(BaseCommand):
    help = '清理指定故障演练任务的临时/最终产物及隔离影像；拒绝清理运行中任务。'

    def add_arguments(self, parser):
        parser.add_argument('--task-id', required=True)
        parser.add_argument('--delete-image', action='store_true', help='同时删除本轮隔离的 RemoteSensingImage 记录')

    def handle(self, *args, **options):
        with transaction.atomic():
            try:
                task = ProcessingTask.objects.select_for_update().select_related('remote_sensing_image').get(pk=options['task_id'])
            except ProcessingTask.DoesNotExist as exc:
                raise CommandError(f'任务不存在：{options["task_id"]}') from exc
            if task.status in {'pending', 'retrying', 'processing'}:
                raise CommandError(f'拒绝清理活跃任务 {task.id}（状态：{task.status}）')
            image = task.remote_sensing_image
            if image and not image.name.startswith('drill-'):
                raise CommandError('仅允许清理名称以 drill- 开头的隔离演练影像')
            tmp_dir = Path(settings.MEDIA_ROOT) / 'ecological_indices' / '.tmp' / str(task.id)
            final_dir = Path(settings.MEDIA_ROOT) / 'ecological_indices' / str(image.id) if image else None
            shutil.rmtree(tmp_dir, ignore_errors=True)
            if final_dir:
                shutil.rmtree(final_dir, ignore_errors=True)
            EcologicalIndex.objects.filter(remote_sensing_image=image).delete()
            task.delete()
            if options['delete_image'] and image:
                image.delete()
        self.stdout.write(self.style.SUCCESS('已清理指定演练任务；报告文件未删除。'))
