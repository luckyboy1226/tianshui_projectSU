
"""
Django settings for tianshuipy project - 开发环境配置
使用SQLite数据库，简化部署
"""

from pathlib import Path
import os


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def env_list(name, default=None):
    value = os.getenv(name)
    if value is None:
        return list(default or [])
    return [item.strip() for item in value.split(',') if item.strip()]

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Quick-start development settings - unsuitable for production
SECRET_KEY = os.getenv('SECRET_KEY', "django-insecure-@jmeepv1459j^#n1nfu@87jcfkcp_ia@jip2)m=k#h7n6@89lw")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env_bool('DEBUG', True)

ALLOWED_HOSTS = env_list('ALLOWED_HOSTS', ['*'])

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    # 自定义应用
    "users",
    "environment",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "tianshuipy.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "tianshuipy.wsgi.application"

# Database - 使用SQLite简化开发
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Internationalization
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [
    BASE_DIR / "static",
]

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# 自定义用户模型
AUTH_USER_MODEL = 'users.User'

# 开发环境行为开关：默认保持演示友好
ALLOW_PUBLIC_USER_REGISTRATION = env_bool('ALLOW_PUBLIC_USER_REGISTRATION', True)
ALLOW_ANONYMOUS_ANALYSIS_UPLOADS = env_bool('ALLOW_ANONYMOUS_ANALYSIS_UPLOADS', True)
ALLOW_ANONYMOUS_BUSINESS_LAYER_ADMIN = env_bool('ALLOW_ANONYMOUS_BUSINESS_LAYER_ADMIN', True)
ALLOW_ANONYMOUS_OVERLAY_ADMIN = env_bool('ALLOW_ANONYMOUS_OVERLAY_ADMIN', True)
ALLOW_PUBLIC_FEEDBACK_MANAGEMENT = env_bool('ALLOW_PUBLIC_FEEDBACK_MANAGEMENT', True)

# REST Framework 配置
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',  # 开发环境允许匿名访问
    ],
    'DEFAULT_SCHEMA_CLASS': 'rest_framework.schemas.openapi.AutoSchema',
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}

# CORS 配置 - 允许前端访问
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = env_list('CORS_ALLOWED_ORIGINS', [
    'http://localhost:3000',
    'http://127.0.0.1:3000',
    'http://localhost:5173',
    'http://127.0.0.1:5173',
])
CSRF_TRUSTED_ORIGINS = env_list('CSRF_TRUSTED_ORIGINS', CORS_ALLOWED_ORIGINS)

# 允许的请求头
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
    'x-request-time',  # 添加自定义请求时间头
    'x-idempotency-key',
]

# 允许的HTTP方法
CORS_ALLOW_METHODS = [
    'DELETE',
    'GET',
    'OPTIONS',
    'PATCH',
    'POST',
    'PUT',
]

# 文件上传配置
# 大遥感栅格不能放进内存处理；超过 10MB 的上传交给 Django 临时文件处理器落盘。
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024 * 1024
MAX_UPLOAD_SIZE = 10 * 1024 * 1024 * 1024
FILE_UPLOAD_HANDLERS = [
    'django.core.files.uploadhandler.MemoryFileUploadHandler',
    'django.core.files.uploadhandler.TemporaryFileUploadHandler',
]

# Celery 配置
# 默认也只受理、入队，不在 HTTP 请求线程执行 GIS；若要调试同步任务可显式设为 true。
CELERY_TASK_ALWAYS_EAGER = os.getenv('CELERY_TASK_ALWAYS_EAGER', 'false').lower() == 'true'
CELERY_TASK_EAGER_PROPAGATES = False
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', os.getenv('TIANSHUI_CELERY_BROKER_URL', 'memory://'))
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', os.getenv('TIANSHUI_CELERY_RESULT_BACKEND', 'cache+memory://'))

# 日志配置
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
        'file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'logs' / 'django.log',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['file'],
            'level': 'INFO',
            'propagate': True,
        },
    },
}

# 创建日志目录
os.makedirs(BASE_DIR / 'logs', exist_ok=True)

# 创建媒体文件目录
os.makedirs(BASE_DIR / 'media' / 'remote_sensing', exist_ok=True)
os.makedirs(BASE_DIR / 'media' / 'thumbnails', exist_ok=True)
os.makedirs(BASE_DIR / 'media' / 'ecological_indices', exist_ok=True)
os.makedirs(BASE_DIR / 'media' / 'visualizations', exist_ok=True)
os.makedirs(BASE_DIR / 'media' / 'overlay_analysis' / 'rasters', exist_ok=True)

# GeoServer配置（开发环境）
GEOSERVER_URL = os.getenv('GEOSERVER_URL', 'http://localhost:8080/geoserver')
GEOSERVER_USERNAME = os.getenv('GEOSERVER_USERNAME', 'admin')
GEOSERVER_PASSWORD = os.getenv('GEOSERVER_PASSWORD', 'geoserver')
GEOSERVER_WORKSPACE = os.getenv('GEOSERVER_WORKSPACE', 'tianshuipy')

# 地理空间服务配置
SPATIAL_SERVICES = {
    'WMS_ENABLED': True,
    'WFS_ENABLED': True,
    'WCS_ENABLED': True,
    'DEFAULT_CRS': 'EPSG:4326',
    'MAX_FEATURES': 10000,
}

# Celery配置
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_ENABLE_UTC = True
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30分钟
CELERY_TASK_SOFT_TIME_LIMIT = 25 * 60  # 25分钟
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_WORKER_MAX_TASKS_PER_CHILD = 1000
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_CONNECTION_TIMEOUT = 2
# 发布失败由 ProcessingTask outbox 记录并由 dispatch_pending_tasks 补投，
# 避免 HTTP 请求在 Broker 故障时无限等待。
CELERY_TASK_PUBLISH_RETRY = False
CELERY_TASK_DEFAULT_DELIVERY_MODE = 'persistent'
CELERY_TASK_DEFAULT_QUEUE = 'geo.default'
CELERY_TASK_QUEUES = {
    'geo.high': {'exchange': 'geo', 'routing_key': 'high'},
    'geo.default': {'exchange': 'geo', 'routing_key': 'default'},
    'geo.low': {'exchange': 'geo', 'routing_key': 'low'},
    'geo.heavy': {'exchange': 'geo', 'routing_key': 'heavy'},
}
CELERY_BROKER_TRANSPORT_OPTIONS = {'queue_order_strategy': 'priority'}
