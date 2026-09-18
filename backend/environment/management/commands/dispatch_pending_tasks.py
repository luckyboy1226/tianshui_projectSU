from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta

from environment.concurrency import dispatch_processing_task
from environment.models import ProcessingTask


class Command(BaseCommand):
    help = '补投因 Broker 短暂不可用而未成功投递的生态指数任务。'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100, help='本次最多补投的任务数')
        parser.add_argument('--stale-seconds', type=int, default=300, help='认领超过此秒数的 dispatching 任务可被安全接管')

    def handle(self, *args, **options):
        stale_seconds = max(1, options['stale_seconds'])
        stale_before = timezone.now() - timedelta(seconds=stale_seconds)
        tasks = ProcessingTask.objects.filter(
            task_type__startswith='生态指数计算',
            status='pending',
        ).filter(
            Q(dispatch_status__in=['pending', 'failed']) |
            Q(dispatch_status='dispatching', dispatching_at__lt=stale_before) |
            Q(dispatch_status='dispatching', dispatching_at__isnull=True)
        ).order_by('created_at')[:max(1, options['limit'])]
        dispatched = failed = 0
        for task in tasks:
            task = dispatch_processing_task(task, recover_stale=True, stale_after_seconds=stale_seconds)
            if task.dispatch_status == 'dispatched':
                dispatched += 1
            else:
                failed += 1
        self.stdout.write(self.style.SUCCESS(f'补投完成：成功 {dispatched}，待重试 {failed}。'))
