"""Safely remove only artifacts enumerated by GIS benchmark JSON reports."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from environment.models import RemoteSensingImage


class Command(BaseCommand):
    help = '根据指定端到端压测报告清理临时影像记录和结果目录；不会删除 JSON/CSV 或基准输入。'

    def add_arguments(self, parser):
        parser.add_argument('--report-file', action='append', required=True, help='可重复指定 benchmark_gis_e2e JSON')
        parser.add_argument('--confirm', action='store_true', help='确认执行删除；省略时仅列出精确目标')

    def handle(self, *args, **options):
        media_root = Path(settings.MEDIA_ROOT).resolve()
        output_root = (media_root / 'ecological_indices').resolve()
        image_ids = set()
        output_dirs = set()

        for source in options['report_file']:
            report_path = Path(source).expanduser().resolve()
            if not report_path.is_file():
                raise CommandError(f'报告不存在：{report_path}')
            try:
                report = json.loads(report_path.read_text(encoding='utf-8'))
            except json.JSONDecodeError as exc:
                raise CommandError(f'报告不是有效 JSON：{report_path}') from exc
            for task in report.get('tasks', []):
                image_id = str(task.get('image_id', '')).strip()
                if not image_id:
                    continue
                image_ids.add(image_id)
                for result in task.get('result_files', []):
                    candidate = Path(result.get('path', '')).resolve()
                    # 仅允许 reports 中本任务 UUID 名下的生态指数目录，防止报告
                    # 被误填后波及其他业务文件。
                    expected_dir = (output_root / image_id).resolve()
                    if candidate.is_relative_to(expected_dir):
                        output_dirs.add(expected_dir)

        if not image_ids:
            raise CommandError('报告中没有可清理的压测任务。')
        for path in sorted(output_dirs):
            self.stdout.write(f'结果目录：{path}')
        self.stdout.write(f'临时影像 ID：{", ".join(sorted(image_ids))}')
        if not options['confirm']:
            self.stdout.write(self.style.WARNING('这是预览。追加 --confirm 才会删除上述精确目标。'))
            return

        # 仅删除带明确压测前缀的数据库影像；报告与真实基准输入从不在清理范围内。
        benchmark_name = Q(name__startswith='真实 Landsat 端到端压测-') | Q(name__startswith='真实 Landsat RSEI A/B-')
        images = list(RemoteSensingImage.objects.filter(id__in=image_ids).filter(benchmark_name))
        deleted_images = len(images)
        if images:
            RemoteSensingImage.objects.filter(pk__in=[image.pk for image in images]).delete()
        removed_dirs = 0
        for path in output_dirs:
            if path.is_dir():
                shutil.rmtree(path)
                removed_dirs += 1
        self.stdout.write(self.style.SUCCESS(
            f'已清理 {deleted_images} 条临时影像记录和 {removed_dirs} 个结果目录；JSON/CSV 与基准 GeoTIFF 已保留。'
        ))
