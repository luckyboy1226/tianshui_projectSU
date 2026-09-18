"""Run real authenticated GeoTIFF processing benchmarks through the HTTP task API."""

from __future__ import annotations

import csv
from datetime import date
import math
from http.cookiejar import CookieJar
import json
from pathlib import Path
import platform
import secrets
import statistics
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

import psutil
import rasterio
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

from environment.models import EcologicalIndex, ProcessingTask, RemoteSensingImage


FINAL_STATES = {'completed', 'failed', 'cancelled'}


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    # Nearest-rank percentiles: for a small capacity-test batch, P95/P99 must
    # still expose the slowest scene instead of being rounded down to P50.
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * fraction) - 1))
    return round(ordered[index], 3)


def milliseconds(delta):
    return round(delta.total_seconds() * 1000, 3) if delta is not None else None


class Command(BaseCommand):
    help = '通过 Nginx/HTTP、Redis/Celery 和真实 GeoTIFF 执行端到端 GIS 任务压测。'

    def add_arguments(self, parser):
        parser.add_argument('--base-url', default='http://127.0.0.1:8081')
        parser.add_argument('--media-path', required=True, help='相对于 Django MEDIA_ROOT 的真实 GeoTIFF 路径')
        parser.add_argument('--indices', nargs='+', required=True, help='例如 ndvi 或 greenness wetness dryness heat')
        parser.add_argument('--tasks', type=int, default=1)
        parser.add_argument('--submit-concurrency', type=int, default=1)
        parser.add_argument('--worker-concurrency', type=int, required=True, help='仅记录实际已启动 Worker 的并发度')
        parser.add_argument('--worker-pid', type=int, required=True, help='Celery 主 Worker 的 PID，用于采集 CPU/内存')
        parser.add_argument('--timeout-seconds', type=int, default=3600)
        parser.add_argument('--sample-seconds', type=float, default=0.5)
        parser.add_argument('--report-file', required=True)

    def handle(self, *args, **options):
        task_count = options['tasks']
        if task_count < 1:
            raise CommandError('--tasks 必须大于 0')
        media_path = str(options['media_path']).replace('\\', '/')
        raster_path = Path(settings.MEDIA_ROOT) / media_path
        if not raster_path.is_file():
            raise CommandError(f'真实 GeoTIFF 不存在：{raster_path}')

        with rasterio.open(raster_path) as dataset:
            raster_metadata = {
                'path': str(raster_path),
                'bytes': raster_path.stat().st_size,
                'width': dataset.width,
                'height': dataset.height,
                'band_count': dataset.count,
                'dtypes': list(dataset.dtypes),
                'crs': str(dataset.crs),
                'resolution': list(dataset.res),
                'nodata': dataset.nodata,
                'descriptions': list(dataset.descriptions),
                'scales': list(dataset.scales),
                'offsets': list(dataset.offsets),
            }

        base_url = options['base_url'].rstrip('/')
        username = f'gis_benchmark_{uuid.uuid4().hex[:16]}'
        password = secrets.token_urlsafe(24)
        benchmark_user = get_user_model().objects.create_user(username=username, password=password)
        cookie_jar = CookieJar()
        opener = build_opener(HTTPCookieProcessor(cookie_jar))
        try:
            login_request = Request(
                f'{base_url}/api/v1/users/login/',
                data=json.dumps({'username': username, 'password': password}).encode('utf-8'),
                headers={'Content-Type': 'application/json'}, method='POST',
            )
            with opener.open(login_request, timeout=20) as response:
                if response.status != 200:
                    raise CommandError(f'压测登录失败：HTTP {response.status}')
            cookies = {cookie.name: cookie.value for cookie in cookie_jar}
            if not cookies.get('sessionid') or not cookies.get('csrftoken'):
                raise CommandError('压测登录未获得 Session/CSRF Cookie')
            auth_headers = {
                'Cookie': f"sessionid={cookies['sessionid']}; csrftoken={cookies['csrftoken']}",
                'X-CSRFToken': cookies['csrftoken'],
            }

            images = [
                RemoteSensingImage.objects.create(
                    name=f'真实 Landsat 端到端压测-{uuid.uuid4().hex[:10]}',
                    image_type='custom', file_path=media_path,
                    center_lat=34.58, center_lon=105.72,
                    acquisition_date=date(2025, 7, 26),
                    # 登录用户仅用于走真实 Session/CSRF 提交链路。影像本身不
                    # 关联该临时用户，避免 finally 删除账号时级联删掉已验证的
                    # 任务/结果落库记录；压测结束后由专用清理命令按报告清理。
                    uploaded_by=None,
                )
                for _ in range(task_count)
            ]

            monitor_stop = threading.Event()
            monitor_samples = []
            monitor_error = []

            def monitor():
                try:
                    worker = psutil.Process(options['worker_pid'])
                    processes = [worker] + worker.children(recursive=True)
                    for process in processes:
                        try:
                            process.cpu_percent(interval=None)
                        except psutil.Error:
                            pass
                    try:
                        import redis
                        redis_client = redis.Redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=1)
                    except Exception:
                        redis_client = None
                    while not monitor_stop.wait(options['sample_seconds']):
                        processes = [worker] + worker.children(recursive=True)
                        cpu = rss = 0.0
                        for process in processes:
                            try:
                                cpu += process.cpu_percent(interval=None)
                                rss += process.memory_info().rss
                            except psutil.Error:
                                pass
                        queue_length = None
                        if redis_client is not None:
                            try:
                                queue_length = sum(redis_client.llen(queue) for queue in ('geo.high', 'geo.default', 'geo.low', 'geo.heavy'))
                            except Exception:
                                queue_length = None
                        monitor_samples.append({
                            'at': timezone.now().isoformat(), 'cpu_percent': round(cpu, 3),
                            'rss_bytes': int(rss), 'queue_length': queue_length,
                            'system_memory_used_bytes': psutil.virtual_memory().used,
                            'system_memory_available_bytes': psutil.virtual_memory().available,
                            # psutil on Windows expects a string path; Django exposes
                            # MEDIA_ROOT as a pathlib.Path in this project.
                            'disk_used_bytes': psutil.disk_usage(str(settings.MEDIA_ROOT)).used,
                        })
                except Exception as exc:
                    monitor_error.append(str(exc))

            monitor_thread = threading.Thread(target=monitor, name='gis-benchmark-monitor', daemon=True)
            monitor_thread.start()
            submitted_at = {}

            def submit(image):
                started = time.perf_counter()
                submitted_at[str(image.id)] = timezone.now()
                request = Request(
                    f'{base_url}/api/v1/environment/remote-sensing-images/{image.id}/calculate_indices/',
                    data=json.dumps({'indices': options['indices'], 'priority': 'normal'}).encode('utf-8'),
                    headers={
                        'Content-Type': 'application/json',
                        'X-Idempotency-Key': f'gis-e2e-{uuid.uuid4().hex}',
                        **auth_headers,
                    }, method='POST',
                )
                try:
                    with urlopen(request, timeout=60) as response:
                        return str(image.id), response.status, json.loads(response.read().decode('utf-8')), (time.perf_counter() - started) * 1000
                except HTTPError as exc:
                    return str(image.id), exc.code, {'error': exc.read().decode('utf-8', errors='replace')}, (time.perf_counter() - started) * 1000
                except (URLError, TimeoutError) as exc:
                    return str(image.id), 0, {'error': str(exc)}, (time.perf_counter() - started) * 1000

            wall_started = time.perf_counter()
            submitted = []
            with ThreadPoolExecutor(max_workers=min(task_count, options['submit_concurrency'])) as executor:
                futures = [executor.submit(submit, image) for image in images]
                for future in as_completed(futures):
                    submitted.append(future.result())

            task_ids = [item[2].get('task_id') for item in submitted if item[1] == 202 and item[2].get('task_id')]
            deadline = time.monotonic() + options['timeout_seconds']
            while time.monotonic() < deadline:
                task_rows = list(ProcessingTask.objects.filter(id__in=task_ids))
                if len(task_rows) == len(task_ids) and all(row.status in FINAL_STATES for row in task_rows):
                    break
                time.sleep(1)
            task_rows = list(ProcessingTask.objects.filter(id__in=task_ids).select_related('remote_sensing_image'))
            monitor_stop.set()
            monitor_thread.join(timeout=5)
            wall_elapsed = time.perf_counter() - wall_started

            rows = []
            for task in task_rows:
                image = task.remote_sensing_image
                output_records = EcologicalIndex.objects.filter(remote_sensing_image=image)
                result_files = []
                for index in output_records:
                    candidate = Path(settings.MEDIA_ROOT) / str(index.result_file)
                    if candidate.is_file():
                        result_files.append({'index_type': index.index_type, 'path': str(candidate), 'bytes': candidate.stat().st_size})
                queue_wait = milliseconds(task.started_at - task.created_at) if task.started_at else None
                execution = milliseconds(task.completed_at - task.started_at) if task.completed_at and task.started_at else None
                e2e = milliseconds(task.completed_at - submitted_at[str(image.id)]) if task.completed_at else None
                rows.append({
                    'task_id': str(task.id), 'image_id': str(image.id), 'status': task.status,
                    'dispatch_status': task.dispatch_status, 'dispatch_attempts': task.dispatch_attempts,
                    'queue_wait_ms': queue_wait, 'execution_ms': execution, 'end_to_end_ms': e2e,
                    'error_message': task.error_message, 'result_files': result_files,
                    'result_bytes': sum(item['bytes'] for item in result_files),
                })

            successful = [row for row in rows if row['status'] == 'completed']
            try:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()')
                    database_connection_count = cursor.fetchone()[0]
            except Exception:
                database_connection_count = None
            def summary(field):
                values = [row[field] for row in successful if row[field] is not None]
                return {'p50': percentile(values, .5), 'p95': percentile(values, .95), 'p99': percentile(values, .99), 'max': max(values) if values else None}

            report = {
                'measurement_scope': '真实 GeoTIFF 端到端处理：HTTP 提交、PostgreSQL、Redis、Celery、Rasterio/GDAL、结果文件与数据库落库',
                'started_at': timezone.now().isoformat(), 'base_url': base_url,
                'raster': raster_metadata, 'indices': options['indices'],
                'tasks_total': task_count, 'tasks_success': len(successful),
                'tasks_failed': len(rows) - len(successful),
                'success_rate': round(len(successful) / task_count, 4),
                'submit_http_202': sum(1 for item in submitted if item[1] == 202),
                'submission_latencies_ms': [round(item[3], 3) for item in submitted],
                'worker_concurrency': options['worker_concurrency'], 'worker_pid': options['worker_pid'],
                'wall_seconds': round(wall_elapsed, 3),
                'throughput_tasks_per_minute': round(len(successful) / wall_elapsed * 60, 3) if wall_elapsed else None,
                'queue_wait_ms': summary('queue_wait_ms'), 'execution_ms': summary('execution_ms'),
                'end_to_end_ms': summary('end_to_end_ms'), 'result_bytes_total': sum(row['result_bytes'] for row in rows),
                'worker_cpu_peak_percent': max((sample['cpu_percent'] for sample in monitor_samples), default=None),
                'worker_memory_peak_bytes': max((sample['rss_bytes'] for sample in monitor_samples), default=None),
                'system_memory_peak_used_bytes': max((sample['system_memory_used_bytes'] for sample in monitor_samples), default=None),
                'system_memory_min_available_bytes': min((sample['system_memory_available_bytes'] for sample in monitor_samples), default=None),
                'disk_peak_used_bytes': max((sample['disk_used_bytes'] for sample in monitor_samples), default=None),
                'redis_queue_peak': max((sample['queue_length'] for sample in monitor_samples if sample['queue_length'] is not None), default=None),
                'database_connection_count_after': database_connection_count,
                'monitor_errors': monitor_error, 'monitor_samples': monitor_samples,
                'machine': {'platform': platform.platform(), 'logical_cpus': psutil.cpu_count(), 'memory_total_bytes': psutil.virtual_memory().total},
                'tasks': rows,
            }
            report_path = Path(options['report_file']).expanduser().resolve()
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            csv_path = report_path.with_suffix('.csv')
            with csv_path.open('w', newline='', encoding='utf-8-sig') as stream:
                writer = csv.DictWriter(stream, fieldnames=['task_id', 'image_id', 'status', 'dispatch_status', 'dispatch_attempts', 'queue_wait_ms', 'execution_ms', 'end_to_end_ms', 'result_bytes', 'error_message'])
                writer.writeheader()
                writer.writerows([{key: row.get(key) for key in writer.fieldnames} for row in rows])
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
            self.stdout.write(self.style.SUCCESS(f'原始 JSON：{report_path}'))
            self.stdout.write(self.style.SUCCESS(f'原始 CSV：{csv_path}'))
            if len(successful) != task_count:
                raise CommandError('端到端压测存在失败/超时任务，详见原始报告。')
        finally:
            benchmark_user.delete()
