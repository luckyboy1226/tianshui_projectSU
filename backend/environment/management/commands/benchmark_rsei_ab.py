"""Run a real, persisted RSEI pipeline benchmark in legacy or optimized mode."""

from __future__ import annotations

import csv
import gc
import json
import os
from pathlib import Path
import threading
import time
import uuid

import psutil
import rasterio
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from environment.ecological_indices import EcologicalIndexCalculator
from environment.models import EcologicalIndex, ProcessingTask, RSEIResult, RemoteSensingImage


COMPONENTS = ('greenness', 'wetness', 'dryness', 'heat')


class Command(BaseCommand):
    help = '真实 Landsat RSEI A/B 子命令：--mode legacy 保留重复计算/全图预览/未压缩写入，optimized 启用优化。'

    def add_arguments(self, parser):
        parser.add_argument('--media-path', required=True, help='相对 MEDIA_ROOT 的已校准 7 波段 Landsat GeoTIFF')
        parser.add_argument('--mode', choices=('legacy', 'optimized', 'optimized_fast'), required=True)
        parser.add_argument('--report-file', required=True)
        parser.add_argument('--sample-seconds', type=float, default=.5)
        parser.add_argument('--keep-artifacts', action='store_true', help='保留临时数据库记录和结果文件，默认也保留以用于数值对比')

    def handle(self, *args, **options):
        relative_path = str(options['media_path']).replace('\\', '/')
        source = Path(settings.MEDIA_ROOT) / relative_path
        if not source.is_file():
            raise CommandError(f'真实 GeoTIFF 不存在：{source}')
        mode = options['mode']
        report_path = Path(options['report_file']).expanduser().resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)

        with rasterio.open(source) as dataset:
            source_meta = self._raster_meta(dataset, source)
        if source_meta['band_count'] < 7 or source_meta['descriptions'][-1] not in ('ST_B10', 'LST', 'THERMAL'):
            raise CommandError('A/B RSEI 必须使用包含明确 ST_B10/LST 的已校准 7 波段输入。')

        image = RemoteSensingImage.objects.create(
            name=f'真实 Landsat RSEI A/B-{mode}-{uuid.uuid4().hex[:10]}', image_type='landsat9',
            file_path=relative_path, center_lat=34.58, center_lon=105.72, acquisition_date='2025-07-26',
        )
        task = ProcessingTask.objects.create(
            remote_sensing_image=image, task_type=f'rsei_ab_{mode}', status='processing',
            request_payload={'indices': list(COMPONENTS), 'benchmark_mode': mode}, queue_name='geo.heavy',
        )
        output_dir = Path(settings.MEDIA_ROOT) / 'ecological_indices' / str(image.id)
        output_dir.mkdir(parents=True, exist_ok=True)

        process = psutil.Process(os.getpid())
        samples, stop = [], threading.Event()
        io_start = psutil.disk_io_counters()
        def monitor():
            process.cpu_percent(None)
            while not stop.wait(options['sample_seconds']):
                try:
                    samples.append({'at': time.time(), 'rss_bytes': process.memory_info().rss, 'cpu_percent': process.cpu_percent(None)})
                except psutil.Error:
                    pass
        thread = threading.Thread(target=monitor, daemon=True)
        thread.start()
        phases = {}
        calculator = EcologicalIndexCalculator(str(source))
        if mode == 'legacy':
            calculator.preview_max_dimension = None
            calculator.statistics_chunk_rows = 0
            calculator.output_options = {}
        elif mode == 'optimized':
            # 存储/I-O 优先档：显式启用压缩，不依赖进程环境。
            calculator.output_options.update({'compress': 'deflate', 'predictor': 3})

        def phase(name, callback):
            started = time.perf_counter()
            value = callback()
            phases[name] = round(phases.get(name, 0.0) + time.perf_counter() - started, 6)
            return value

        records, arrays = {}, {}
        wall_started = time.perf_counter()
        try:
            if not phase('image_read', calculator.load_image):
                raise CommandError('无法读取真实 Landsat 输入。')
            methods = {name: getattr(calculator, f'calculate_{name}') for name in COMPONENTS}
            for name in COMPONENTS:
                arrays[name] = phase(f'component_{name}', methods[name])
                if arrays[name] is None:
                    raise CommandError(f'分量计算失败：{name}')
                stats = phase('statistics', lambda item=arrays[name]: calculator.calculate_statistics(item))
                records[name] = self._persist_index(image, name, item=arrays[name], stats=stats, calculator=calculator, output_dir=output_dir, phase=phase)

            # legacy 刻意不传 arrays，复现旧任务的重复分量计算；optimized 复用同一批数组。
            rsei = phase('rsei_total', lambda: calculator.calculate_rsei(None if mode == 'legacy' else arrays))
            if not rsei:
                raise CommandError('RSEI PCA 计算失败。')
            phases.update({key: round(phases.get(key, 0.0) + value, 6) for key, value in calculator.stage_timings.items()})
            rsei_stats = phase('statistics', lambda: calculator.calculate_statistics(rsei['rsei']))
            records['rsei'] = self._persist_index(image, 'rsei', item=rsei['rsei'], stats=rsei_stats, calculator=calculator, output_dir=output_dir, phase=phase)
            phase('database_persist', lambda: RSEIResult.objects.create(
                remote_sensing_image=image, greenness=records['greenness'], wetness=records['wetness'],
                dryness=records['dryness'], heat=records['heat'], rsei_result=records['rsei'],
                pc1_variance=float(rsei['pca_variance'][0]), pc2_variance=float(rsei['pca_variance'][1]),
                pc3_variance=float(rsei['pca_variance'][2]), pc4_variance=float(rsei['pca_variance'][3]),
                greenness_weight=float(rsei['pca_components'][0][0]), wetness_weight=float(rsei['pca_components'][0][1]),
                dryness_weight=float(rsei['pca_components'][0][2]), heat_weight=float(rsei['pca_components'][0][3]),
            ))
            task.status, task.progress = 'completed', 100
            task.save(update_fields=['status', 'progress'])
        except Exception:
            task.status = 'failed'
            task.save(update_fields=['status'])
            raise
        finally:
            calculator.close()
            gc.collect()
            stop.set(); thread.join(timeout=3)

        io_end = psutil.disk_io_counters()
        files = [self._file_meta(Path(record.result_file.path)) for record in records.values()]
        report = {
            'mode': mode, 'measurement_scope': '真实 Landsat RSEI：读取、四分量、PCA、统计、GeoTIFF、PNG 与数据库落库',
            'source': source_meta, 'image_id': str(image.id), 'task_id': str(task.id),
            'phases_seconds': phases, 'wall_seconds': round(time.perf_counter() - wall_started, 6),
            'worker_rss_peak_bytes': max((item['rss_bytes'] for item in samples), default=process.memory_info().rss),
            'worker_cpu_peak_percent': max((item['cpu_percent'] for item in samples), default=0),
            'disk_io_bytes': {'read': max(0, io_end.read_bytes - io_start.read_bytes), 'write': max(0, io_end.write_bytes - io_start.write_bytes)},
            'output_files': files, 'output_bytes_total': sum(item['bytes'] for item in files),
            'statistics': {name: self._stats(record) for name, record in records.items()}, 'monitor_samples': samples,
            'output_directory': str(output_dir), 'database_persisted': True,
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        csv_path = report_path.with_suffix('.csv')
        with csv_path.open('w', newline='', encoding='utf-8-sig') as stream:
            writer = csv.DictWriter(stream, fieldnames=['mode', 'index_type', 'file', 'bytes', 'min', 'max', 'mean', 'std'])
            writer.writeheader()
            for name, record in records.items():
                writer.writerow({'mode': mode, 'index_type': name, 'file': record.result_file.path, 'bytes': Path(record.result_file.path).stat().st_size,
                                 'min': record.min_value, 'max': record.max_value, 'mean': record.mean_value, 'std': record.std_value})
        self.stdout.write(self.style.SUCCESS(f'JSON：{report_path}'))
        self.stdout.write(self.style.SUCCESS(f'CSV：{csv_path}'))

    def _persist_index(self, image, name, item, stats, calculator, output_dir, phase):
        tif = output_dir / f'{name}_result.tif'
        png = output_dir / f'{name}_visualization.png'
        if not phase('geotiff_write', lambda: calculator.save_result(item, str(tif))):
            raise CommandError(f'写入失败：{name}')
        if not phase('png_visualization', lambda: calculator.create_visualization(item, name.upper(), str(png))):
            raise CommandError(f'PNG 预览失败：{name}')
        return phase('database_persist', lambda: EcologicalIndex.objects.create(
            remote_sensing_image=image, index_type=name,
            result_file=f'ecological_indices/{image.id}/{tif.name}', visualization_file=f'ecological_indices/{image.id}/{png.name}',
            min_value=stats['min_value'], max_value=stats['max_value'], mean_value=stats['mean_value'], std_value=stats['std_value'],
            excellent_area=stats['excellent_area'], good_area=stats['good_area'], moderate_area=stats['moderate_area'],
            poor_area=stats['poor_area'], bad_area=stats['bad_area'],
        ))

    @staticmethod
    def _raster_meta(dataset, path):
        return {'path': str(path), 'bytes': path.stat().st_size, 'width': dataset.width, 'height': dataset.height,
                'band_count': dataset.count, 'dtypes': list(dataset.dtypes), 'descriptions': list(dataset.descriptions),
                'crs': str(dataset.crs), 'transform': tuple(dataset.transform), 'nodata': dataset.nodata,
                'tiled': dataset.is_tiled, 'block_shapes': dataset.block_shapes, 'compression': dataset.compression.name if dataset.compression else None}

    @staticmethod
    def _file_meta(path):
        with rasterio.open(path) as dataset:
            meta = Command._raster_meta(dataset, path)
        return meta

    @staticmethod
    def _stats(record):
        return {key: getattr(record, f'{key}_value') for key in ('min', 'max', 'mean', 'std')}
