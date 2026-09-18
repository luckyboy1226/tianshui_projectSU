"""对运行中的 API 做真实 HTTP 并发压测，默认验证重复提交去重。"""

import json
import math
from pathlib import Path
import secrets
import statistics
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from environment.models import ProcessingTask, RemoteSensingImage


class Command(BaseCommand):
    help = '真实 HTTP 压测生态指数任务提交接口，并核验高并发下只创建一项任务。'

    def add_arguments(self, parser):
        parser.add_argument('--base-url', default='http://127.0.0.1:8081', help='运行中的 API 地址（默认经 Nginx）')
        parser.add_argument('--requests', type=int, default=300, help='总请求数')
        parser.add_argument('--concurrency', type=int, default=32, help='并发数')
        parser.add_argument(
            '--authenticated',
            action='store_true',
            help='通过真实登录接口获取 Session/CSRF 后压测受认证保护的生产写接口',
        )
        parser.add_argument('--keep-data', action='store_true', help='保留本次创建的影像和任务记录')
        parser.add_argument('--report-file', help='可选：将原始 JSON 结果写入该文件')

    def handle(self, *args, **options):
        total = options['requests']
        workers = options['concurrency']
        if total < 1 or workers < 1:
            raise CommandError('--requests 与 --concurrency 必须大于 0')

        image = RemoteSensingImage.objects.create(
            name=f'并发压测占位影像-{uuid.uuid4().hex[:8]}',
            image_type='custom',
            file_path='benchmark/placeholder.tif',
            center_lat=34.58,
            center_lon=105.72,
            acquisition_date=date.today(),
        )
        baseline = ProcessingTask.objects.filter(remote_sensing_image=image).count()
        base_url = options['base_url'].rstrip('/')
        endpoint = f'{base_url}/api/v1/environment/remote-sensing-images/{image.id}/calculate_indices/'
        payload = json.dumps({'indices': ['ndvi', 'ndwi'], 'priority': 'normal'}).encode('utf-8')
        shared_key = f'benchmark-{uuid.uuid4().hex}'
        benchmark_user = None
        auth_headers = {}

        if options['authenticated']:
            username = f'benchmark_{uuid.uuid4().hex[:16]}'
            password = secrets.token_urlsafe(24)
            benchmark_user = get_user_model().objects.create_user(
                username=username,
                password=password,
            )
            cookie_jar = CookieJar()
            opener = build_opener(HTTPCookieProcessor(cookie_jar))
            login_request = Request(
                f'{base_url}/api/v1/users/login/',
                data=json.dumps({'username': username, 'password': password}).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            try:
                with opener.open(login_request, timeout=20) as response:
                    if response.status != 200:
                        raise CommandError(f'压测账号登录失败，HTTP {response.status}')
            except (HTTPError, URLError, TimeoutError) as exc:
                benchmark_user.delete()
                image.delete()
                raise CommandError(f'压测账号登录失败：{exc}') from exc

            cookies = {cookie.name: cookie.value for cookie in cookie_jar}
            session_cookie = cookies.get('sessionid')
            csrf_cookie = cookies.get('csrftoken')
            if not session_cookie or not csrf_cookie:
                benchmark_user.delete()
                image.delete()
                raise CommandError('压测账号登录未返回 sessionid/csrftoken，无法验证生产写接口。')
            auth_headers = {
                'Cookie': f'sessionid={session_cookie}; csrftoken={csrf_cookie}',
                'X-CSRFToken': csrf_cookie,
            }

        def send_one(sequence):
            started = time.perf_counter()
            request = Request(
                endpoint,
                data=payload,
                headers={
                    'Content-Type': 'application/json',
                    'X-Idempotency-Key': shared_key,
                    'X-Benchmark-Request': str(sequence),
                    **auth_headers,
                },
                method='POST',
            )
            try:
                with urlopen(request, timeout=20) as response:
                    body = json.loads(response.read().decode('utf-8'))
                    return response.status, body, (time.perf_counter() - started) * 1000
            except HTTPError as exc:
                body = exc.read().decode('utf-8', errors='replace')
                return exc.code, {'error': body}, (time.perf_counter() - started) * 1000
            except URLError as exc:
                return 0, {'error': str(exc.reason)}, (time.perf_counter() - started) * 1000
            except (TimeoutError, ValueError) as exc:
                return 0, {'error': str(exc)}, (time.perf_counter() - started) * 1000
            except Exception as exc:
                return 0, {'error': str(exc)}, (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        results = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(send_one, number) for number in range(total)]
            for future in as_completed(futures):
                results.append(future.result())
        elapsed = time.perf_counter() - started

        created_tasks = list(ProcessingTask.objects.filter(remote_sensing_image=image).values_list('id', flat=True))
        statuses = [item[0] for item in results]
        latencies = sorted(item[2] for item in results)
        successful = [item for item in results if item[0] == 202]
        error_samples = [
            {'status': item[0], 'body': item[1]}
            for item in results if item[0] != 202
        ][:3]
        returned_ids = {item[1].get('task_id') for item in successful if item[1].get('task_id')}
        percentile = lambda p: latencies[min(len(latencies) - 1, math.ceil(len(latencies) * p) - 1)]
        report = {
            'endpoint': endpoint,
            'measurement_scope': '任务提交控制面（未启动 GIS Worker；不代表 GeoTIFF 栅格计算吞吐）',
            'authenticated_request': bool(options['authenticated']),
            'requests': total,
            'concurrency': workers,
            'http_202': len(successful),
            'http_errors': total - len(successful),
            'error_samples': error_samples,
            'elapsed_seconds': round(elapsed, 3),
            'throughput_rps': round(total / elapsed, 2),
            'latency_ms': {
                'avg': round(statistics.fmean(latencies), 2),
                'p50': round(percentile(0.50), 2),
                'p95': round(percentile(0.95), 2),
                'p99': round(percentile(0.99), 2),
                'max': round(max(latencies), 2),
            },
            'database_tasks_created': len(created_tasks) - baseline,
            'distinct_task_ids_returned': len(returned_ids),
            'duplicate_suppression_passed': len(successful) == total and len(created_tasks) - baseline == 1 and len(returned_ids) == 1,
        }
        report_json = json.dumps(report, ensure_ascii=False, indent=2)
        self.stdout.write(report_json)
        if options['report_file']:
            report_file = Path(options['report_file']).expanduser().resolve()
            report_file.parent.mkdir(parents=True, exist_ok=True)
            report_file.write_text(report_json + '\n', encoding='utf-8')
            self.stdout.write(self.style.SUCCESS(f'原始结果已写入: {report_file}'))

        if not options['keep_data']:
            # 任务已发布到 Broker 后不能直接删掉影像/任务记录：尚未启动的
            # Worker 会取到一条指向不存在对象的消息。标记取消可让 Worker
            # 在读取影像前安全忽略这条压测消息，同时释放幂等活跃锁。
            ProcessingTask.objects.filter(remote_sensing_image=image).update(
                status='cancelled',
                active_fingerprint=None,
                current_step='压测完成，等待 Worker 安全忽略',
            )
            if benchmark_user is not None:
                benchmark_user.delete()
            self.stdout.write('压测任务已标记取消；Worker 消费到消息后会在 GIS 计算前安全忽略。')

        if not report['duplicate_suppression_passed']:
            raise CommandError('压测未通过：检查运行服务、迁移状态、Nginx 限流或数据库锁配置。')
