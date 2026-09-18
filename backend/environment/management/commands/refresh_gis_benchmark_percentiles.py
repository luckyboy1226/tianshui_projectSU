"""Recalculate aggregate percentiles from immutable per-task benchmark rows."""

from __future__ import annotations

import json
import math
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


def percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return None
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * fraction) - 1))
    return round(ordered[index], 3)


class Command(BaseCommand):
    help = '从每任务的原始时延重算端到端 GIS 压测 JSON 的 P50/P95/P99（nearest-rank）。'

    def add_arguments(self, parser):
        parser.add_argument('--report-file', action='append', required=True, help='可重复指定 benchmark_gis_e2e JSON')

    def handle(self, *args, **options):
        for source in options['report_file']:
            path = Path(source).expanduser().resolve()
            if not path.is_file():
                raise CommandError(f'报告不存在：{path}')
            report = json.loads(path.read_text(encoding='utf-8'))
            successful = [task for task in report.get('tasks', []) if task.get('status') == 'completed']
            for field, key in (
                ('queue_wait_ms', 'queue_wait_ms'),
                ('execution_ms', 'execution_ms'),
                ('end_to_end_ms', 'end_to_end_ms'),
            ):
                values = [task[key] for task in successful if task.get(key) is not None]
                report[field] = {
                    'p50': percentile(values, .50),
                    'p95': percentile(values, .95),
                    'p99': percentile(values, .99),
                    'max': max(values) if values else None,
                }
            report['percentile_method'] = 'nearest-rank'
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            self.stdout.write(self.style.SUCCESS(f'已重算：{path}'))
