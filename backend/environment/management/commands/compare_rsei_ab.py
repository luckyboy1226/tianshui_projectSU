"""Windowed, all-pixel numerical comparison for real RSEI A/B outputs."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import rasterio
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = '逐窗口比较 legacy/optimized RSEI 输出，给出全像元 MAE、RMSE、相关系数和分级面积差。'

    def add_arguments(self, parser):
        parser.add_argument('--legacy-report', required=True)
        parser.add_argument('--optimized-report', required=True)
        parser.add_argument('--report-file', required=True)
        parser.add_argument('--tolerance', type=float, default=1e-6)

    def handle(self, *args, **options):
        legacy = self._load(options['legacy_report'])
        optimized = self._load(options['optimized_report'])
        legacy_files = {Path(item['path']).stem.replace('_result', ''): item['path'] for item in legacy['output_files']}
        optimized_files = {Path(item['path']).stem.replace('_result', ''): item['path'] for item in optimized['output_files']}
        if legacy_files.keys() != optimized_files.keys():
            raise CommandError(f'输出集合不同：{legacy_files.keys()} vs {optimized_files.keys()}')
        results = [self._compare(name, legacy_files[name], optimized_files[name]) for name in sorted(legacy_files)]
        passed = all(item['max_abs_error'] <= options['tolerance'] and item['metadata_equal'] for item in results)
        report = {'tolerance': options['tolerance'], 'passed': passed, 'comparison': results}
        path = Path(options['report_file']).expanduser().resolve()
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        with path.with_suffix('.csv').open('w', newline='', encoding='utf-8-sig') as stream:
            writer = csv.DictWriter(stream, fieldnames=['index_type', 'valid_pixels', 'correlation', 'mae', 'rmse', 'max_abs_error', 'metadata_equal', 'class_area_difference_km2'])
            writer.writeheader(); writer.writerows([{key: row.get(key) for key in writer.fieldnames} for row in results])
        self.stdout.write(self.style.SUCCESS(f'一致性判定：{"通过" if passed else "失败"}，JSON：{path}'))
        if not passed:
            raise CommandError('数值或空间元数据一致性未达到阈值，不能将优化设为默认。')

    @staticmethod
    def _load(path):
        return json.loads(Path(path).expanduser().resolve().read_text(encoding='utf-8'))

    @staticmethod
    def _compare(name, legacy_path, optimized_path):
        with rasterio.open(legacy_path) as left, rasterio.open(optimized_path) as right:
            nodata_equal = (
                left.nodata == right.nodata or
                (left.nodata is not None and right.nodata is not None and np.isnan(left.nodata) and np.isnan(right.nodata))
            )
            # tiled/compression 是预期的 I/O 优化差异，不属于科学空间元数据。
            metadata_equal = (left.width, left.height, left.crs, left.transform) == (right.width, right.height, right.crs, right.transform) and nodata_equal
            if (left.width, left.height) != (right.width, right.height):
                raise CommandError(f'{name} 尺寸不同')
            n = 0; sx = sy = sxx = syy = sxy = abs_sum = sq_sum = 0.0; max_abs = 0.0
            left_class = np.zeros(5, dtype=np.int64); right_class = np.zeros(5, dtype=np.int64)
            for _, window in left.block_windows(1):
                a = left.read(1, window=window); b = right.read(1, window=window)
                valid = np.isfinite(a) & np.isfinite(b)
                if not np.any(valid):
                    continue
                x = a[valid].astype(np.float64, copy=False); y = b[valid].astype(np.float64, copy=False)
                delta = x - y
                n += x.size; sx += x.sum(); sy += y.sum(); sxx += np.dot(x, x); syy += np.dot(y, y); sxy += np.dot(x, y)
                abs_sum += np.abs(delta).sum(); sq_sum += np.dot(delta, delta); max_abs = max(max_abs, float(np.max(np.abs(delta))))
                if name == 'rsei':
                    left_class += np.bincount(np.clip((x * 5).astype(int), 0, 4), minlength=5)[:5]
                    right_class += np.bincount(np.clip((y * 5).astype(int), 0, 4), minlength=5)[:5]
            covariance = n * sxy - sx * sy
            variance = max(0.0, (n * sxx - sx * sx) * (n * syy - sy * sy))
            correlation = covariance / np.sqrt(variance) if variance > 0 else 1.0
            pixel_km2 = abs(left.transform.a * left.transform.e) / 1_000_000
            area_diff = float(np.abs(left_class - right_class).sum() * pixel_km2) if name == 'rsei' else 0.0
            return {'index_type': name, 'valid_pixels': int(n), 'correlation': float(correlation), 'mae': float(abs_sum / n),
                    'rmse': float(np.sqrt(sq_sum / n)), 'max_abs_error': max_abs, 'metadata_equal': bool(metadata_equal),
                    'class_area_difference_km2': area_diff,
                    'legacy': {'crs': str(left.crs), 'transform': tuple(left.transform), 'nodata': left.nodata, 'tiled': left.is_tiled, 'compression': left.compression.name if left.compression else None, 'block_shapes': left.block_shapes},
                    'optimized': {'crs': str(right.crs), 'transform': tuple(right.transform), 'nodata': right.nodata, 'tiled': right.is_tiled, 'compression': right.compression.name if right.compression else None, 'block_shapes': right.block_shapes}}
