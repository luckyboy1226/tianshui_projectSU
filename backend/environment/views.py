from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action, api_view, authentication_classes, permission_classes
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import AllowAny
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.http import HttpResponse
from django.utils import timezone
from django.utils.text import get_valid_filename
from celery import current_app
import os
import json
import base64
import logging
import requests
import time
import uuid
import re
import shutil
import zipfile
import numpy as np
import rasterio
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from PIL import Image
from matplotlib import colors as mpl_colors
from matplotlib import colormaps as mpl_colormaps
from rasterio.enums import Resampling
from rasterio.warp import transform_bounds

# 取消注释必要的导入
from .models import (
    RemoteSensingImage,
    EcologicalIndex,
    RSEIResult,
    ProcessingTask,
    CitizenFeedback,
    ClimateDataFile,
    ClimateAnalysisResult,
    BusinessLayer,
    BusinessLayerAuditLog,
    EcologicalIndexFile,
    EcologicalProjectFile,
    OverlayAnalysisTask
)
from .serializers import (
    RemoteSensingImageSerializer,
    EcologicalIndexSerializer,
    RSEIResultSerializer,
    ProcessingTaskSerializer,
    RemoteSensingImageUploadSerializer,
    EcologicalIndexCalculationSerializer,
    RSEICalculationSerializer,
    CitizenFeedbackSerializer,
    ClimateDataFileSerializer,
    ClimateDataFileUploadSerializer,
    ClimateAnalysisResultSerializer,
    ClimateAnalysisRequestSerializer,
    BusinessLayerSerializer,
    BusinessLayerStyleSerializer,
    BusinessLayerAuditLogSerializer,
    BusinessLayerServiceSerializer,
    BusinessLayerUploadSerializer,
    EcologicalIndexFileSerializer,
    EcologicalIndexFileUploadSerializer,
    EcologicalProjectFileSerializer,
    EcologicalProjectFileUploadSerializer,
    OverlayAnalysisTaskSerializer,
    OverlayAnalysisTaskCreateSerializer
)
from .tasks import calculate_ecological_indices, calculate_rsei_only
from .concurrency import (
    IdempotencyConflict,
    dispatch_processing_task,
    submit_ecological_task,
)
from .ecological_indices import EcologicalIndexCalculator
from .band_mapping import (
    get_band_scale_offset,
    get_tasseled_cap_coefficients,
    infer_rgb_bands,
    infer_standard_band_mapping,
    supported_remote_indices as infer_supported_remote_indices,
    thermal_band_is_calibrated,
)
from .raster_processing import (
    calculate_normalized_index_windowed,
    calculate_normalized_index_preview_stats,
    prepare_raster_upload,
    preview_array,
    raster_band_statistics,
    remove_tree,
    RasterioLandUseAnalyzer,
    validate_shapefile_zip,
)
try:
    from .gdal_land_use_analysis import LandUseAnalyzer
    from .vector_rasterize import rasterize_shapefile_to_tiff
    GDAL_IMPORT_ERROR = None
except ImportError as exc:
    LandUseAnalyzer = None
    rasterize_shapefile_to_tiff = None
    GDAL_IMPORT_ERROR = exc

try:
    import shapefile
    SHAPEFILE_IMPORT_ERROR = None
except ImportError as exc:
    shapefile = None
    SHAPEFILE_IMPORT_ERROR = exc
from .file_utils import safe_file_cleanup, get_cleanup_files

logger = logging.getLogger(__name__)
TRANSPARENT_PNG_BYTES = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQABpfZFQAAAAABJRU5ErkJggg=='
)


def _is_authenticated(user):
    return bool(user and user.is_authenticated)


def _allow_anonymous_analysis_uploads():
    return bool(getattr(settings, 'ALLOW_ANONYMOUS_ANALYSIS_UPLOADS', True))


def _allow_anonymous_business_layer_admin():
    return bool(getattr(settings, 'ALLOW_ANONYMOUS_BUSINESS_LAYER_ADMIN', True))


def _allow_anonymous_overlay_admin():
    return bool(getattr(settings, 'ALLOW_ANONYMOUS_OVERLAY_ADMIN', True))


def _allow_public_feedback_management():
    return bool(getattr(settings, 'ALLOW_PUBLIC_FEEDBACK_MANAGEMENT', True))


def _get_overlay_layer_configs():
    base_dir = os.path.join(settings.MEDIA_ROOT, 'ecological_projects')
    return {
        'ecology_synced': {
            'label': '系统RSEI结果',
            'store': 'ecology_rsei',
            'kind': 'raster',
            'layer_name': 'ecology_rsei',
            'paths': [
                os.path.join(base_dir, 'ecology_rsei.tif'),
            ],
        },
        'ecology_uploaded': {
            'label': '上传生态栅格',
            'store': 'ecology_uploaded',
            'kind': 'raster',
            'layer_name': 'ecology_uploaded',
            'paths': [
                os.path.join(base_dir, 'ecology_uploaded.tif'),
            ],
        },
        'economy': {
            'label': '经济数据矢量',
            'store': 'economy_vector_store',
            'kind': 'vector',
            'layer_name': 'economy_vector',
            'paths': [
                os.path.join(base_dir, 'economy_vector'),
            ],
        },
        'economy_point': {
            'label': '经济数据点图层',
            'store': 'economy_point_vector_store',
            'kind': 'vector',
            'layer_name': 'economy_point_vector',
            'paths': [
                os.path.join(base_dir, 'economy_point_vector'),
            ],
        },
        'economy_line': {
            'label': '经济数据线图层',
            'store': 'economy_line_vector_store',
            'kind': 'vector',
            'layer_name': 'economy_line_vector',
            'paths': [
                os.path.join(base_dir, 'economy_line_vector'),
            ],
        },
        'economy_polygon': {
            'label': '经济数据面图层',
            'store': 'economy_polygon_vector_store',
            'kind': 'vector',
            'layer_name': 'economy_polygon_vector',
            'paths': [
                os.path.join(base_dir, 'economy_polygon_vector'),
            ],
        },
        'engineering': {
            'label': '工程项目矢量',
            'store': 'engineering_vector_store',
            'kind': 'vector',
            'layer_name': 'engineering_vector',
            'paths': [
                os.path.join(base_dir, 'engineering_vector'),
            ],
        },
        'engineering_point': {
            'label': '工程项目点数据',
            'store': 'engineering_point_vector_store',
            'kind': 'vector',
            'layer_name': 'engineering_point_vector',
            'paths': [
                os.path.join(base_dir, 'engineering_point_vector'),
            ],
        },
        'engineering_line': {
            'label': '工程项目线数据',
            'store': 'engineering_line_vector_store',
            'kind': 'vector',
            'layer_name': 'engineering_line_vector',
            'paths': [
                os.path.join(base_dir, 'engineering_line_vector'),
            ],
        },
        'engineering_polygon': {
            'label': '工程项目面数据',
            'store': 'engineering_polygon_vector_store',
            'kind': 'vector',
            'layer_name': 'engineering_polygon_vector',
            'paths': [
                os.path.join(base_dir, 'engineering_polygon_vector'),
            ],
        },
    }


def _get_overlay_metadata_path():
    return os.path.join(settings.MEDIA_ROOT, 'ecological_projects', 'overlay_upload_metadata.json')


def _default_overlay_metadata():
    return {
        layer_type: {
            'description': '',
            'file_name': '',
            'layer_name': config['layer_name'],
            'updated_at': None,
            'source_type': '',
            'source_image_id': '',
            'source_image_name': '',
            'source_result_id': '',
            'source_result_created_at': None,
        }
        for layer_type, config in _get_overlay_layer_configs().items()
    }


def _load_overlay_metadata():
    metadata = _default_overlay_metadata()
    metadata_path = _get_overlay_metadata_path()
    if not os.path.exists(metadata_path):
        return metadata

    try:
        with open(metadata_path, 'r', encoding='utf-8') as fh:
            stored = json.load(fh)
        if isinstance(stored, dict):
            for layer_type in metadata.keys():
                layer_data = stored.get(layer_type)
                if isinstance(layer_data, dict):
                    metadata[layer_type].update(layer_data)
                    metadata[layer_type]['description'] = layer_data.get('description') or ''
                    metadata[layer_type]['file_name'] = layer_data.get('file_name') or ''
                    metadata[layer_type]['layer_name'] = layer_data.get('layer_name') or metadata[layer_type]['layer_name']
                    metadata[layer_type]['source_type'] = layer_data.get('source_type') or ''
    except Exception as exc:
        logger.warning(f"读取叠加分析上传元数据失败: {exc}")

    return metadata


def _save_overlay_metadata(metadata):
    metadata_path = _get_overlay_metadata_path()
    os.makedirs(os.path.dirname(metadata_path), exist_ok=True)
    with open(metadata_path, 'w', encoding='utf-8') as fh:
        json.dump(metadata, fh, ensure_ascii=False, indent=2)


def _update_overlay_metadata(layer_type, **updates):
    metadata = _load_overlay_metadata()
    if layer_type not in metadata:
        metadata[layer_type] = {}

    metadata[layer_type].update(updates)
    metadata[layer_type]['updated_at'] = timezone.now().isoformat()
    _save_overlay_metadata(metadata)
    return metadata[layer_type]


def _clear_overlay_metadata(layer_type):
    metadata = _load_overlay_metadata()
    config = _get_overlay_layer_configs().get(layer_type, {})
    metadata[layer_type] = {
        'description': '',
        'file_name': '',
        'layer_name': config.get('layer_name', ''),
        'updated_at': timezone.now().isoformat(),
        'source_type': '',
        'source_image_id': '',
        'source_image_name': '',
        'source_result_id': '',
        'source_result_created_at': None,
    }
    _save_overlay_metadata(metadata)


def _overlay_vector_geojson_url(layer_type):
    return f'/api/v1/environment/overlay-analysis-tasks/uploaded-vector-geojson/?data_type={layer_type}'


def _overlay_vector_shp_path(layer_type):
    config = _get_overlay_layer_configs().get(layer_type)
    if not config or config.get('kind') != 'vector':
        return None
    return os.path.join(config['paths'][0], f"{config['layer_name']}.shp")


def _geojson_geometry_bounds(geometry):
    bounds = [float('inf'), float('inf'), float('-inf'), float('-inf')]

    def visit_coordinates(coords):
        if not coords:
            return
        if isinstance(coords[0], (int, float)) and len(coords) >= 2:
            x, y = coords[0], coords[1]
            bounds[0] = min(bounds[0], x)
            bounds[1] = min(bounds[1], y)
            bounds[2] = max(bounds[2], x)
            bounds[3] = max(bounds[3], y)
            return
        for item in coords:
            visit_coordinates(item)

    if geometry:
        visit_coordinates(geometry.get('coordinates') or [])

    if bounds[0] == float('inf'):
        return None
    return bounds


def _geojson_feature_collection_bounds(geojson):
    aggregate = [float('inf'), float('inf'), float('-inf'), float('-inf')]
    for feature in geojson.get('features') or []:
        feature_bounds = _geojson_geometry_bounds(feature.get('geometry'))
        if not feature_bounds:
            continue
        aggregate[0] = min(aggregate[0], feature_bounds[0])
        aggregate[1] = min(aggregate[1], feature_bounds[1])
        aggregate[2] = max(aggregate[2], feature_bounds[2])
        aggregate[3] = max(aggregate[3], feature_bounds[3])

    if aggregate[0] == float('inf'):
        return None
    return aggregate


def _get_rsei_source(remote_sensing_image_id=None):
    rsei_queryset = (
        RSEIResult.objects
        .select_related('remote_sensing_image', 'rsei_result')
        .order_by('-created_at')
    )
    if remote_sensing_image_id:
        rsei_queryset = rsei_queryset.filter(remote_sensing_image_id=remote_sensing_image_id)

    latest_rsei = rsei_queryset.first()
    if latest_rsei and latest_rsei.rsei_result and latest_rsei.rsei_result.result_file:
        return latest_rsei.rsei_result, latest_rsei.remote_sensing_image, latest_rsei.created_at

    index_queryset = (
        EcologicalIndex.objects
        .select_related('remote_sensing_image')
        .filter(index_type='rsei')
        .exclude(result_file='')
        .order_by('-updated_at', '-created_at')
    )
    if remote_sensing_image_id:
        index_queryset = index_queryset.filter(remote_sensing_image_id=remote_sensing_image_id)

    latest_index = index_queryset.first()
    if latest_index and latest_index.result_file:
        return latest_index, latest_index.remote_sensing_image, latest_index.updated_at or latest_index.created_at

    return None, None, None


def _list_available_rsei_sources():
    sources = []
    indices = (
        EcologicalIndex.objects
        .select_related('remote_sensing_image')
        .filter(index_type='rsei')
        .exclude(result_file='')
        .order_by('-updated_at', '-created_at')
    )

    for index in indices:
        try:
            result_path = index.result_file.path
        except Exception:
            result_path = ''

        if not result_path or not os.path.exists(result_path):
            continue

        image = index.remote_sensing_image
        sources.append({
            'remote_sensing_image_id': str(image.id),
            'remote_sensing_image_name': image.name,
            'acquisition_date': image.acquisition_date.isoformat() if image.acquisition_date else None,
            'result_id': str(index.id),
            'result_file_name': os.path.basename(result_path),
            'updated_at': (index.updated_at or index.created_at).isoformat() if (index.updated_at or index.created_at) else None,
        })

    return sources


def _sync_latest_rsei_to_overlay(remote_sensing_image_id=None):
    overlay_config = _get_overlay_layer_configs()['ecology_synced']
    target_path = overlay_config['paths'][0]

    source_index, source_image, source_created_at = _get_rsei_source(remote_sensing_image_id=remote_sensing_image_id)
    if not source_index or not source_index.result_file:
        return {
            'success': False,
            'message': '未找到可用的RSEI结果，请先在遥感生态指数分析模块完成一次RSEI计算。',
            'reason': 'no_rsei_result'
        }

    try:
        source_path = source_index.result_file.path
    except Exception as exc:
        logger.warning(f"读取最新RSEI结果路径失败: {exc}")
        return {
            'success': False,
            'message': '最近一次RSEI结果文件路径无效，暂时无法同步。',
            'reason': 'invalid_result_path'
        }

    if not source_path or not os.path.exists(source_path):
        return {
            'success': False,
            'message': '最近一次RSEI结果文件不存在，暂时无法同步。',
            'reason': 'missing_result_file'
        }

    os.makedirs(os.path.dirname(target_path), exist_ok=True)

    try:
        same_file = os.path.exists(target_path) and os.path.samefile(source_path, target_path)
    except Exception:
        same_file = False

    try:
        if not same_file:
            shutil.copy2(source_path, target_path)
            logger.info(f"已将最近一次RSEI结果同步到叠加分析图层: {source_path} -> {target_path}")
    except Exception as exc:
        logger.error(f"同步最近一次RSEI结果失败: {exc}")
        return {
            'success': False,
            'message': f'复制最近一次RSEI结果失败: {exc}',
            'reason': 'copy_failed'
        }

    publish_success = False
    try:
        from .geoserver_config import geoserver_manager

        publish_success = geoserver_manager.publish_raster(
            coverage_store_name=overlay_config['store'],
            layer_name=overlay_config['layer_name'],
            file_path=target_path,
            style_type='ecology_rsei'
        )
    except Exception as exc:
        logger.error(f"发布同步后的RSEI图层失败: {exc}")

    image_name = getattr(source_image, 'name', '') or ''
    metadata = _update_overlay_metadata(
        'ecology_synced',
        description=f'系统自动同步最近一次RSEI结果：{image_name}' if image_name else '系统自动同步最近一次RSEI结果',
        file_name=os.path.basename(source_path),
        layer_name=overlay_config['layer_name'],
        source_type='selected_rsei' if remote_sensing_image_id else 'latest_rsei',
        source_image_id=str(getattr(source_image, 'id', '') or ''),
        source_image_name=image_name,
        source_result_id=str(source_index.id),
        source_result_created_at=source_created_at.isoformat() if source_created_at else None,
        service_mode='geoserver' if publish_success else 'local',
        geoserver_published=bool(publish_success),
    )

    return {
        'success': True,
        'message': 'RSEI结果已同步到叠加分析生态图层。' if publish_success else 'RSEI结果已同步，GeoServer未连接，当前使用本地栅格覆盖图显示。',
        'warning': None if publish_success else 'GeoServer发布失败，已启用本地覆盖图兜底。',
        'metadata': metadata,
        'layer_name': overlay_config['layer_name'],
        'source_path': source_path,
        'target_path': target_path,
    }

# 取消注释遥感影像视图集
class RemoteSensingImageViewSet(viewsets.ModelViewSet):
    """遥感影像视图集"""
    queryset = RemoteSensingImage.objects.all()
    serializer_class = RemoteSensingImageSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [permissions.AllowAny]  # 修改为允许所有请求

    def get_permissions(self):
        public_actions = {'list', 'retrieve', 'indices'}
        if self.action in public_actions or _allow_anonymous_analysis_uploads():
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]
    
    def get_serializer_class(self):
        """根据操作选择序列化器"""
        if self.action == 'create':
            return RemoteSensingImageUploadSerializer
        return RemoteSensingImageSerializer
    
    def perform_create(self, serializer):
        """创建时设置上传用户"""
        # 如果用户已认证，则设置上传用户，否则设为None
        if self.request.user.is_authenticated:
            serializer.save(uploaded_by=self.request.user)
        else:
            serializer.save(uploaded_by=None)
    
    @action(detail=True, methods=['post'])
    def calculate_indices(self, request, pk=None):
        """创建生态指数计算任务（支持幂等提交和跨实例去重）。"""
        try:
            image = self.get_object()
            indices_list = request.data.get('indices', ['ndvi', 'ndwi', 'ndbi'])
            if not isinstance(indices_list, list):
                return Response({'error': 'indices 必须是数组'}, status=status.HTTP_400_BAD_REQUEST)
            normalized_indices = [idx.lower() for idx in indices_list]
            valid_indices = ['ndvi', 'ndwi', 'ndbi', 'ndsi', 'wetness', 'dryness', 'heat', 'greenness']
            if not all(idx in valid_indices for idx in normalized_indices):
                return Response({'error': f'不支持的指数类型。支持的指数: {", ".join(valid_indices)}'}, status=status.HTTP_400_BAD_REQUEST)

            submission = submit_ecological_task(
                image=image,
                indices=normalized_indices,
                user=request.user,
                idempotency_key=request.headers.get('X-Idempotency-Key'),
                priority=request.data.get('priority', 'normal'),
            )
            task = dispatch_processing_task(submission.task) if submission.created else submission.task

            return Response({
                'message': '生态指数计算已受理' if submission.created else '检测到重复请求，已返回原任务',
                'task_id': str(task.id),
                'celery_task_id': task.celery_task_id or None,
                'indices': normalized_indices,
                'deduplicated': submission.deduplicated,
                'queue': task.queue_name,
                'dispatch_status': task.dispatch_status,
            }, status=status.HTTP_202_ACCEPTED)

        except IdempotencyConflict as exc:
            return Response({'error': str(exc)}, status=status.HTTP_409_CONFLICT)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.error(f"启动生态指数计算失败: {e}")
            return Response({
                'error': f'启动计算失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'])
    def indices(self, request, pk=None):
        """获取影像的生态指数列表及统计数据"""
        try:
            image = self.get_object()

            # 获取该影像的所有生态指数
            indices = EcologicalIndex.objects.filter(remote_sensing_image=image)

            if not indices.exists():
                response = Response({
                    'message': '该影像暂无生态指数数据',
                    'indices': []
                })
                response['Content-Type'] = 'application/json; charset=utf-8'
                return response

            # 序列化数据
            serializer = EcologicalIndexSerializer(indices, many=True)

            # 手动添加正确的中文显示文本
            indices_data = serializer.data
            for index_obj, index_data in zip(indices, indices_data):
                # 修复index_type_display
                index_type = index_data.get('index_type', '')
                index_type_display_map = {
                    'ndvi': 'NDVI - 归一化植被指数',
                    'ndwi': 'NDWI - 归一化水体指数',
                    'ndbi': 'NDBI - 归一化建筑指数',
                    'ndsi': 'NDSI - 归一化积雪指数',
                    'rsei': 'RSEI - 遥感生态指数',
                    'wetness': '湿度指数',
                    'dryness': '干度指数',
                    'heat': '热度指数',
                    'greenness': '绿度指数',
                }
                index_data['index_type_display'] = index_type_display_map.get(index_type, index_type.upper())
                
                # 修复remote_sensing_image中的processing_status_display
                if 'remote_sensing_image' in index_data:
                    processing_status = index_data['remote_sensing_image'].get('processing_status', '')
                    status_display_map = {
                        'pending': '等待中',
                        'processing': '处理中',
                        'completed': '已完成',
                        'failed': '失败',
                    }
                    index_data['remote_sensing_image']['processing_status_display'] = status_display_map.get(processing_status, processing_status)

                try:
                    index_data['compare_overlay'] = _build_compare_overlay_payload(
                        request=request,
                        raster_abs=index_obj.result_file.path if getattr(index_obj, 'result_file', None) else None,
                        result_file_rel=index_obj.result_file.name if getattr(index_obj, 'result_file', None) else None,
                        visualization_rel=index_obj.visualization_file.name if getattr(index_obj, 'visualization_file', None) else None,
                        source_filename=Path(index_obj.result_file.name).name if getattr(index_obj, 'result_file', None) else None,
                        style_hint=index_type,
                    )
                except Exception as overlay_exc:
                    logger.warning(f"补充 compare_overlay 失败: {overlay_exc}")
                    index_data['compare_overlay'] = None

            response = Response({
                'message': '获取生态指数成功',
                'count': indices.count(),
                'indices': indices_data
            })
            response['Content-Type'] = 'application/json; charset=utf-8'
            return response

        except Exception as e:
            logger.error(f"获取生态指数失败: {e}")
            response = Response({
                'error': f'获取生态指数失败: {str(e)}'
            }, status=500)
            response['Content-Type'] = 'application/json; charset=utf-8'
            return response


class EcologicalIndexViewSet(viewsets.ModelViewSet):
    """生态指数视图集"""
    queryset = EcologicalIndex.objects.select_related('remote_sensing_image').order_by('-created_at', '-id')
    serializer_class = EcologicalIndexSerializer
    permission_classes = [permissions.AllowAny]

    def get_permissions(self):
        public_actions = {'list', 'retrieve', 'statistics'}
        if self.action in public_actions or _allow_anonymous_analysis_uploads():
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]
    
    @action(detail=False, methods=['post'])
    def calculate(self, request):
        """按影像ID创建生态指数计算任务"""
        serializer = EcologicalIndexCalculationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        image_id = serializer.validated_data['remote_sensing_image_id']
        indices = serializer.validated_data['indices']
        image = get_object_or_404(RemoteSensingImage, id=image_id)
        
        try:
            submission = submit_ecological_task(
                image=image,
                indices=indices,
                user=request.user,
                idempotency_key=request.headers.get('X-Idempotency-Key'),
                priority=request.data.get('priority', 'normal'),
            )
        except IdempotencyConflict as exc:
            return Response({'error': str(exc)}, status=status.HTTP_409_CONFLICT)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        task = dispatch_processing_task(submission.task) if submission.created else submission.task
        
        return Response({
            'message': '生态指数计算已受理' if submission.created else '检测到重复请求，已返回原任务',
            'task_id': str(task.id),
            'celery_task_id': task.celery_task_id or None,
            'indices': indices,
            'deduplicated': submission.deduplicated,
            'queue': task.queue_name,
            'dispatch_status': task.dispatch_status,
        }, status=status.HTTP_202_ACCEPTED)
    
    @action(detail=True, methods=['get'])
    def statistics(self, request, pk=None):
        """获取单个生态指数统计信息"""
        index = self.get_object()
        return Response({
            'id': str(index.id),
            'index_type': index.index_type,
            'index_type_display': index.get_index_type_display(),
            'min_value': index.min_value,
            'max_value': index.max_value,
            'mean_value': index.mean_value,
            'std_value': index.std_value,
            'excellent_area': index.excellent_area,
            'good_area': index.good_area,
            'moderate_area': index.moderate_area,
            'poor_area': index.poor_area,
            'bad_area': index.bad_area,
        })


class RSEIResultViewSet(viewsets.ModelViewSet):
    """RSEI结果视图集"""
    queryset = RSEIResult.objects.select_related(
        'remote_sensing_image',
        'greenness',
        'wetness',
        'dryness',
        'heat',
        'rsei_result'
    ).order_by('-created_at', '-id')
    serializer_class = RSEIResultSerializer
    permission_classes = [permissions.AllowAny]

    def get_permissions(self):
        public_actions = {'list', 'retrieve'}
        if self.action in public_actions or _allow_anonymous_analysis_uploads():
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]
    
    @action(detail=False, methods=['post'])
    def calculate(self, request):
        """按影像ID创建RSEI计算任务"""
        serializer = RSEICalculationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        image_id = serializer.validated_data['remote_sensing_image_id']
        celery_task = calculate_rsei_only.delay(str(image_id))
        
        return Response({
            'message': 'RSEI计算已启动',
            'celery_task_id': str(celery_task.id),
            'remote_sensing_image_id': str(image_id)
        }, status=status.HTTP_201_CREATED)

class ProcessingTaskViewSet(viewsets.ModelViewSet):
    """处理任务视图集"""
    queryset = ProcessingTask.objects.all()
    serializer_class = ProcessingTaskSerializer
    permission_classes = [permissions.AllowAny]  # 允许所有请求

    def get_permissions(self):
        if _allow_anonymous_analysis_uploads():
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]
    
    def perform_create(self, serializer):
        """创建时设置创建用户"""
        # 如果用户已认证，则设置创建用户，否则设为None
        if self.request.user.is_authenticated:
            serializer.save(created_by=self.request.user)
        else:
            serializer.save(created_by=None)
    
    @action(detail=True, methods=['get'])
    def status(self, request, pk=None):
        """获取任务状态"""
        task = self.get_object()
        return Response({
            'id': task.id,
            'status': task.status,
            'status_display': task.get_status_display(),
            'progress': task.progress,
            'current_step': task.current_step,
            'error_message': task.error_message,
            'created_at': task.created_at,
            'started_at': task.started_at,
            'completed_at': task.completed_at,
            'queue': task.queue_name,
            'priority': task.priority,
            'celery_task_id': task.celery_task_id or None,
            'dispatch_status': task.dispatch_status,
            'dispatch_attempts': task.dispatch_attempts,
            'dispatching_at': task.dispatching_at,
            'last_dispatch_error': task.last_dispatch_error,
        })

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """取消尚未结束的任务，并释放数据库级 single-flight 锁。"""
        with transaction.atomic():
            task = ProcessingTask.objects.select_for_update().get(pk=pk)
            if task.status in {'completed', 'failed', 'cancelled'}:
                return Response({
                    'id': str(task.id),
                    'status': task.status,
                    'message': '任务已结束，无需重复取消',
                }, status=status.HTTP_200_OK)

            celery_task_id = task.celery_task_id
            task.status = 'cancelled'
            task.current_step = '已取消'
            task.completed_at = timezone.now()
            task.active_fingerprint = None
            task.save(update_fields=['status', 'current_step', 'completed_at', 'active_fingerprint'])

        if celery_task_id:
            try:
                # threads pool 无法安全强杀 GIS 代码；运行中的任务会在下一状态写入前看到
                # cancelled 状态，不会覆盖取消结果。
                current_app.control.revoke(celery_task_id, terminate=False)
            except Exception:
                logger.exception('撤销 Celery 任务失败，任务状态已在数据库中取消: %s', task.id)

        return Response({
            'id': str(task.id),
            'status': 'cancelled',
            'message': '任务已取消，已释放重复提交锁',
        }, status=status.HTTP_200_OK)

class CitizenFeedbackViewSet(viewsets.ModelViewSet):
    """民众意见反馈视图集"""
    queryset = CitizenFeedback.objects.all()
    serializer_class = CitizenFeedbackSerializer
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def get_permissions(self):
        if self.action == 'create':
            return [permissions.AllowAny()]
        if _allow_public_feedback_management():
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        if self.request.user.is_authenticated:
            serializer.save(created_by=self.request.user)
        else:
            serializer.save(created_by=None)

    @action(detail=False, methods=['delete'], url_path='clear')
    def clear(self, request):
        deleted_count = self.get_queryset().count()
        self.get_queryset().delete()
        return Response({
            'message': '反馈记录已清空',
            'deleted_count': deleted_count
        }, status=status.HTTP_200_OK)


REMOTE_INDEX_METHODS = {
    'ndvi': ('NDVI', 'calculate_ndvi'),
    'ndwi': ('NDWI', 'calculate_ndwi'),
    'ndbi': ('NDBI', 'calculate_ndbi'),
    'dryness': ('干度指数', 'calculate_dryness'),
    'wetness': ('湿度指数', 'calculate_wetness'),
    'heat': ('热度指数', 'calculate_heat'),
    'greenness': ('绿度指数', 'calculate_greenness'),
}


REMOTE_INDEX_LABELS = {
    'ndvi': '绿化指数(NDVI)',
    'ndwi': '湿度指数(NDWI)',
    'ndbi': '建筑指数(NDBI)',
    'dryness': '干度指数(NDBSI)',
    'wetness': '湿度指数(Tasseled Cap)',
    'heat': '热度指数(LST/Heat)',
    'greenness': '绿度指数',
    'rsei': '遥感生态指数(RSEI)',
    'uploaded_raster': '上传成果栅格',
}


def _supported_remote_indices(band_count=None, dataset=None, band_mapping=None):
    if band_count is None and dataset is not None:
        band_count = int(getattr(dataset, 'count', 0) or 0)
    mapping = band_mapping or infer_standard_band_mapping(dataset=dataset, band_count=band_count)
    return infer_supported_remote_indices(mapping=mapping, band_count=band_count, dataset=dataset)


def _unsupported_remote_index_response(index_type, band_count, band_mapping=None, dataset=None):
    supported_indices = infer_supported_remote_indices(mapping=band_mapping, band_count=band_count, dataset=dataset)
    requested_label = REMOTE_INDEX_LABELS.get(index_type, index_type.upper())
    supported_labels = [
        REMOTE_INDEX_LABELS.get(item, item.upper())
        for item in supported_indices
        if item != 'uploaded_raster'
    ]

    if index_type == 'rsei' and band_mapping and band_mapping.get('thermal') is None:
        detail = (
            f'当前影像为{band_count}波段，但缺少热红外/LST波段，不支持{requested_label}。'
            '标准RSEI除了绿度、湿度、干度，还必须有热度分量。'
        )
    elif index_type == 'rsei' and band_mapping and not get_tasseled_cap_coefficients(band_mapping.get('profile')):
        detail = (
            f'当前影像已识别出常用反射波段，但暂缺该传感器的标准湿度系数，不支持{requested_label}。'
            '如果要做严谨的RSEI，请为该传感器补充对应的Tasseled Cap / 湿度模型参数。'
        )
    elif index_type == 'rsei' and band_mapping and band_mapping.get('thermal') is not None and dataset is not None and not thermal_band_is_calibrated(mapping=band_mapping, dataset=dataset):
        detail = (
            f'当前影像包含热红外波段，但缺少可靠的温度量纲信息，不支持{requested_label}。'
            '请上传带有LST/温度scale-offset的标准产品，或先完成温度反演。'
        )
    elif index_type == 'wetness' and band_mapping and band_mapping.get('swir2') is None:
        detail = (
            f'当前影像为{band_count}波段，但缺少SWIR2波段，不支持{requested_label}。'
            'Tasseled Cap湿度分量需要 Blue/Green/Red/NIR/SWIR1/SWIR2 六个语义波段。'
        )
    elif index_type == 'wetness' and band_mapping and band_mapping.get('swir2') is not None and not get_tasseled_cap_coefficients(band_mapping.get('profile')):
        detail = (
            f'当前影像具备计算{requested_label}所需波段，但暂缺该传感器的标准湿度系数。'
            '请补充对应传感器系数后再计算，避免把其他卫星的系数直接套用到当前数据。'
        )
    elif index_type == 'heat' and band_mapping and band_mapping.get('thermal') is None:
        detail = (
            f'当前影像为{band_count}波段，但缺少热红外/LST波段，不支持{requested_label}。'
        )
    elif index_type == 'heat' and band_mapping and band_mapping.get('thermal') is not None and dataset is not None and not thermal_band_is_calibrated(mapping=band_mapping, dataset=dataset):
        detail = (
            f'当前影像包含热红外波段，但缺少可靠的温度量纲信息，不支持{requested_label}。'
            '请使用带温度scale/offset或LST单位的标准热红外产品。'
        )
    elif band_count == 4:
        detail = (
            f'当前影像为4波段，不支持{requested_label}。'
            '这类GF/PMS四波段影像通常可计算NDVI或NDWI；'
            '热度指数、干度指数和RSEI需要包含短波红外/热红外等更多有效波段的数据。'
        )
    elif index_type == 'rsei' and band_count == 6:
        detail = (
            f'当前影像为6波段反射波段数据，不支持{requested_label}。'
            '标准RSEI除绿度、湿度、干度外，还需要热度（LST/热红外）分量；'
            '请上传包含热红外波段的Landsat类影像，或改算当前影像支持的单项指数。'
        )
    elif band_count and band_count < 6:
        detail = (
            f'当前影像为{band_count}波段，不支持{requested_label}。'
            '请改选该影像支持的指数，或上传包含至少6个有效波段的多光谱影像。'
        )
    else:
        detail = f'当前影像不支持{requested_label}，请检查影像波段配置。'

    return Response({
        'error': detail,
        'bands_count': band_count,
        'requested_index': index_type,
        'supported_indices': supported_indices,
        'supported_index_labels': supported_labels,
    }, status=400)


def _save_uploaded_file(uploaded_file, subdir):
    safe_name = get_valid_filename(uploaded_file.name)
    relative_path = os.path.join(subdir, f'{uuid.uuid4().hex}_{safe_name}')
    absolute_path = os.path.join(settings.MEDIA_ROOT, relative_path)
    os.makedirs(os.path.dirname(absolute_path), exist_ok=True)
    with open(absolute_path, 'wb+') as destination:
        for chunk in uploaded_file.chunks():
            destination.write(chunk)
    return relative_path.replace('\\', '/'), absolute_path


def _remove_file_if_exists(path):
    if not path:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
    except PermissionError:
        logger.warning(f"无法删除文件 {path}，可能仍被占用")
    except Exception as exc:
        logger.warning(f"删除临时文件失败 {path}: {exc}")


def _cleanup_temp_paths(files=None, dirs=None):
    for path in files or []:
        _remove_file_if_exists(path)
    for path in dirs or []:
        try:
            remove_tree(path)
        except Exception as exc:
            logger.warning(f"删除临时目录失败 {path}: {exc}")


def _landuse_attribute_candidates(requested_attr=None):
    candidates = []
    for field in [requested_attr, 'class', 'landuse', 'code', 'class_id', 'dlbm', 'type', 'value']:
        field_name = str(field or '').strip()
        if field_name and field_name not in candidates:
            candidates.append(field_name)
    return candidates


def _normalize_vector_field_name(field_name):
    return re.sub(r'[\s_\-（）()\[\]{}【】.:：/\\]+', '', str(field_name or '')).lower()


def _extract_year_from_field_name(field_name):
    matches = re.findall(r'(19|20)\d{2}', str(field_name or ''))
    if not matches:
        return None
    try:
        return int(re.findall(r'(?:19|20)\d{2}', str(field_name or ''))[-1])
    except Exception:
        return None


def _list_shapefile_field_names(shp_path, encoding=None):
    if shapefile is None:
        logger.warning(f"无法读取Shapefile字段，依赖缺失: {SHAPEFILE_IMPORT_ERROR}")
        return []

    try:
        reader_kwargs = {}
        if encoding:
            reader_kwargs['encoding'] = encoding
        with shapefile.Reader(shp_path, **reader_kwargs) as reader:
            return [field[0] for field in reader.fields[1:] if field and field[0]]
    except Exception as exc:
        logger.warning(f"读取Shapefile字段失败: {exc}")
        return []


def _score_vector_field_name(field_name, aliases=None, keywords=None):
    normalized = _normalize_vector_field_name(field_name)
    aliases = aliases or []
    keywords = keywords or []
    score = 0

    for alias in aliases:
        alias_normalized = _normalize_vector_field_name(alias)
        if normalized == alias_normalized:
            score += 120
        elif alias_normalized and alias_normalized in normalized:
            score += 80

    for keyword in keywords:
        keyword_normalized = _normalize_vector_field_name(keyword)
        if keyword_normalized and keyword_normalized in normalized:
            score += 35

    year = _extract_year_from_field_name(field_name)
    if year:
        score += max(0, year - 2000)

    return score


def _detect_economy_style_field(shp_path, encoding=None):
    field_names = _list_shapefile_field_names(shp_path, encoding=encoding)
    if not field_names:
        return None, '经济指标'

    candidate_groups = [
        {
            'label': 'GDP',
            'aliases': [
                'GDP', 'gdp', 'gdp_total', 'gross_domestic_product',
                '地区生产总值', '生产总值', '经济总量'
            ],
            'keywords': ['gdp', '生产总值', '地区生产总值', '经济总量'],
        },
        {
            'label': '经济产值',
            'aliases': ['总产值', '产值', '工业总产值', '经济产值'],
            'keywords': ['产值', '总产值', '工业产值', '经济产值'],
        },
        {
            'label': '财政收入',
            'aliases': ['财政收入', '一般公共预算收入', 'revenue', 'income'],
            'keywords': ['财政', '收入', 'revenue', 'income'],
        },
        {
            'label': '人口',
            'aliases': ['POP', 'pop', 'population', '人口', '常住人口'],
            'keywords': ['pop', 'population', '人口'],
        },
    ]

    ranked_candidates = []
    for group in candidate_groups:
        for field_name in field_names:
            score = _score_vector_field_name(
                field_name,
                aliases=group['aliases'],
                keywords=group['keywords'],
            )
            if score > 0:
                ranked_candidates.append((score, field_name, group['label']))

    # 兜底：排除常见编码/名称/面积字段后，尝试其他数值字段
    excluded_keywords = ['name', '名称', 'code', '编码', 'area', '面积', 'layer', 'grade', '等级']
    for field_name in field_names:
        normalized = _normalize_vector_field_name(field_name)
        if any(_normalize_vector_field_name(keyword) in normalized for keyword in excluded_keywords):
            continue
        ranked_candidates.append((5 + (_extract_year_from_field_name(field_name) or 0) % 100, field_name, '经济指标'))

    ranked_candidates.sort(key=lambda item: (-item[0], item[1]))

    seen_fields = set()
    deduped_candidates = []
    for score, field_name, label in ranked_candidates:
        if field_name in seen_fields:
            continue
        seen_fields.add(field_name)
        deduped_candidates.append((score, field_name, label))

    return (deduped_candidates[0][1], deduped_candidates[0][2]) if deduped_candidates else (None, '经济指标')


def _rasterize_shapefile_with_rasterio(shp_path, output_tif, attribute_field, nodata_value=-9999):
    if shapefile is None:
        raise RuntimeError(f'Shapefile兼容栅格化依赖缺失: {SHAPEFILE_IMPORT_ERROR}')

    reader = shapefile.Reader(shp_path)
    fields = reader.fields[1:]
    field_names = [field[0] for field in fields]
    if attribute_field not in field_names:
        raise ValueError(f'属性字段不存在: {attribute_field}，可用字段: {", ".join(field_names)}')

    field_index = field_names.index(attribute_field)
    field_type = fields[field_index][1]
    if field_type not in ['N', 'F']:
        raise ValueError(f'属性字段 {attribute_field} 不是数值字段')

    shapes = reader.shapes()
    records = reader.records()
    if not shapes:
        raise ValueError('Shapefile中没有可用要素')

    bbox = reader.bbox
    min_x, min_y, max_x, max_y = bbox
    width = max_x - min_x
    height = max_y - min_y
    if width <= 0 or height <= 0:
        raise ValueError('Shapefile空间范围无效')

    target_size = 2500
    longest_side = max(width, height)
    pixel_size = longest_side / target_size if longest_side > 0 else 1.0
    if not np.isfinite(pixel_size) or pixel_size <= 0:
        pixel_size = 1.0

    x_res = max(1, int(np.ceil(width / pixel_size)))
    y_res = max(1, int(np.ceil(height / pixel_size)))
    transform = rasterio.transform.from_bounds(min_x, min_y, max_x, max_y, x_res, y_res)

    geometries = []
    for shp, record in zip(shapes, records):
        value = record[field_index]
        if value in [None, '']:
            continue
        try:
            burn_value = int(round(float(value)))
        except (TypeError, ValueError):
            continue
        if shp.shapeTypeName not in ['POLYGON', 'POLYGONZ', 'POLYGONM']:
            continue
        points = shp.points
        parts = list(shp.parts) + [len(points)]
        rings = [points[parts[i]:parts[i + 1]] for i in range(len(parts) - 1)]
        if not rings or len(rings[0]) < 3:
            continue
        shell = rings[0]
        holes = [ring for ring in rings[1:] if len(ring) >= 3]
        geometry = {
            'type': 'Polygon',
            'coordinates': [shell, *holes]
        }
        geometries.append((geometry, burn_value))

    if not geometries:
        raise ValueError('未找到可用于栅格化的面要素或数值属性')

    raster = rasterio.features.rasterize(
        geometries,
        out_shape=(y_res, x_res),
        fill=nodata_value,
        transform=transform,
        dtype=np.int32,
    )

    prj_path = os.path.splitext(shp_path)[0] + '.prj'
    crs = None
    if os.path.exists(prj_path):
        try:
            crs_text = Path(prj_path).read_text(encoding='utf-8', errors='ignore').strip()
            if crs_text:
                crs = rasterio.crs.CRS.from_wkt(crs_text)
        except Exception as exc:
            logger.warning(f'读取Shapefile投影失败，将继续写出无CRS栅格: {exc}')

    os.makedirs(os.path.dirname(output_tif), exist_ok=True)
    with rasterio.open(
        output_tif,
        'w',
        driver='GTiff',
        height=y_res,
        width=x_res,
        count=1,
        dtype=raster.dtype,
        transform=transform,
        crs=crs,
        nodata=nodata_value,
        compress='lzw',
    ) as dst:
        dst.write(raster, 1)


def _prepare_landuse_analysis_input(uploaded_file, requested_attr=None):
    upload_rel, upload_abs = _save_uploaded_file(uploaded_file, 'landuse_analysis')
    cleanup_files = [upload_abs]
    cleanup_dirs = []
    raster_input = upload_abs
    used_attr = None
    extension = os.path.splitext(uploaded_file.name.lower())[1]

    if extension == '.zip':
        extract_dir = os.path.join(os.path.dirname(upload_abs), f'{Path(upload_abs).stem}_extracted')
        shp_path = _extract_shapefile_zip(upload_abs, extract_dir)
        cleanup_dirs.append(extract_dir)

        raster_input = os.path.join(os.path.dirname(upload_abs), f'{Path(upload_abs).stem}_rasterized.tif')
        last_error = None
        rasterizer = rasterize_shapefile_to_tiff if rasterize_shapefile_to_tiff is not None else _rasterize_shapefile_with_rasterio
        for field_name in _landuse_attribute_candidates(requested_attr):
            try:
                rasterizer(shp_path, raster_input, attribute_field=field_name)
                used_attr = field_name
                cleanup_files.append(raster_input)
                break
            except Exception as exc:
                last_error = exc
        if used_attr is None:
            detail = f'；最近一次错误：{last_error}' if last_error else ''
            raise ValueError(
                'Shapefile 栅格化失败，未找到可用的土地利用分类字段。'
                f'请检查属性表是否包含 {", ".join(_landuse_attribute_candidates(requested_attr))}{detail}'
            )
    elif extension not in ['.tif', '.tiff']:
        raise ValueError('只支持 GeoTIFF(.tif/.tiff) 或包含完整 Shapefile 的 ZIP 压缩包')

    return {
        'upload_rel': upload_rel,
        'upload_abs': upload_abs,
        'raster_input': raster_input,
        'cleanup_files': cleanup_files,
        'cleanup_dirs': cleanup_dirs,
        'used_attr': used_attr,
    }


def _normalize_shapefile_dataset(source_shp_path, target_dir, fixed_name):
    source_dir = os.path.dirname(source_shp_path)
    source_stem = Path(source_shp_path).stem.lower()
    supported_extensions = {
        '.shp', '.shx', '.dbf', '.prj', '.cpg', '.sbn', '.sbx', '.qix', '.fix'
    }

    for file_name in os.listdir(source_dir):
        file_path = os.path.join(source_dir, file_name)
        if not os.path.isfile(file_path):
            continue
        file_ext = Path(file_name).suffix.lower()
        if file_ext not in supported_extensions:
            continue
        if Path(file_name).stem.lower() != source_stem:
            continue
        target_path = os.path.join(target_dir, f'{fixed_name}{file_ext}')
        if os.path.abspath(file_path) == os.path.abspath(target_path):
            continue
        if os.path.exists(target_path):
            os.remove(target_path)
        os.replace(file_path, target_path)

    normalized_shp = os.path.join(target_dir, f'{fixed_name}.shp')
    if not os.path.exists(normalized_shp):
        raise ValueError('Shapefile 组件整理失败，未生成标准 .shp 文件')

    cpg_path = os.path.join(target_dir, f'{fixed_name}.cpg')
    encoding = 'GBK'
    if os.path.exists(cpg_path):
        try:
            with open(cpg_path, 'r', encoding='utf-8', errors='ignore') as cpg_file:
                detected = cpg_file.read().strip()
            if detected:
                encoding = detected
        except Exception as exc:
            logger.warning(f"读取 {cpg_path} 编码失败，回退到 GBK: {exc}")
    else:
        with open(cpg_path, 'w', encoding='utf-8') as cpg_file:
            cpg_file.write(encoding)

    return normalized_shp, encoding


def _prepare_overlay_vector_dataset(uploaded_file, dataset_folder, fixed_name):
    upload_dir = os.path.join(settings.MEDIA_ROOT, 'ecological_projects', dataset_folder)
    if os.path.exists(upload_dir):
        remove_tree(upload_dir)
    os.makedirs(upload_dir, exist_ok=True)

    zip_path = os.path.join(upload_dir, f'{fixed_name}.zip')
    with open(zip_path, 'wb+') as destination:
        for chunk in uploaded_file.chunks():
            destination.write(chunk)

    is_valid_zip, zip_message = validate_shapefile_zip(zip_path)
    if not is_valid_zip:
        raise ValueError(zip_message)

    source_shp = _extract_shapefile_zip(zip_path, upload_dir)
    shp_path, encoding = _normalize_shapefile_dataset(source_shp, upload_dir, fixed_name)
    return {
        'upload_dir': upload_dir,
        'zip_path': zip_path,
        'shp_path': shp_path,
        'encoding': encoding,
    }


VECTOR_GEOMETRY_SUFFIXES = {
    'point': {'POINT', 'POINTZ', 'POINTM', 'MULTIPOINT', 'MULTIPOINTZ', 'MULTIPOINTM'},
    'line': {'POLYLINE', 'POLYLINEZ', 'POLYLINEM', 'LINESTRING', 'LINESTRINGZ', 'LINESTRINGM'},
    'polygon': {'POLYGON', 'POLYGONZ', 'POLYGONM'},
}


def _overlay_business_vector_config(group, geometry_suffix=None):
    if group not in {'economy', 'engineering'}:
        raise ValueError('矢量数据类型必须是 economy 或 engineering')

    if geometry_suffix:
        data_type = f'{group}_{geometry_suffix}'
        config = _get_overlay_layer_configs().get(data_type)
        if not config:
            raise ValueError(f'不支持的{group}矢量几何类型: {geometry_suffix}')
        return data_type, config['paths'][0].split(os.sep)[-1], config['layer_name'], config['label']

    config = _get_overlay_layer_configs().get(group)
    return group, config['paths'][0].split(os.sep)[-1], config['layer_name'], config['label']


def _detect_vector_geometry_suffix(shp_path):
    shape_type = ''
    if shapefile is not None:
        with shapefile.Reader(shp_path) as reader:
            shape_type = str(reader.shapeTypeName or '').upper()
        for suffix, shape_types in VECTOR_GEOMETRY_SUFFIXES.items():
            if shape_type in shape_types:
                return suffix

    # pyshp is optional in the GIS runtime. Use GDAL/OGR when it is absent so
    # a point or line dataset is never silently misclassified as a polygon.
    try:
        from osgeo import ogr

        datasource = ogr.Open(shp_path)
        if datasource is not None:
            layer = datasource.GetLayer(0)
            geometry_type = ogr.GT_Flatten(layer.GetGeomType()) if layer is not None else None
            ogr_types = {
                'point': {ogr.wkbPoint, ogr.wkbMultiPoint},
                'line': {ogr.wkbLineString, ogr.wkbMultiLineString},
                'polygon': {ogr.wkbPolygon, ogr.wkbMultiPolygon},
            }
            for suffix, geometry_types in ogr_types.items():
                if geometry_type in geometry_types:
                    return suffix
            shape_type = ogr.GeometryTypeToName(geometry_type) if geometry_type is not None else shape_type
    except Exception as exc:
        logger.warning(f'使用OGR识别矢量几何类型失败: {exc}')

    raise ValueError(f'当前ZIP内是{shape_type or "未知"}几何，当前仅支持点、线、面矢量数据')


def _find_complete_shapefiles(root_dir):
    required = {'.shp', '.shx', '.dbf'}
    candidates = {}
    for current_root, _, file_names in os.walk(root_dir):
        for file_name in file_names:
            ext = Path(file_name).suffix.lower()
            if ext not in required:
                continue
            stem = Path(file_name).stem.lower()
            candidates.setdefault((current_root, stem), set()).add(ext)

    shp_paths = []
    for (current_root, stem), extensions in candidates.items():
        if required.issubset(extensions):
            for file_name in os.listdir(current_root):
                if Path(file_name).stem.lower() == stem and Path(file_name).suffix.lower() == '.shp':
                    shp_paths.append(os.path.join(current_root, file_name))
                    break

    return shp_paths


def _extract_all_shapefiles_from_upload(uploaded_file, group):
    probe_dir = os.path.join(settings.MEDIA_ROOT, 'ecological_projects', f'{group}_upload_probe_{uuid.uuid4().hex}')
    os.makedirs(probe_dir, exist_ok=True)
    zip_path = os.path.join(probe_dir, get_valid_filename(uploaded_file.name) or f'{group}.zip')
    with open(zip_path, 'wb+') as destination:
        for chunk in uploaded_file.chunks():
            destination.write(chunk)

    is_valid_zip, zip_message = validate_shapefile_zip(zip_path)
    if not is_valid_zip:
        remove_tree(probe_dir)
        raise ValueError(zip_message)

    _extract_shapefile_zip(zip_path, probe_dir)
    shp_paths = _find_complete_shapefiles(probe_dir)
    if not shp_paths:
        remove_tree(probe_dir)
        raise ValueError('ZIP中未找到完整Shapefile组件，至少需要同名 .shp/.shx/.dbf')

    return probe_dir, zip_path, shp_paths


def _prepare_overlay_vector_layers_from_upload(uploaded_file, group):
    probe_dir, zip_path, source_shp_paths = _extract_all_shapefiles_from_upload(uploaded_file, group)
    selected_layers = []
    used_suffixes = set()
    try:
        for source_shp in source_shp_paths:
            geometry_suffix = _detect_vector_geometry_suffix(source_shp)
            if geometry_suffix in used_suffixes:
                logger.info(f"{uploaded_file.name} 中包含多个{geometry_suffix}图层，保留第一个并跳过: {source_shp}")
                continue
            used_suffixes.add(geometry_suffix)

            data_type, dataset_folder, layer_name, layer_label = _overlay_business_vector_config(group, geometry_suffix)
            selected_layers.append({
                'data_type': data_type,
                'dataset_folder': dataset_folder,
                'layer_name': layer_name,
                'layer_label': layer_label,
                'source_shp': source_shp,
                'geometry_suffix': geometry_suffix,
            })

        if not selected_layers:
            raise ValueError('ZIP中没有可用的点、线或面Shapefile')

        for layer_type in [group, *(f'{group}_{suffix}' for suffix in VECTOR_GEOMETRY_SUFFIXES.keys())]:
            config = _get_overlay_layer_configs().get(layer_type)
            if not config:
                continue
            for path in config.get('paths') or []:
                if os.path.isdir(path):
                    remove_tree(path)
                elif os.path.exists(path):
                    os.remove(path)

        prepared_layers = []
        for selected in selected_layers:
            data_type = selected['data_type']
            dataset_folder = selected['dataset_folder']
            layer_name = selected['layer_name']
            layer_label = selected['layer_label']
            source_shp = selected['source_shp']
            geometry_suffix = selected['geometry_suffix']
            final_dir = os.path.join(settings.MEDIA_ROOT, 'ecological_projects', dataset_folder)
            os.makedirs(final_dir, exist_ok=True)
            shutil.copyfile(zip_path, os.path.join(final_dir, f'{layer_name}.zip'))
            shp_path, encoding = _normalize_shapefile_dataset(source_shp, final_dir, layer_name)
            prepared_layers.append({
                'data_type': data_type,
                'dataset_folder': dataset_folder,
                'layer_name': layer_name,
                'layer_label': layer_label,
                'shp_path': shp_path,
                'encoding': encoding,
                'geometry_suffix': geometry_suffix,
            })
    finally:
        remove_tree(probe_dir)

    return prepared_layers


def _clear_overlay_business_vector_metadata(group):
    for layer_type in [group, *(f'{group}_{suffix}' for suffix in VECTOR_GEOMETRY_SUFFIXES.keys())]:
        if layer_type in _get_overlay_layer_configs():
            _clear_overlay_metadata(layer_type)


def _delete_overlay_business_vector_services(group):
    try:
        from .geoserver_config import geoserver_manager
    except Exception as exc:
        logger.warning(f"清理{group}历史GeoServer服务失败: {exc}")
        return

    for layer_type in [group, *(f'{group}_{suffix}' for suffix in VECTOR_GEOMETRY_SUFFIXES.keys())]:
        config = _get_overlay_layer_configs().get(layer_type)
        if not config or config.get('kind') != 'vector':
            continue
        try:
            geoserver_manager.delete_datastore(config['store'], recurse=True)
        except Exception as exc:
            logger.warning(f"删除{config['label']}GeoServer服务失败: {exc}")


def _publish_overlay_business_vector_layer(layer_info, group):
    publish_success = False
    style_field_name = None
    style_field_label = '经济指标'
    try:
        from .geoserver_config import geoserver_manager

        publish_success = geoserver_manager.publish_shapefile(
            layer_name=layer_info['layer_name'],
            shapefile_path=layer_info['shp_path'],
            charset=layer_info['encoding']
        )

        if publish_success:
            if group == 'economy':
                try:
                    style_field_name, style_field_label = _detect_economy_style_field(
                        layer_info['shp_path'],
                        encoding=layer_info['encoding']
                    )
                    if style_field_name:
                        min_val, max_val, mean_val = geoserver_manager._get_vector_statistics(layer_info['shp_path'], style_field_name)
                    else:
                        min_val, max_val, mean_val = (None, None, None)
                    if style_field_name and min_val is not None and max_val is not None:
                        sld_content = geoserver_manager._create_vector_sld_by_attribute(
                            field_name=style_field_name,
                            min_val=min_val,
                            max_val=max_val,
                            color_scheme='default'
                        )
                        try:
                            geoserver_manager.delete_style(layer_info['layer_name'])
                        except Exception:
                            pass
                        if geoserver_manager.create_style(layer_info['layer_name'], sld_content):
                            geoserver_manager.apply_style_to_layer(layer_info['layer_name'], layer_info['layer_name'])
                    else:
                        logger.warning(f"{layer_info['layer_label']}无法识别可用经济分级字段，使用默认样式")
                except Exception as exc:
                    logger.warning(f"生成经济矢量样式失败: {exc}，使用默认样式")
            else:
                try:
                    color_map = {
                        'point': ('#1677ff', 0.85),
                        'line': ('#00a3a3', 0.7),
                        'polygon': ('#2A5BFF', 0.45),
                    }
                    color, opacity = color_map.get(layer_info.get('geometry_suffix'), ('#1677ff', 0.6))
                    sld_content = geoserver_manager._create_vector_sld_simple(color=color, opacity=opacity)
                    try:
                        geoserver_manager.delete_style(layer_info['layer_name'])
                    except Exception:
                        pass
                    if geoserver_manager.create_style(layer_info['layer_name'], sld_content):
                        geoserver_manager.apply_style_to_layer(layer_info['layer_name'], layer_info['layer_name'])
                except Exception as exc:
                    logger.warning(f"生成工程矢量样式失败: {exc}，使用默认样式")
    except Exception as exc:
        logger.error(f"发布{layer_info['layer_label']}到GeoServer时出错: {exc}")
        import traceback
        logger.error(traceback.format_exc())

    return publish_success, style_field_name, style_field_label


def _overlay_business_vector_upload_response(uploaded_file, description, group):
    prepared_layers = _prepare_overlay_vector_layers_from_upload(uploaded_file, group)
    _delete_overlay_business_vector_services(group)
    _clear_overlay_business_vector_metadata(group)
    results = []
    for layer_info in prepared_layers:
        publish_success, style_field_name, style_field_label = _publish_overlay_business_vector_layer(layer_info, group)
        metadata = _update_overlay_metadata(
            layer_info['data_type'],
            description=description,
            file_name=uploaded_file.name,
            layer_name=layer_info['layer_name'],
            source_type='uploaded_vector',
            service_mode='geoserver' if publish_success else 'local',
            geoserver_published=publish_success,
        )
        results.append({
            'data_type': layer_info['data_type'],
            'geometry_type': layer_info['geometry_suffix'],
            'label': layer_info['layer_label'],
            'layer_name': layer_info['layer_name'],
            'shp_path': layer_info['shp_path'],
            'geoserver_published': publish_success,
            'style_field_name': style_field_name,
            'style_field_label': style_field_label,
            'metadata': metadata,
        })

    published_count = sum(1 for item in results if item['geoserver_published'])
    labels = '、'.join(item['label'] for item in results)
    group_label = '经济数据矢量' if group == 'economy' else '工程项目矢量'
    all_published = published_count == len(results)
    return Response({
        'success': True,
        'message': f'{group_label}上传成功，已识别并处理：{labels}' + ('' if all_published else '；部分图层使用本地GeoJSON显示'),
        'file_name': uploaded_file.name,
        'description': description,
        'data_type': group,
        'results': results,
        'metadata': results[0]['metadata'] if results else {},
    })


def _engineering_upload_config(data_type):
    data_type, dataset_folder, layer_name, layer_label = _overlay_business_vector_config(
        'engineering',
        data_type.replace('engineering_', '') if data_type.startswith('engineering_') else None
    )
    return dataset_folder, layer_name, layer_label


def _get_engineering_geometry_layer_type(shp_path):
    return f"engineering_{_detect_vector_geometry_suffix(shp_path)}"


def _validate_engineering_geometry(shp_path, data_type):
    """Prevent a point/polygon upload from being saved to the wrong layer slot."""
    if data_type == 'engineering' or shapefile is None:
        return

    geometry_layer_type = _get_engineering_geometry_layer_type(shp_path)
    if geometry_layer_type != data_type:
        expected_label = '点' if data_type == 'engineering_point' else '面'
        actual_label = '点' if geometry_layer_type == 'engineering_point' else '面'
        raise ValueError(f'当前ZIP内是工程{actual_label}数据，不能作为工程{expected_label}数据上传')


def _landuse_structure_payload(analyzer):
    results = {
        'fragmentation': analyzer.calculate_fragmentation_index() or {'error': '破碎度指数计算失败'},
        'cohesion': analyzer.calculate_cohesion_index() or {'error': '内聚力指数计算失败'},
        'diversity': analyzer.calculate_diversity_index() or {'error': '多样性指数计算失败'},
        'fragility': analyzer.calculate_fragility_index() or {'error': '脆弱度指数计算失败'},
    }
    summary = {
        'fragmentation_index': results.get('fragmentation', {}).get('overall_fragmentation', 0),
        'cohesion_index': results.get('cohesion', {}).get('cohesion_index', 0),
        'shannon_diversity': results.get('diversity', {}).get('shannon_diversity', 0),
        'fragility_index': results.get('fragility', {}).get('fragility_index', 0),
    }
    return results, summary


def _landuse_stress_payload(analyzer):
    results = {
        'soil_erosion': analyzer.calculate_soil_erosion_index() or {'error': '土壤侵蚀指数计算失败'},
        'unused_land': analyzer.calculate_unused_land_ratio() or {'error': '未利用地面积比例计算失败'},
        'cultivated_construction': analyzer.calculate_development_ratio() or {'error': '耕地建设用地面积比例计算失败'},
        'land_degradation': analyzer.calculate_land_degradation_index() or {'error': '土地退化指数计算失败'},
    }
    summary = {
        'soil_erosion_index': results.get('soil_erosion', {}).get('soil_erosion_index', 0),
        'unused_land_proportion': results.get('unused_land', {}).get('unused_land_ratio', 0),
        'cultivated_construction_proportion': results.get('cultivated_construction', {}).get('development_ratio', 0),
        'land_degradation_index': results.get('land_degradation', {}).get('land_degradation_index', 0),
    }
    return results, summary


def _landuse_analysis_meta(analyzer_cls):
    is_gdal_engine = analyzer_cls is LandUseAnalyzer
    return {
        'analysis_engine': 'gdal' if is_gdal_engine else 'rasterio_fallback',
        'analysis_engine_label': 'GDAL精确计算' if is_gdal_engine else 'Rasterio兼容计算',
        'analysis_precision': 'adaptive_resolution' if is_gdal_engine else 'mixed_resolution',
        'analysis_notes': (
            [
                '系统会根据数据大小自动选择计算分辨率，超大数据采用最近邻重采样以保证可完成计算。',
                '面积统计会使用对应的像元面积修正；破碎度和内聚力为交互分析结果，正式成果建议以原始分辨率复核。'
            ]
            if is_gdal_engine else
            [
                '当前环境未启用GDAL，系统已自动切换为兼容计算模式。',
                '面积占比、脆弱度、土壤侵蚀、开发比例、退化指数基于全量像元统计。',
                '破碎度和内聚力在兼容模式下基于降采样预览估算，适合快速研判，正式成果建议在GDAL环境复核。'
            ]
        )
    }


def _run_landuse_index_analysis(request, uploaded_file, analysis_type):
    prepared = None
    analyzer = None
    try:
        prepared = _prepare_landuse_analysis_input(
            uploaded_file,
            requested_attr=request.data.get('landuse_attr'),
        )
        analyzer_cls = LandUseAnalyzer if LandUseAnalyzer is not None else RasterioLandUseAnalyzer
        analyzer = analyzer_cls(prepared['raster_input'])
        analysis_meta = _landuse_analysis_meta(analyzer_cls)

        if not analyzer.load_landuse_data():
            return Response({'error': '土地利用数据加载失败'}, status=400)

        if analysis_type == 'structure':
            results, summary = _landuse_structure_payload(analyzer)
            message = '生态环境结构指数计算完成'
        else:
            results, summary = _landuse_stress_payload(analyzer)
            message = '生态环境胁迫指数计算完成'

        visualization = _landuse_visualization_payload(
            request,
            analyzer,
            uploaded_file.name,
            raster_abs=prepared.get('raster_input'),
        )
        return Response({
            'message': message,
            'results': results,
            'visualization': visualization,
            'summary': summary,
            'meta': analysis_meta,
        })
    except ValueError as exc:
        return Response({'error': str(exc)}, status=400)
    except RuntimeError as exc:
        status_code = 503 if 'gdal' in str(exc).lower() or 'osgeo' in str(exc).lower() else 500
        return Response({'error': str(exc)}, status=status_code)
    except Exception as exc:
        logger.exception(f'计算土地利用指数失败: {analysis_type}')
        return Response({'error': f'计算失败: {exc}'}, status=500)
    finally:
        if analyzer is not None:
            analyzer.close()
        if prepared:
            _cleanup_temp_paths(prepared.get('cleanup_files'), prepared.get('cleanup_dirs'))


def _media_url(request, relative_path):
    if not relative_path:
        return None
    return settings.MEDIA_URL + relative_path.replace('\\', '/')


def _statistics_payload(stats):
    return {
        'min_value': stats.get('min_value') if stats else None,
        'max_value': stats.get('max_value') if stats else None,
        'mean_value': stats.get('mean_value') if stats else None,
        'std_value': stats.get('std_value') if stats else None,
        'excellent_area': stats.get('excellent_area') if stats else None,
        'good_area': stats.get('good_area') if stats else None,
        'moderate_area': stats.get('moderate_area') if stats else None,
        'poor_area': stats.get('poor_area') if stats else None,
        'bad_area': stats.get('bad_area') if stats else None,
    }


def _single_band_statistics(path):
    return preview_array(path), raster_band_statistics(path)


def _remote_preview_thresholds():
    max_preview_pixels = getattr(settings, 'REMOTE_ANALYSIS_PREVIEW_MAX_PIXELS', 16000000)
    max_preview_side = getattr(settings, 'REMOTE_ANALYSIS_PREVIEW_MAX_SIDE', 2500)
    return int(max_preview_pixels), int(max_preview_side)


def _should_use_remote_preview(dataset):
    max_pixels, max_side = _remote_preview_thresholds()
    total_pixels = int(dataset.width) * int(dataset.height)
    max_dimension = max(int(dataset.width), int(dataset.height))
    min_dimension = min(int(dataset.width), int(dataset.height))

    # 避免把 Landsat 这类长边略大、但总体像元量仍可控的影像误判成超大图。
    return total_pixels > max_pixels or (max_dimension > max_side and min_dimension > max_side)


def _remote_preview_scale(width, height):
    _, max_side = _remote_preview_thresholds()
    return max(1, int(np.ceil(max(width, height) / max_side)))


def _preview_multiband_index(raster_path, index_type):
    def read_scaled_band(dataset, band_index, out_height, out_width):
        raw_data = dataset.read(
            band_index,
            out_shape=(out_height, out_width),
            resampling=rasterio.enums.Resampling.bilinear,
        )
        band_data = raw_data.astype('float32')
        nodata_value = dataset.nodata
        if nodata_value is not None:
            band_data[raw_data == nodata_value] = np.nan
        scale_value, offset_value = get_band_scale_offset(dataset, band_index - 1, band_count=int(dataset.count))
        return band_data * np.float32(scale_value) + np.float32(offset_value)

    with rasterio.open(raster_path) as dataset:
        band_count = int(dataset.count)
        mapping = infer_standard_band_mapping(dataset=dataset, band_count=band_count)
        scale = _remote_preview_scale(dataset.width, dataset.height)
        out_height = max(1, dataset.height // scale)
        out_width = max(1, dataset.width // scale)

        if index_type == 'ndbi':
            if mapping.get('swir1') is not None and mapping.get('nir') is not None:
                swir_band = read_scaled_band(dataset, mapping['swir1'] + 1, out_height, out_width)
                nir_band = read_scaled_band(dataset, mapping['nir'] + 1, out_height, out_width)
            elif band_count == 3:
                swir_band = read_scaled_band(dataset, 3, out_height, out_width)
                nir_band = read_scaled_band(dataset, 1, out_height, out_width)
            else:
                raise ValueError(f'当前波段配置不支持 {index_type.upper()} 预览计算')
            denominator = swir_band + nir_band
            index_data = np.full_like(swir_band, np.nan, dtype=np.float32)
            valid_mask = denominator != 0
            index_data[valid_mask] = (swir_band[valid_mask] - nir_band[valid_mask]) / denominator[valid_mask]
        else:
            if index_type == 'ndvi':
                if mapping.get('nir') is not None and mapping.get('red') is not None:
                    numerator_band, denominator_band = mapping['nir'] + 1, mapping['red'] + 1
                elif band_count == 3:
                    numerator_band, denominator_band = 2, 1
                else:
                    raise ValueError(f'当前波段配置不支持 {index_type.upper()} 预览计算')
            else:
                if mapping.get('green') is not None and mapping.get('nir') is not None:
                    numerator_band, denominator_band = mapping['green'] + 1, mapping['nir'] + 1
                elif band_count == 3:
                    numerator_band, denominator_band = 2, 1
                else:
                    raise ValueError(f'当前波段配置不支持 {index_type.upper()} 预览计算')
            numerator = read_scaled_band(dataset, numerator_band, out_height, out_width)
            denominator_band_data = read_scaled_band(dataset, denominator_band, out_height, out_width)
            base = numerator + denominator_band_data
            index_data = np.full_like(numerator, np.nan, dtype=np.float32)
            valid_mask = base != 0
            index_data[valid_mask] = (numerator[valid_mask] - denominator_band_data[valid_mask]) / base[valid_mask]

        return np.clip(index_data, -1.0, 1.0)


def _infer_remote_sensing_metadata(raster_path):
    center_lat = 0.0
    center_lon = 0.0
    resolution = None
    bands_count = None

    with rasterio.open(raster_path) as dataset:
        bands_count = int(dataset.count)
        if dataset.res:
            try:
                resolution = float(abs(dataset.res[0]))
            except Exception:
                resolution = None

        if dataset.crs:
            try:
                bounds = dataset.bounds
                if dataset.crs.to_string() == 'EPSG:4326':
                    left, bottom, right, top = bounds.left, bounds.bottom, bounds.right, bounds.top
                else:
                    left, bottom, right, top = transform_bounds(
                        dataset.crs,
                        'EPSG:4326',
                        bounds.left,
                        bounds.bottom,
                        bounds.right,
                        bounds.top,
                        densify_pts=21
                    )
                center_lon = float((left + right) / 2)
                center_lat = float((bottom + top) / 2)
            except Exception as exc:
                logger.warning(f'推断遥感影像中心点失败，使用默认坐标: {exc}')

    return {
        'center_lat': center_lat,
        'center_lon': center_lon,
        'resolution': resolution,
        'bands_count': bands_count,
    }


def _build_remote_analysis_payload(
    request,
    index_type,
    label,
    stats,
    result_file_rel=None,
    result_file_abs=None,
    visualization_rel=None,
    extra=None,
):
    compare_overlay = _build_compare_overlay_payload(
        request=request,
        raster_abs=result_file_abs,
        result_file_rel=result_file_rel,
        visualization_rel=visualization_rel,
        source_filename=Path(result_file_rel).name if result_file_rel else None,
        style_hint=index_type,
    )
    payload = {
        'id': uuid.uuid4().hex,
        'index_type': index_type,
        'index_type_display': label,
        **_statistics_payload(stats),
        'result_file_url': _media_url(request, result_file_rel) if result_file_rel else None,
        'visualization_file_url': _media_url(request, visualization_rel) if visualization_rel else None,
        'compare_overlay': compare_overlay,
    }
    if extra:
        payload.update(extra)
    return payload


def _persist_rsei_analysis_result(request, uploaded_file_name, raster_abs, calculator, result_items, pca_meta):
    user = request.user if request.user.is_authenticated else None
    image_id = uuid.uuid4()
    safe_name = get_valid_filename(Path(uploaded_file_name).stem or 'rsei_image')
    source_suffix = Path(raster_abs).suffix.lower() or '.tif'
    source_filename = f'{image_id}_{safe_name}{source_suffix}'
    source_rel = os.path.join('remote_sensing', source_filename).replace('\\', '/')
    source_abs = os.path.join(settings.MEDIA_ROOT, source_rel)

    result_dir_rel = os.path.join('ecological_indices', str(image_id)).replace('\\', '/')
    result_dir_abs = os.path.join(settings.MEDIA_ROOT, result_dir_rel)
    created_paths = []
    created_image = None
    created_indices = {}

    try:
        os.makedirs(os.path.dirname(source_abs), exist_ok=True)
        os.makedirs(result_dir_abs, exist_ok=True)

        shutil.copy2(raster_abs, source_abs)
        created_paths.append(source_abs)

        metadata = _infer_remote_sensing_metadata(source_abs)
        created_image = RemoteSensingImage.objects.create(
            id=image_id,
            name=safe_name,
            description='通过遥感生态指数分析页面生成的 RSEI 结果源影像',
            image_type='custom',
            file_path=source_rel,
            center_lat=metadata['center_lat'],
            center_lon=metadata['center_lon'],
            acquisition_date=timezone.now().date(),
            resolution=metadata['resolution'],
            bands_count=metadata['bands_count'],
            file_size=os.path.getsize(source_abs),
            is_processed=True,
            processing_status='completed',
            uploaded_by=user,
        )

        for item in result_items:
            index_type = item['index_type']
            label = item['label']
            index_data = item['data']
            stats = item['stats']

            result_file_rel = f'{result_dir_rel}/{index_type}_result.tif'
            visualization_file_rel = f'{result_dir_rel}/{index_type}_visualization.png'
            result_file_abs = os.path.join(settings.MEDIA_ROOT, result_file_rel)
            visualization_file_abs = os.path.join(settings.MEDIA_ROOT, visualization_file_rel)

            if not calculator.save_result(index_data, result_file_abs):
                raise ValueError(f'保存 {index_type} 结果栅格失败')
            created_paths.append(result_file_abs)

            if not calculator.create_visualization(index_data, label, visualization_file_abs):
                raise ValueError(f'生成 {index_type} 可视化失败')
            created_paths.append(visualization_file_abs)

            created_indices[index_type] = EcologicalIndex.objects.create(
                remote_sensing_image=created_image,
                index_type=index_type,
                result_file=result_file_rel,
                visualization_file=visualization_file_rel,
                min_value=stats.get('min_value'),
                max_value=stats.get('max_value'),
                mean_value=stats.get('mean_value'),
                std_value=stats.get('std_value'),
                excellent_area=stats.get('excellent_area'),
                good_area=stats.get('good_area'),
                moderate_area=stats.get('moderate_area'),
                poor_area=stats.get('poor_area'),
                bad_area=stats.get('bad_area'),
                created_by=user,
            )

        RSEIResult.objects.create(
            remote_sensing_image=created_image,
            greenness=created_indices['greenness'],
            wetness=created_indices['wetness'],
            dryness=created_indices['dryness'],
            heat=created_indices['heat'],
            rsei_result=created_indices['rsei'],
            pc1_variance=pca_meta.get('pc1_variance', 0.0),
            pc2_variance=pca_meta.get('pc2_variance', 0.0),
            pc3_variance=pca_meta.get('pc3_variance', 0.0),
            pc4_variance=pca_meta.get('pc4_variance', 0.0),
            greenness_weight=pca_meta.get('greenness_weight', 0.0),
            wetness_weight=pca_meta.get('wetness_weight', 0.0),
            dryness_weight=pca_meta.get('dryness_weight', 0.0),
            heat_weight=pca_meta.get('heat_weight', 0.0),
        )

        return created_image, created_indices
    except Exception:
        if created_image:
            try:
                created_image.delete()
            except Exception as exc:
                logger.warning(f'回滚遥感影像记录失败: {exc}')

        for path in reversed(created_paths):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception as exc:
                logger.warning(f'回滚持久化文件失败: {path}, {exc}')

        raise


def _safe_layer_name(name):
    base = re.sub(r'[^0-9A-Za-z_]+', '_', name or '').strip('_').lower()
    if not base:
        base = 'business_layer'
    if base[0].isdigit():
        base = f'layer_{base}'
    return f'{base}_{uuid.uuid4().hex[:8]}'


def _build_ogc_urls(geoserver, layer_name, layer_type):
    qualified_layer = f'{geoserver.workspace}:{layer_name}'
    base_ows = f'{geoserver.base_url}/ows'
    urls = {
        'wms_url': (
            f'{base_ows}?service=WMS&version=1.3.0&request=GetMap'
            f'&layers={qualified_layer}&format=image/png&transparent=true'
        )
    }
    if layer_type == 'vector':
        urls['wfs_url'] = (
            f'{base_ows}?service=WFS&version=2.0.0&request=GetFeature'
            f'&typeNames={qualified_layer}&outputFormat=application/json'
        )
        urls['wcs_url'] = None
    else:
        urls['wfs_url'] = None
        urls['wcs_url'] = (
            f'{base_ows}?service=WCS&version=2.0.1&request=GetCoverage'
            f'&coverageId={qualified_layer}'
        )
    return urls


def _raster_layer_metadata(path):
    """读取栅格基础元数据，供前端定位和服务说明使用。"""
    metadata = {}
    try:
        with rasterio.open(path) as dataset:
            bounds = dataset.bounds
            rgb_bands = _infer_raster_rgb_bands(dataset)
            metadata.update({
                'bounds': [bounds.left, bounds.bottom, bounds.right, bounds.top],
                'crs': dataset.crs.to_string() if dataset.crs else None,
                'width': dataset.width,
                'height': dataset.height,
                'band_count': dataset.count,
                'dtype': dataset.dtypes[0] if dataset.dtypes else None,
                'band_descriptions': [desc for desc in (dataset.descriptions or ()) if desc],
                'colorinterp': [str(item) for item in getattr(dataset, 'colorinterp', ())],
                'rgb_bands': rgb_bands,
            })
    except Exception as exc:
        logger.warning(f"读取栅格元数据失败: {exc}")
        try:
            from osgeo import gdal, osr

            dataset = gdal.Open(path, gdal.GA_ReadOnly)
            if dataset is None:
                return metadata

            geotransform = dataset.GetGeoTransform(can_return_null=True)
            projection = dataset.GetProjection()
            band_count = int(dataset.RasterCount or 0)
            width = int(dataset.RasterXSize or 0)
            height = int(dataset.RasterYSize or 0)

            crs = None
            if projection:
                spatial_ref = osr.SpatialReference()
                spatial_ref.ImportFromWkt(projection)
                auth_name = spatial_ref.GetAuthorityName(None)
                auth_code = spatial_ref.GetAuthorityCode(None)
                if auth_name and auth_code:
                    crs = f'{auth_name}:{auth_code}'
                else:
                    crs = projection

            bounds = None
            if geotransform and width > 0 and height > 0:
                origin_x, pixel_width, _, origin_y, _, pixel_height = geotransform
                min_x = origin_x
                max_x = origin_x + pixel_width * width
                max_y = origin_y
                min_y = origin_y + pixel_height * height
                bounds = [min(min_x, max_x), min(min_y, max_y), max(min_x, max_x), max(min_y, max_y)]

            metadata.update({
                'bounds': bounds,
                'crs': crs or 'EPSG:4326',
                'width': width,
                'height': height,
                'band_count': band_count,
                'dtype': gdal.GetDataTypeName(dataset.GetRasterBand(1).DataType) if band_count > 0 else None,
            })
        except Exception as gdal_exc:
            logger.warning(f"使用GDAL读取栅格元数据也失败: {gdal_exc}")
    return metadata


def _build_compare_overlay_payload(
    request,
    raster_abs=None,
    result_file_rel=None,
    visualization_rel=None,
    source_filename=None,
    style_hint=None,
    class_color_map=None,
    infer_background_value=False,
):
    """构建前端结果叠加展示所需的标准空间信息。"""
    if not raster_abs or not os.path.exists(raster_abs):
        return None

    metadata = _raster_layer_metadata(raster_abs)
    bounds = metadata.get('bounds')
    crs = metadata.get('crs') or 'EPSG:4326'
    if not bounds or len(bounds) != 4:
        return None

    bounds_3857 = None
    try:
        if crs == 'EPSG:3857':
            bounds_3857 = bounds
        else:
            transformed = transform_bounds(crs, 'EPSG:3857', *bounds, densify_pts=21)
            bounds_3857 = [transformed[0], transformed[1], transformed[2], transformed[3]]
    except Exception as exc:
        logger.warning(f"转换结果叠加范围到 EPSG:3857 失败: {exc}")

    overlay_image_rel = None
    overlay_image_url = None
    base_rel = result_file_rel or visualization_rel
    if base_rel:
        overlay_image_rel = str(Path(base_rel).with_name(f'{Path(base_rel).stem}_overlay.png')).replace('\\', '/')
        overlay_image_abs = os.path.join(settings.MEDIA_ROOT, overlay_image_rel)
        if _generate_compare_overlay_png(
            raster_abs=raster_abs,
            output_abs=overlay_image_abs,
            style_hint=style_hint,
            class_color_map=class_color_map,
            infer_background_value=infer_background_value,
        ):
            overlay_image_url = _media_url(request, overlay_image_rel)

    return {
        'source_filename': source_filename,
        'crs': crs,
        'bounds': bounds,
        'bounds_3857': bounds_3857,
        'width': metadata.get('width'),
        'height': metadata.get('height'),
        'band_count': metadata.get('band_count'),
        'result_file_url': _media_url(request, result_file_rel) if result_file_rel else None,
        'visualization_file_url': _media_url(request, visualization_rel) if visualization_rel else None,
        'overlay_image_url': overlay_image_url,
    }


def _continuous_overlay_colormap(style_hint=None):
    return mpl_colors.LinearSegmentedColormap.from_list(
        'analysis_result_overlay',
        ['#8B0000', '#FF0000', '#FFA500', '#FFFF00', '#00FF00', '#006400'],
        N=256,
    )


def _trim_uploaded_raster_background(data, valid_mask):
    """尝试识别直接上传栅格四角一致的背景填充值，并将其透明化。"""
    try:
        if data.ndim != 2 or not np.any(valid_mask):
            return valid_mask

        height, width = data.shape
        window = max(1, min(12, height // 20 or 1, width // 20 or 1))
        corner_windows = [
            data[:window, :window],
            data[:window, width - window:width],
            data[height - window:height, :window],
            data[height - window:height, width - window:width],
        ]

        corner_values = []
        for block in corner_windows:
            values = block[np.isfinite(block)]
            if values.size:
                corner_values.append(np.round(values, 6))

        if not corner_values:
            return valid_mask

        merged = np.concatenate(corner_values)
        unique_values, counts = np.unique(merged, return_counts=True)
        if unique_values.size == 0:
            return valid_mask

        dominant_index = int(np.argmax(counts))
        dominant_value = float(unique_values[dominant_index])
        dominant_count = int(counts[dominant_index])
        if dominant_count < max(8, int(merged.size * 0.65)):
            return valid_mask

        tolerance = max(1e-6, abs(dominant_value) * 1e-6)
        corner_hits = 0
        for block in corner_windows:
            values = block[np.isfinite(block)]
            if values.size and np.mean(np.isclose(values, dominant_value, atol=tolerance)) >= 0.75:
                corner_hits += 1

        if corner_hits < 3:
            return valid_mask

        dominant_mask = valid_mask & np.isclose(data, dominant_value, atol=tolerance)
        dominant_ratio = float(np.count_nonzero(dominant_mask)) / float(np.count_nonzero(valid_mask))
        if dominant_ratio < 0.12:
            return valid_mask

        trimmed_mask = valid_mask & (~dominant_mask)
        return trimmed_mask if np.any(trimmed_mask) else valid_mask
    except Exception as exc:
        logger.warning(f"识别上传栅格背景值失败，跳过透明化优化: {exc}")
        return valid_mask


def _rgba_from_compare_overlay_data(data, valid_mask, class_color_map=None, style_hint=None):
    rgba = np.zeros((data.shape[0], data.shape[1], 4), dtype=np.uint8)
    is_categorical = bool(class_color_map)

    if is_categorical:
        rounded = np.rint(data).astype(np.int32, copy=False)
        for class_id, color in class_color_map.items():
            try:
                rgba_color = mpl_colors.to_rgba(color, alpha=0.78)
            except Exception:
                rgba_color = mpl_colors.to_rgba('#999999', alpha=0.78)
            class_mask = valid_mask & (rounded == int(class_id))
            if not np.any(class_mask):
                continue
            rgba[class_mask] = (np.array(rgba_color) * 255).astype(np.uint8)
    else:
        valid_values = data[valid_mask]
        vmin = float(np.nanpercentile(valid_values, 2))
        vmax = float(np.nanpercentile(valid_values, 98))
        if not np.isfinite(vmin) or not np.isfinite(vmax) or abs(vmax - vmin) < 1e-12:
            vmin = float(np.nanmin(valid_values))
            vmax = float(np.nanmax(valid_values))
        if abs(vmax - vmin) < 1e-12:
            vmax = vmin + 1e-6
        normalized = np.clip((data - vmin) / (vmax - vmin), 0, 1)
        cmap = _continuous_overlay_colormap(style_hint)
        rgba = (cmap(normalized) * 255).astype(np.uint8)
        rgba[..., 3] = np.where(valid_mask, 255, 0).astype(np.uint8)

    rgba[~valid_mask] = (0, 0, 0, 0)
    return rgba


def _generate_compare_overlay_png_with_gdal(
    raster_abs,
    output_abs,
    style_hint=None,
    class_color_map=None,
    max_dimension=1600,
    infer_background_value=False,
):
    try:
        from osgeo import gdal
    except Exception as import_exc:
        logger.warning(f"GDAL导入失败，无法执行叠加图回退生成: {import_exc}")
        return False

    try:
        dataset = gdal.Open(raster_abs, gdal.GA_ReadOnly)
        if dataset is None:
            return False

        width = int(dataset.RasterXSize or 0)
        height = int(dataset.RasterYSize or 0)
        if width <= 0 or height <= 0 or int(dataset.RasterCount or 0) <= 0:
            return False

        scale = min(1.0, max_dimension / max(width, height))
        out_width = max(1, int(round(width * scale)))
        out_height = max(1, int(round(height * scale)))

        band = dataset.GetRasterBand(1)
        is_categorical = bool(class_color_map)
        resample_alg = gdal.GRA_NearestNeighbour if is_categorical else gdal.GRA_Bilinear
        band_data = band.ReadAsArray(
            buf_xsize=out_width,
            buf_ysize=out_height,
            resample_alg=resample_alg,
        )
        if band_data is None:
            return False

        data = band_data.astype(np.float32, copy=False)
        valid_mask = np.isfinite(data)
        nodata_value = band.GetNoDataValue()
        if nodata_value is not None and np.isfinite(nodata_value):
            valid_mask &= data != np.float32(nodata_value)

        if infer_background_value:
            valid_mask = _trim_uploaded_raster_background(data, valid_mask)

        if not np.any(valid_mask):
            return False

        rgba = _rgba_from_compare_overlay_data(
            data=data,
            valid_mask=valid_mask,
            class_color_map=class_color_map,
            style_hint=style_hint,
        )
        Image.fromarray(rgba, mode='RGBA').save(output_abs)
        return True
    except Exception as exc:
        logger.warning(f"使用GDAL回退生成透明结果叠加图失败: {exc}")
        return False


def _generate_compare_overlay_png(
    raster_abs,
    output_abs,
    style_hint=None,
    class_color_map=None,
    max_dimension=1600,
    infer_background_value=False,
):
    """生成适合地图叠加的透明PNG，不包含白底、标题、坐标轴和图例。"""
    if not raster_abs or not os.path.exists(raster_abs):
        return False

    try:
        os.makedirs(os.path.dirname(output_abs), exist_ok=True)
        with rasterio.open(raster_abs) as dataset:
            width = int(dataset.width or 0)
            height = int(dataset.height or 0)
            if width <= 0 or height <= 0:
                return False

            scale = min(1.0, max_dimension / max(width, height))
            out_width = max(1, int(round(width * scale)))
            out_height = max(1, int(round(height * scale)))

            is_categorical = bool(class_color_map)
            resampling = Resampling.nearest if is_categorical else Resampling.bilinear
            band = dataset.read(
                1,
                masked=True,
                out_shape=(out_height, out_width),
                resampling=resampling,
            )

        mask = np.ma.getmaskarray(band)
        data = np.ma.filled(band, np.nan).astype(np.float32)
        valid_mask = np.isfinite(data) & (~mask)
        if infer_background_value:
            valid_mask = _trim_uploaded_raster_background(data, valid_mask)
        if not np.any(valid_mask):
            return False

        rgba = _rgba_from_compare_overlay_data(
            data=data,
            valid_mask=valid_mask,
            class_color_map=class_color_map,
            style_hint=style_hint,
        )
        Image.fromarray(rgba, mode='RGBA').save(output_abs)
        return True
    except Exception as exc:
        logger.warning(f"生成透明结果叠加图失败，将尝试GDAL回退: {exc}")
        return _generate_compare_overlay_png_with_gdal(
            raster_abs=raster_abs,
            output_abs=output_abs,
            style_hint=style_hint,
            class_color_map=class_color_map,
            max_dimension=max_dimension,
            infer_background_value=infer_background_value,
        )


def _infer_raster_rgb_bands(dataset):
    """尽量推断栅格影像的 RGB 波段顺序。"""
    band_count = int(getattr(dataset, 'count', 0) or 0)
    if band_count < 3:
        return None
    rgb_mapping = infer_rgb_bands(dataset=dataset)
    if rgb_mapping:
        return rgb_mapping
    return {'red_band': 3, 'green_band': 2, 'blue_band': 1}


def _vector_layer_metadata(path):
    """读取矢量基础元数据，供前端定位和服务说明使用。"""
    metadata = {}
    try:
        from osgeo import ogr
        datasource = ogr.Open(path)
        if datasource is None:
            return metadata

        layer = datasource.GetLayer(0)
        extent = layer.GetExtent()
        spatial_ref = layer.GetSpatialRef()
        crs = None
        if spatial_ref:
            auth_name = spatial_ref.GetAuthorityName(None)
            auth_code = spatial_ref.GetAuthorityCode(None)
            if auth_name and auth_code:
                crs = f'{auth_name}:{auth_code}'
            else:
                crs = spatial_ref.ExportToWkt()

        if extent:
            min_x, max_x, min_y, max_y = extent
            metadata['bounds'] = [min_x, min_y, max_x, max_y]
        metadata['crs'] = crs or 'EPSG:4326'
        metadata['feature_count'] = layer.GetFeatureCount()
        datasource = None
    except Exception as exc:
        logger.warning(f"读取矢量元数据失败: {exc}")
    return metadata


def _extract_shapefile_zip(zip_path, target_dir):
    os.makedirs(target_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        for member in zip_ref.infolist():
            normalized = member.filename.replace('\\', '/')
            if normalized.startswith('/') or '..' in normalized.split('/'):
                raise ValueError('ZIP文件中包含不安全路径')
        zip_ref.extractall(target_dir)

    shp_files = []
    for root, _, files in os.walk(target_dir):
        for file_name in files:
            if file_name.lower().endswith('.shp'):
                shp_files.append(os.path.join(root, file_name))
    if not shp_files:
        raise ValueError('ZIP文件中未找到.shp文件')
    return shp_files[0]


def _json_safe_property(value):
    if value is None:
        return None
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    if isinstance(value, bytes):
        for encoding in ('utf-8', 'gbk', 'gb18030'):
            try:
                return value.decode(encoding)
            except Exception:
                continue
        return value.decode('utf-8', errors='ignore')
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    return value


def _shapefile_to_geojson_with_ogr(shp_path):
    from osgeo import ogr, osr

    datasource = ogr.Open(shp_path)
    if datasource is None:
        raise ValueError('Shapefile 无法读取，请检查 ZIP 内文件是否完整')

    layer = datasource.GetLayer(0)
    if layer is None:
        raise ValueError('Shapefile 中没有可读取图层')

    source_srs = layer.GetSpatialRef()
    target_srs = osr.SpatialReference()
    target_srs.ImportFromEPSG(4326)
    coordinate_transform = None
    if source_srs and not source_srs.IsSame(target_srs):
        coordinate_transform = osr.CoordinateTransformation(source_srs, target_srs)

    layer_defn = layer.GetLayerDefn()
    field_names = [
        layer_defn.GetFieldDefn(index).GetName()
        for index in range(layer_defn.GetFieldCount())
    ]

    features = []
    for feature in layer:
        geometry = feature.GetGeometryRef()
        if geometry is None:
            continue
        geometry_clone = geometry.Clone()
        if coordinate_transform:
            geometry_clone.Transform(coordinate_transform)
        try:
            geometry_json = json.loads(geometry_clone.ExportToJson())
        finally:
            geometry_clone = None
        properties = {
            field_name: _json_safe_property(feature.GetField(field_name))
            for field_name in field_names
        }
        features.append({
            'type': 'Feature',
            'geometry': geometry_json,
            'properties': properties,
        })

    datasource = None
    return {
        'type': 'FeatureCollection',
        'features': features,
    }


def _shapefile_to_geojson_with_pyshp(shp_path):
    if shapefile is None:
        raise RuntimeError(f'当前环境缺少 Shapefile 解析依赖: {SHAPEFILE_IMPORT_ERROR}')

    last_error = None
    for encoding in ('utf-8', 'gbk', 'gb18030'):
        try:
            with shapefile.Reader(shp_path, encoding=encoding) as reader:
                field_names = [field[0] for field in reader.fields[1:] if field and field[0]]
                features = []
                for shape_record in reader.iterShapeRecords():
                    geometry = getattr(shape_record.shape, '__geo_interface__', None)
                    if not geometry:
                        continue
                    properties = {
                        field_name: _json_safe_property(value)
                        for field_name, value in zip(field_names, shape_record.record)
                    }
                    features.append({
                        'type': 'Feature',
                        'geometry': geometry,
                        'properties': properties,
                    })
                return {
                    'type': 'FeatureCollection',
                    'features': features,
                }
        except Exception as exc:
            last_error = exc

    raise ValueError(f'Shapefile 属性编码或几何读取失败: {last_error}')


def _shapefile_to_geojson(shp_path):
    try:
        return _shapefile_to_geojson_with_ogr(shp_path)
    except Exception as exc:
        logger.warning(f'OGR 转换 Shapefile 失败，尝试 pyshp 兜底: {exc}')
        return _shapefile_to_geojson_with_pyshp(shp_path)


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def parse_local_vector_layer(request):
    """解析本地 Shapefile ZIP，用于主地图临时图层预览。"""
    if 'file' not in request.FILES:
        return Response({'error': '请上传 Shapefile ZIP 文件'}, status=400)

    uploaded_file = request.FILES['file']
    if not uploaded_file.name.lower().endswith('.zip'):
        return Response({'error': '当前接口仅支持完整 Shapefile ZIP'}, status=400)

    upload_rel, upload_abs = _save_uploaded_file(uploaded_file, 'analysis_tmp')
    extract_dir = os.path.join(settings.MEDIA_ROOT, 'analysis_tmp', f'vector_{uuid.uuid4().hex}')
    try:
        is_valid_zip, zip_message = validate_shapefile_zip(upload_abs)
        if not is_valid_zip:
            return Response({'error': zip_message}, status=400)

        shp_path = _extract_shapefile_zip(upload_abs, extract_dir)
        geojson = _shapefile_to_geojson(shp_path)
        feature_count = len(geojson.get('features') or [])
        if feature_count == 0:
            return Response({'error': 'Shapefile ZIP 中未解析到有效要素'}, status=400)

        return Response({
            'success': True,
            'filename': uploaded_file.name,
            'feature_count': feature_count,
            'geojson': geojson,
        })
    except Exception as exc:
        logger.exception('解析本地Shapefile ZIP失败')
        return Response({'error': f'Shapefile ZIP 解析失败: {exc}'}, status=400)
    finally:
        try:
            if os.path.exists(upload_abs):
                os.remove(upload_abs)
        except Exception as cleanup_error:
            logger.warning(f'清理本地矢量上传文件失败: {cleanup_error}')
        remove_tree(extract_dir)


def _convert_kml_to_shapefile(kml_path, target_dir, output_name):
    os.makedirs(target_dir, exist_ok=True)
    try:
        from osgeo import ogr
    except ImportError as exc:
        raise RuntimeError('当前环境缺少 GDAL/OGR，无法将 KML 转换为 Shapefile') from exc

    data_source = ogr.Open(kml_path)
    if data_source is None:
        raise ValueError('KML 文件无法读取，请检查文件内容是否完整')

    source_layer = None
    for index in range(data_source.GetLayerCount()):
        candidate = data_source.GetLayerByIndex(index)
        if candidate and candidate.GetFeatureCount() > 0:
            source_layer = candidate
            break
    if source_layer is None:
        source_layer = data_source.GetLayer(0)
    if source_layer is None:
        raise ValueError('KML 文件中未找到可转换的图层')

    shapefile_path = os.path.join(target_dir, f'{output_name}.shp')
    driver = ogr.GetDriverByName('ESRI Shapefile')
    if os.path.exists(shapefile_path):
        driver.DeleteDataSource(shapefile_path)

    target_ds = driver.CreateDataSource(shapefile_path)
    if target_ds is None:
        raise RuntimeError('创建 Shapefile 失败')

    source_srs = source_layer.GetSpatialRef()
    geometry_type = source_layer.GetGeomType()
    target_layer = target_ds.CreateLayer(output_name, srs=source_srs, geom_type=geometry_type)
    layer_defn = source_layer.GetLayerDefn()

    for field_index in range(layer_defn.GetFieldCount()):
        field_defn = layer_defn.GetFieldDefn(field_index)
        target_layer.CreateField(field_defn)

    target_defn = target_layer.GetLayerDefn()
    source_layer.ResetReading()
    for feature in source_layer:
        target_feature = ogr.Feature(target_defn)
        target_feature.SetFrom(feature)
        geometry = feature.GetGeometryRef()
        if geometry is not None:
            target_feature.SetGeometry(geometry.Clone())
        if target_layer.CreateFeature(target_feature) != 0:
            raise RuntimeError('KML 转换写入 Shapefile 失败')
        target_feature = None

    data_source = None
    target_ds = None

    cpg_path = os.path.splitext(shapefile_path)[0] + '.cpg'
    with open(cpg_path, 'w', encoding='utf-8') as cpg_file:
        cpg_file.write('UTF-8')

    return shapefile_path


def _update_url_query(url, **params):
    parsed = urlsplit(url)
    query = {key: value for key, value in parse_qsl(parsed.query, keep_blank_values=True)}
    for key, value in params.items():
        if value is None:
            query.pop(key, None)
        else:
            query[key] = value
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def _is_placeholder_service_url(url):
    try:
        host = (urlsplit(url).hostname or '').lower()
    except Exception:
        return False
    placeholder_hosts = {'example.com', 'example.org', 'example.net'}
    return host in placeholder_hosts or any(host.endswith(f'.{item}') for item in placeholder_hosts)


def _service_health_payload(status_value='unknown', message=None):
    return {
        'service_health_status': status_value,
        'service_health_message': message,
        'service_checked_at': timezone.now(),
    }


def _hex_to_rgb(color):
    color = (color or '').strip().lstrip('#')
    if len(color) != 6:
        raise ValueError('颜色值必须是 6 位十六进制')
    return tuple(int(color[index:index + 2], 16) for index in (0, 2, 4))


def _interpolate_color(start_color, end_color, factor):
    start_rgb = _hex_to_rgb(start_color)
    end_rgb = _hex_to_rgb(end_color)
    rgb = tuple(round(start_rgb[index] + (end_rgb[index] - start_rgb[index]) * factor) for index in range(3))
    return f'#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}'


def _log_business_layer_action(layer, action, status_value='info', message=None, operator=None, details=None):
    operator_name = None
    if operator and getattr(operator, 'is_authenticated', False):
        operator_name = operator.username
    elif layer.uploaded_by:
        operator_name = layer.uploaded_by.username

    return BusinessLayerAuditLog.objects.create(
        business_layer=layer,
        action=action,
        status=status_value,
        operator=operator if operator and getattr(operator, 'is_authenticated', False) else None,
        operator_name=operator_name,
        message=message,
        details=details or {},
    )


def _vector_style_sld(layer_name, style_config):
    fill_color = style_config.get('fill_color') or '#1f8f4d'
    stroke_color = style_config.get('stroke_color') or fill_color
    stroke_width = style_config.get('stroke_width', 2)
    fill_opacity = style_config.get('fill_opacity', 0.18)
    classification_field = (style_config.get('classification_field') or '').strip()
    color_scheme = style_config.get('color_scheme') or 'green_yellow_red'
    geometry_type = (style_config.get('geometry_type') or 'polygon').lower()

    if classification_field and style_config.get('min_value') is not None and style_config.get('max_value') is not None:
        min_val = float(style_config['min_value'])
        max_val = float(style_config['max_value'])
        if max_val <= min_val:
            max_val = min_val + 1
        threshold1 = min_val + (max_val - min_val) * 0.33
        threshold2 = min_val + (max_val - min_val) * 0.67
        schemes = {
            'green_yellow_red': ('#2E8B57', '#F6C344', '#D64545'),
            'blue_cyan_green': ('#315f8c', '#4fb7c5', '#1f8f4d'),
            'purple_pink_red': ('#7c5cc4', '#d17ab4', '#d64545'),
        }
        low_color, mid_color, high_color = schemes.get(color_scheme, schemes['green_yellow_red'])
        symbolizer = f'''
          <Rule>
            <Name>low</Name>
            <ogc:Filter>
              <ogc:PropertyIsLessThan>
                <ogc:PropertyName>{classification_field}</ogc:PropertyName>
                <ogc:Literal>{threshold1:.6f}</ogc:Literal>
              </ogc:PropertyIsLessThan>
            </ogc:Filter>
            <PolygonSymbolizer>
              <Fill><CssParameter name="fill">{low_color}</CssParameter><CssParameter name="fill-opacity">{fill_opacity}</CssParameter></Fill>
              <Stroke><CssParameter name="stroke">{stroke_color}</CssParameter><CssParameter name="stroke-width">{stroke_width}</CssParameter></Stroke>
            </PolygonSymbolizer>
          </Rule>
          <Rule>
            <Name>medium</Name>
            <ogc:Filter>
              <ogc:And>
                <ogc:PropertyIsGreaterThanOrEqualTo>
                  <ogc:PropertyName>{classification_field}</ogc:PropertyName>
                  <ogc:Literal>{threshold1:.6f}</ogc:Literal>
                </ogc:PropertyIsGreaterThanOrEqualTo>
                <ogc:PropertyIsLessThan>
                  <ogc:PropertyName>{classification_field}</ogc:PropertyName>
                  <ogc:Literal>{threshold2:.6f}</ogc:Literal>
                </ogc:PropertyIsLessThan>
              </ogc:And>
            </ogc:Filter>
            <PolygonSymbolizer>
              <Fill><CssParameter name="fill">{mid_color}</CssParameter><CssParameter name="fill-opacity">{fill_opacity}</CssParameter></Fill>
              <Stroke><CssParameter name="stroke">{stroke_color}</CssParameter><CssParameter name="stroke-width">{stroke_width}</CssParameter></Stroke>
            </PolygonSymbolizer>
          </Rule>
          <Rule>
            <Name>high</Name>
            <ogc:Filter>
              <ogc:PropertyIsGreaterThanOrEqualTo>
                <ogc:PropertyName>{classification_field}</ogc:PropertyName>
                <ogc:Literal>{threshold2:.6f}</ogc:Literal>
              </ogc:PropertyIsGreaterThanOrEqualTo>
            </ogc:Filter>
            <PolygonSymbolizer>
              <Fill><CssParameter name="fill">{high_color}</CssParameter><CssParameter name="fill-opacity">{fill_opacity}</CssParameter></Fill>
              <Stroke><CssParameter name="stroke">{stroke_color}</CssParameter><CssParameter name="stroke-width">{stroke_width}</CssParameter></Stroke>
            </PolygonSymbolizer>
          </Rule>'''
    elif geometry_type == 'point':
        symbolizer = f'''
          <Rule>
            <PointSymbolizer>
              <Graphic>
                <Mark>
                  <WellKnownName>circle</WellKnownName>
                  <Fill><CssParameter name="fill">{fill_color}</CssParameter></Fill>
                  <Stroke><CssParameter name="stroke">{stroke_color}</CssParameter><CssParameter name="stroke-width">{stroke_width}</CssParameter></Stroke>
                </Mark>
                <Size>10</Size>
              </Graphic>
            </PointSymbolizer>
          </Rule>'''
    elif geometry_type == 'line':
        symbolizer = f'''
          <Rule>
            <LineSymbolizer>
              <Stroke>
                <CssParameter name="stroke">{stroke_color}</CssParameter>
                <CssParameter name="stroke-width">{stroke_width}</CssParameter>
              </Stroke>
            </LineSymbolizer>
          </Rule>'''
    else:
        symbolizer = f'''
          <Rule>
            <PolygonSymbolizer>
              <Fill><CssParameter name="fill">{fill_color}</CssParameter><CssParameter name="fill-opacity">{fill_opacity}</CssParameter></Fill>
              <Stroke><CssParameter name="stroke">{stroke_color}</CssParameter><CssParameter name="stroke-width">{stroke_width}</CssParameter></Stroke>
            </PolygonSymbolizer>
          </Rule>'''

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor version="1.0.0"
  xmlns="http://www.opengis.net/sld"
  xmlns:ogc="http://www.opengis.net/ogc"
  xmlns:xlink="http://www.w3.org/1999/xlink"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.opengis.net/sld http://schemas.opengis.net/sld/1.0.0/StyledLayerDescriptor.xsd">
  <NamedLayer>
    <Name>{layer_name}</Name>
    <UserStyle>
      <Title>{layer_name} vector style</Title>
      <FeatureTypeStyle>{symbolizer}
      </FeatureTypeStyle>
    </UserStyle>
  </NamedLayer>
</StyledLayerDescriptor>'''


def _raster_style_sld(layer_name, style_config):
    opacity = style_config.get('raster_opacity', 0.72)
    band_count = int(style_config.get('band_count') or 1)
    if band_count >= 3:
        red_band = int(style_config.get('red_band') or 1)
        green_band = int(style_config.get('green_band') or 2)
        blue_band = int(style_config.get('blue_band') or 3)
        return f'''<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor version="1.0.0"
  xmlns="http://www.opengis.net/sld"
  xmlns:xlink="http://www.w3.org/1999/xlink"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.opengis.net/sld http://schemas.opengis.net/sld/1.0.0/StyledLayerDescriptor.xsd">
  <NamedLayer>
    <Name>{layer_name}</Name>
    <UserStyle>
      <Title>{layer_name} raster RGB style</Title>
      <FeatureTypeStyle>
        <Rule>
          <RasterSymbolizer>
            <Opacity>{opacity}</Opacity>
            <ChannelSelection>
              <RedChannel>
                <SourceChannelName>{red_band}</SourceChannelName>
              </RedChannel>
              <GreenChannel>
                <SourceChannelName>{green_band}</SourceChannelName>
              </GreenChannel>
              <BlueChannel>
                <SourceChannelName>{blue_band}</SourceChannelName>
              </BlueChannel>
            </ChannelSelection>
          </RasterSymbolizer>
        </Rule>
      </FeatureTypeStyle>
    </UserStyle>
  </NamedLayer>
</StyledLayerDescriptor>'''

    min_value = float(style_config.get('min_value', 0))
    max_value = float(style_config.get('max_value', 100))
    if max_value <= min_value:
        max_value = min_value + 1
    ramp = style_config.get('raster_color_ramp') or 'green_yellow_red'
    ramps = {
        'green_yellow_red': ('#2E8B57', '#F6C344', '#D64545'),
        'blue_cyan_green': ('#315f8c', '#4fb7c5', '#1f8f4d'),
        'gray_blue': ('#6b7280', '#93c5fd', '#1d4ed8'),
    }
    start_color, mid_color, end_color = ramps.get(ramp, ramps['green_yellow_red'])
    q1 = min_value + (max_value - min_value) * 0.5
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor version="1.0.0"
  xmlns="http://www.opengis.net/sld"
  xmlns:xlink="http://www.w3.org/1999/xlink"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.opengis.net/sld http://schemas.opengis.net/sld/1.0.0/StyledLayerDescriptor.xsd">
  <NamedLayer>
    <Name>{layer_name}</Name>
    <UserStyle>
      <Title>{layer_name} raster style</Title>
      <FeatureTypeStyle>
        <Rule>
          <RasterSymbolizer>
            <Opacity>{opacity}</Opacity>
            <ColorMap type="ramp">
              <ColorMapEntry color="{start_color}" quantity="{min_value:.6f}" opacity="{opacity}" />
              <ColorMapEntry color="{mid_color}" quantity="{q1:.6f}" opacity="{opacity}" />
              <ColorMapEntry color="{end_color}" quantity="{max_value:.6f}" opacity="{opacity}" />
            </ColorMap>
          </RasterSymbolizer>
        </Rule>
      </FeatureTypeStyle>
    </UserStyle>
  </NamedLayer>
</StyledLayerDescriptor>'''


def _check_layer_service_availability(layer):
    timeout = 20
    metadata = layer.metadata or {}
    geoserver_auth = None

    if any(_is_placeholder_service_url(url) for url in [layer.wms_url, layer.wfs_url, layer.wcs_url, getattr(layer, 'service_url', None)] if url):
        return _service_health_payload('unknown', '示例地址未配置真实服务，暂不执行连通性检测')

    if layer.geoserver_workspace and not metadata.get('is_external_service'):
        from .geoserver_config import get_geoserver_manager
        geoserver_auth = get_geoserver_manager().auth

    try:
        if layer.layer_type == 'vector' and layer.wfs_url:
            type_name = layer.service_type_name or layer.geoserver_layer_name
            if layer.geoserver_workspace and type_name and ':' not in type_name and not metadata.get('is_external_service'):
                type_name = f'{layer.geoserver_workspace}:{type_name}'
            probe_url = _update_url_query(
                layer.wfs_url,
                service='WFS',
                request='GetFeature',
                version='2.0.0',
                typeNames=type_name,
                outputFormat='application/json',
                count='1'
            )
            response = requests.get(probe_url, timeout=timeout, auth=geoserver_auth)
            if response.ok:
                return _service_health_payload('healthy', 'WFS 服务可访问')
            return _service_health_payload('unhealthy', f'WFS 检测失败: HTTP {response.status_code}')

        if layer.wms_url:
            bounds = metadata.get('bounds') or [-180, -90, 180, 90]
            crs = layer.service_srs or metadata.get('crs') or 'EPSG:4326'
            layers = layer.service_type_name or layer.geoserver_layer_name
            if layer.geoserver_workspace and layers and ':' not in layers and not metadata.get('is_external_service'):
                layers = f'{layer.geoserver_workspace}:{layers}'
            wms_query = dict(parse_qsl(urlsplit(layer.wms_url).query, keep_blank_values=True))
            service_version = wms_query.get('version') or wms_query.get('VERSION') or '1.3.0'
            crs_param = 'crs' if service_version == '1.3.0' else 'srs'
            probe_url = _update_url_query(
                layer.wms_url,
                service='WMS',
                request='GetMap',
                version=service_version,
                layers=layers,
                bbox=','.join(str(value) for value in bounds),
                width='32',
                height='32',
                srs=crs if crs_param == 'srs' else None,
                crs=crs if crs_param == 'crs' else None,
                format='image/png',
                transparent='true'
            )
            response = requests.get(probe_url, timeout=timeout, auth=geoserver_auth)
            if response.ok and 'image/' in (response.headers.get('Content-Type') or ''):
                return _service_health_payload('healthy', 'WMS 服务可访问')
            return _service_health_payload('unhealthy', f'WMS 检测失败: HTTP {response.status_code}')

        if layer.wcs_url:
            coverage_id = layer.service_type_name or layer.geoserver_layer_name
            if layer.geoserver_workspace and coverage_id and ':' not in coverage_id and not metadata.get('is_external_service'):
                coverage_id = f'{layer.geoserver_workspace}:{coverage_id}'
            probe_url = _update_url_query(
                layer.wcs_url,
                service='WCS',
                request='DescribeCoverage',
                version='2.0.1',
                coverageId=coverage_id
            )
            response = requests.get(probe_url, timeout=timeout, auth=geoserver_auth)
            if response.ok:
                return _service_health_payload('healthy', 'WCS 服务可访问')
            return _service_health_payload('unhealthy', f'WCS 检测失败: HTTP {response.status_code}')
    except requests.RequestException as exc:
        return _service_health_payload('unhealthy', f'服务检测异常: {exc}')
    except Exception as exc:
        return _service_health_payload('unhealthy', f'服务检测失败: {exc}')

    return _service_health_payload('unknown', '当前图层没有可检测的标准服务地址')


@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def geoserver_ows_proxy(request):
    """代理GeoServer OWS服务，避免浏览器直接访问GeoServer时被CORS拦截。"""
    from .geoserver_config import get_geoserver_manager

    geoserver = get_geoserver_manager()
    logger.info(f"GeoServer OWS proxy request: params={dict(request.GET)}")

    def is_getmap_image_request():
        request_type = str(request.GET.get('REQUEST') or request.GET.get('request') or '').lower()
        output_format = str(request.GET.get('FORMAT') or request.GET.get('format') or '').lower()
        return request_type == 'getmap' and ('png' in output_format or not output_format)

    def transparent_map_response(reason, upstream_status=200):
        logger.warning("GeoServer GetMap fallback transparent image: %s", reason)
        response = HttpResponse(TRANSPARENT_PNG_BYTES, status=200, content_type='image/png')
        response['Cache-Control'] = 'no-store'
        response['X-GeoServer-Fallback'] = 'transparent'
        response['X-GeoServer-Upstream-Status'] = str(upstream_status)
        response['Access-Control-Allow-Origin'] = '*'
        return response

    try:
        upstream = requests.get(
            f'{geoserver.base_url}/ows',
            params=request.GET,
            auth=geoserver.auth,
            timeout=120,
        )
    except requests.RequestException as exc:
        if is_getmap_image_request():
            return transparent_map_response(str(exc), 502)
        return Response({'error': f'GeoServer代理请求失败: {exc}'}, status=502)

    if upstream.status_code >= 400:
        logger.warning(
            "GeoServer OWS proxy upstream error: status=%s content_type=%s body=%s",
            upstream.status_code,
            upstream.headers.get('Content-Type'),
            upstream.text[:500],
        )
        if is_getmap_image_request():
            return transparent_map_response(upstream.text[:300], upstream.status_code)

    content_type = upstream.headers.get('Content-Type', 'application/octet-stream')
    response = HttpResponse(
        upstream.content,
        status=upstream.status_code,
        content_type=content_type,
    )
    for header in ['Cache-Control', 'Expires', 'ETag', 'Last-Modified']:
        if upstream.headers.get(header):
            response[header] = upstream.headers[header]
    response['Access-Control-Allow-Origin'] = '*'
    return response


def _landuse_visualization_payload(request, analyzer, source_file_name, raster_abs=None):
    result_dir_rel = f'landuse_results/{uuid.uuid4().hex}'
    result_dir_abs = os.path.join(settings.MEDIA_ROOT, result_dir_rel)
    os.makedirs(result_dir_abs, exist_ok=True)
    visualization_rel = f'{result_dir_rel}/land_use_visualization.png'
    visualization_abs = os.path.join(settings.MEDIA_ROOT, visualization_rel)
    result_file_rel = None
    if raster_abs and os.path.exists(raster_abs):
        result_file_rel = f'{result_dir_rel}/land_use_result.tif'
        result_file_abs = os.path.join(settings.MEDIA_ROOT, result_file_rel)
        try:
            shutil.copy2(raster_abs, result_file_abs)
        except Exception as exc:
            logger.warning(f"复制土地利用结果TIF失败: {exc}")
            result_file_rel = None
    analyzer.create_landuse_visualization(visualization_abs)
    return {
        'source_filename': source_file_name,
        'visualization_file_url': _media_url(request, visualization_rel),
        'result_file_url': _media_url(request, result_file_rel) if result_file_rel else None,
        'landuse_statistics': analyzer.get_landuse_statistics(),
        'compare_overlay': _build_compare_overlay_payload(
            request=request,
            raster_abs=raster_abs,
            result_file_rel=result_file_rel,
            visualization_rel=visualization_rel,
            source_filename=source_file_name,
            style_hint='landuse',
            class_color_map={
                int(class_id): class_info.get('color', '#999999')
                for class_id, class_info in getattr(analyzer, 'landuse_classes', {}).items()
            } or None,
        ),
    }


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def analyze_remote_sensing_upload(request):
    """上传遥感/成果栅格并直接计算或统计展示，不要求先入库。"""
    if 'file' not in request.FILES:
        return Response({'error': '请上传 GeoTIFF 或常见影像文件'}, status=400)

    index_type = str(request.data.get('index_type') or 'ndvi').lower()
    if index_type == 'lst':
        index_type = 'heat'
    if index_type == 'ndbsi':
        index_type = 'dryness'

    uploaded_file = request.FILES['file']
    extension = os.path.splitext(uploaded_file.name.lower())[1]
    if extension == '.adf':
        return Response({
            'error': 'ADF 是 ArcGIS 栅格目录格式，不能作为单文件上传。请上传包含完整ADF文件夹的ZIP，或先转为GeoTIFF(.tif)。'
        }, status=400)
    if extension not in ['.tif', '.tiff', '.jpg', '.jpeg', '.png', '.zip']:
        return Response({'error': '仅支持 .tif/.tiff/.jpg/.jpeg/.png 或 ADF文件夹ZIP'}, status=400)

    upload_rel, upload_abs = _save_uploaded_file(uploaded_file, 'analysis_tmp')
    result_dir_rel = f'analysis_results/{uuid.uuid4().hex}'
    result_dir_abs = os.path.join(settings.MEDIA_ROOT, result_dir_rel)
    os.makedirs(result_dir_abs, exist_ok=True)

    calculator = None
    cleanup_dirs = []
    try:
        raster_abs = upload_abs
        preview_mode = False
        preview_message = None
        if extension == '.zip':
            raster_abs, cleanup_dirs = prepare_raster_upload(upload_abs, result_dir_abs)
            extension = '.tif'

        if extension in ['.tif', '.tiff']:
            with rasterio.open(raster_abs) as probe_dataset:
                band_count = int(probe_dataset.count)
                probe_mapping = infer_standard_band_mapping(dataset=probe_dataset, band_count=band_count)
                preview_mode = _should_use_remote_preview(probe_dataset)
                supported_indices = _supported_remote_indices(
                    band_count=band_count,
                    dataset=probe_dataset,
                    band_mapping=probe_mapping,
                )
        else:
            band_count = None
            probe_mapping = None
            supported_indices = _supported_remote_indices(band_count=band_count, band_mapping=probe_mapping)
        results = []
        if index_type not in supported_indices and band_count != 1:
            return _unsupported_remote_index_response(index_type, band_count, probe_mapping)
        if preview_mode and band_count and band_count > 1 and index_type not in ['ndvi', 'ndwi', 'ndbi']:
            return Response({
                'error': '当前影像尺寸过大，已为稳定性限制为预览模式。超大影像暂仅支持 NDVI、NDWI、NDBI 预览分析；如需计算热度、干度、湿度、绿度或 RSEI，请先裁剪研究区域后再上传。',
                'bands_count': band_count,
                'requested_index': index_type,
                'supported_indices': ['ndvi', 'ndwi', 'ndbi'],
                'supported_index_labels': [REMOTE_INDEX_LABELS[item] for item in ['ndvi', 'ndwi', 'ndbi']],
            }, status=400)

        if band_count == 1 and extension in ['.tif', '.tiff']:
            label = '上传成果栅格'
            index_data, stats = _single_band_statistics(raster_abs)
            index_result_type = 'uploaded_raster'
            result_tif_rel = f'{result_dir_rel}/{index_result_type}.tif'
            result_tif_abs = os.path.join(settings.MEDIA_ROOT, result_tif_rel)
            shutil.copy2(raster_abs, result_tif_abs)
            if index_type == 'rsei':
                preview_message = (
                    '当前上传的是单波段成果栅格，系统已生成预览和缓存；'
                    '但它不能反推标准 RSEI，也不会作为可同步到叠加分析的 RSEI 计算成果。'
                )
        elif extension in ['.tif', '.tiff'] and index_type in ['ndvi', 'ndwi'] and band_count and band_count >= 3 and not preview_mode:
            index_result_type = index_type
            label = REMOTE_INDEX_METHODS[index_type][0]
            result_tif_rel = f'{result_dir_rel}/{index_result_type}.tif'
            result_tif_abs = os.path.join(settings.MEDIA_ROOT, result_tif_rel)
            _, stats = calculate_normalized_index_windowed(raster_abs, result_tif_abs, index_type)
            index_data = preview_array(result_tif_abs)
            result_file_url = _media_url(request, result_tif_rel)
        elif extension in ['.tif', '.tiff'] and preview_mode and index_type in ['ndvi', 'ndwi', 'ndbi'] and band_count and band_count >= 3:
            index_result_type = index_type
            label = REMOTE_INDEX_METHODS[index_type][0]
            index_data = _preview_multiband_index(raster_abs, index_type)
            stats = EcologicalIndexCalculator(raster_abs).calculate_statistics(index_data)
            result_file_url = None
            preview_message = '检测到超大影像，已自动切换为预览级分析，保证上传与显示稳定。'
        else:
            calculator = EcologicalIndexCalculator(raster_abs)
            if not calculator.load_image():
                return Response({'error': '影像加载失败，请检查文件格式、波段数或坐标信息'}, status=400)
            band_count = int(calculator.bands.shape[0])
            active_mapping = calculator._get_sensor_band_mapping()
            if index_type == 'rsei':
                rsei_result = calculator.calculate_rsei()
                if not rsei_result:
                    return _unsupported_remote_index_response(index_type, band_count, active_mapping, calculator.dataset)
                index_data = rsei_result['rsei']
                stats = calculator.calculate_statistics(index_data)
                label = 'RSEI'
                index_result_type = 'rsei'
            else:
                method_info = REMOTE_INDEX_METHODS.get(index_type)
                if not method_info:
                    return Response({
                        'error': f'不支持的指数类型: {index_type}',
                        'supported_indices': sorted([*REMOTE_INDEX_METHODS.keys(), 'rsei'])
                }, status=400)
                label, method_name = method_info
                index_data = getattr(calculator, method_name)()
                if index_data is None:
                    return _unsupported_remote_index_response(index_type, band_count, active_mapping, calculator.dataset)
                stats = calculator.calculate_statistics(index_data)
                index_result_type = index_type
            if preview_mode:
                preview_message = '检测到超大影像，本次返回预览级结果；如需完整精度结果，建议裁剪区域后再分析。'
                result_file_url = None

        if not stats:
            return Response({'error': '统计结果生成失败'}, status=500)

        result_file_url = locals().get('result_file_url')
        persisted_remote_sensing_image_id = None
        persisted_remote_sensing_image_name = None
        if index_result_type == 'rsei' and calculator and not preview_mode:
            component_definitions = [
                ('greenness', '绿度指数', rsei_result['greenness']),
                ('wetness', '湿度指数(Tasseled Cap)', rsei_result['wetness']),
                ('dryness', '干度指数(NDBSI)', rsei_result['dryness']),
                ('heat', '热度指数(LST/Heat)', rsei_result['heat']),
                ('rsei', 'RSEI', rsei_result['rsei']),
            ]

            result_items = []
            for component_type, component_label, component_data in component_definitions:
                component_stats = calculator.calculate_statistics(component_data)
                if not component_stats:
                    return Response({'error': f'{component_label}统计结果生成失败'}, status=500)
                result_items.append({
                    'index_type': component_type,
                    'label': component_label,
                    'data': component_data,
                    'stats': component_stats,
                })

            pca_variance = rsei_result.get('pca_variance')
            variance_list = list(pca_variance) if pca_variance is not None else []
            component_matrix = rsei_result.get('pca_components')
            first_component = component_matrix[0] if component_matrix is not None and len(component_matrix) > 0 else [0, 0, 0, 0]
            pca_meta = {
                'pc1_variance': float(variance_list[0]) if len(variance_list) > 0 else 0.0,
                'pc2_variance': float(variance_list[1]) if len(variance_list) > 1 else 0.0,
                'pc3_variance': float(variance_list[2]) if len(variance_list) > 2 else 0.0,
                'pc4_variance': float(variance_list[3]) if len(variance_list) > 3 else 0.0,
                'greenness_weight': float(first_component[0]) if len(first_component) > 0 else 0.0,
                'wetness_weight': float(first_component[1]) if len(first_component) > 1 else 0.0,
                'dryness_weight': float(first_component[2]) if len(first_component) > 2 else 0.0,
                'heat_weight': float(first_component[3]) if len(first_component) > 3 else 0.0,
            }

            persisted_image, persisted_indices = _persist_rsei_analysis_result(
                request=request,
                uploaded_file_name=uploaded_file.name,
                raster_abs=raster_abs,
                calculator=calculator,
                result_items=result_items,
                pca_meta=pca_meta,
            )
            persisted_remote_sensing_image_id = str(persisted_image.id)
            persisted_remote_sensing_image_name = persisted_image.name

            response_order = ['rsei', 'greenness', 'wetness', 'dryness', 'heat']
            label_map = {item['index_type']: item['label'] for item in result_items}
            stats_map = {item['index_type']: item['stats'] for item in result_items}
            for item_type in response_order:
                persisted_index = persisted_indices[item_type]
                results.append(_build_remote_analysis_payload(
                    request=request,
                    index_type=item_type,
                    label=label_map[item_type],
                    stats=stats_map[item_type],
                    result_file_rel=persisted_index.result_file.name,
                    result_file_abs=persisted_index.result_file.path,
                    visualization_rel=persisted_index.visualization_file.name,
                ))
            result_file_url = _media_url(request, persisted_indices['rsei'].result_file.name)
        else:
            result_png_rel = f'{result_dir_rel}/{index_result_type}.png'
            result_png_abs = os.path.join(settings.MEDIA_ROOT, result_png_rel)

            if calculator:
                result_tif_rel = f'{result_dir_rel}/{index_result_type}.tif'
                result_tif_abs = os.path.join(settings.MEDIA_ROOT, result_tif_rel)
                calculator.save_result(index_data, result_tif_abs)
                result_file_url = _media_url(request, result_tif_rel)
            else:
                result_tif_rel = locals().get('result_tif_rel')
                result_tif_abs = locals().get('result_tif_abs')

            preview_calculator = calculator or EcologicalIndexCalculator(raster_abs)
            preview_calculator.create_visualization(index_data, label, result_png_abs)

            results.append(_build_remote_analysis_payload(
                request=request,
                index_type=index_result_type,
                label=label,
                stats=stats,
                result_file_rel=result_tif_rel,
                result_file_abs=result_tif_abs if result_tif_rel else None,
                visualization_rel=result_png_rel,
            ))

        supported_labels = [REMOTE_INDEX_LABELS.get(item, item.upper()) for item in supported_indices]

        return Response({
            'message': '分析完成',
            'preview_mode': preview_mode,
            'preview_message': preview_message,
            'supported_indices': supported_indices,
            'supported_index_labels': supported_labels,
            'source': {
                'filename': uploaded_file.name,
                'uploaded_file_url': _media_url(request, upload_rel),
                'bands_count': band_count,
                'supported_indices': supported_indices,
                'supported_index_labels': supported_labels,
            },
            'remote_sensing_image_id': persisted_remote_sensing_image_id,
            'remote_sensing_image_name': persisted_remote_sensing_image_name,
            'indices': results,
            'result': results[0],
        })
    except Exception as exc:
        logger.exception('上传遥感影像分析失败')
        return Response({'error': f'分析失败: {exc}'}, status=500)
    finally:
        if calculator:
            calculator.close()
        try:
            if os.path.exists(upload_abs):
                os.remove(upload_abs)
        except Exception as cleanup_error:
            logger.warning(f'清理上传临时文件失败: {cleanup_error}')
        for cleanup_dir in cleanup_dirs:
            remove_tree(cleanup_dir)


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def calculate_ecological_structure_indices(request):
    """
    计算生态环境结构指数
    包括：破碎度指数、内聚力指数、多样性指数、脆弱度指数
    """
    if 'landuse_file' not in request.FILES:
        return Response({'error': '请上传土地利用数据文件'}, status=400)

    landuse_file = request.FILES['landuse_file']
    if landuse_file.name.lower().endswith('.adf'):
        return Response({
            'error': 'ADF 是 ArcGIS 栅格目录格式，不能作为单文件上传。请先用 GDAL/ArcGIS 转为 GeoTIFF(.tif) 后再上传。'
        }, status=400)

    return _run_landuse_index_analysis(request, landuse_file, 'structure')

@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def calculate_ecological_stress_indices(request):
    """
    计算生态环境胁迫指数
    包括：土壤侵蚀指数、未利用地面积比例、耕地建设用地面积比例、土地退化指数
    """
    if 'landuse_file' not in request.FILES:
        return Response({'error': '请上传土地利用数据文件'}, status=400)

    landuse_file = request.FILES['landuse_file']
    if landuse_file.name.lower().endswith('.adf'):
        return Response({
            'error': 'ADF 是 ArcGIS 栅格目录格式，不能作为单文件上传。请先用 GDAL/ArcGIS 转为 GeoTIFF(.tif) 后再上传。'
        }, status=400)

    return _run_landuse_index_analysis(request, landuse_file, 'stress')


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def calculate_ecological_landuse_indices(request):
    """一次加载土地利用数据并计算结构指数和胁迫指数。"""
    if 'landuse_file' not in request.FILES:
        return Response({'error': '请上传土地利用数据文件'}, status=400)

    landuse_file = request.FILES['landuse_file']
    if landuse_file.name.lower().endswith('.adf'):
        return Response({
            'error': 'ADF 是 ArcGIS 栅格目录格式，不能作为单文件上传。请先用 GDAL/ArcGIS 转为 GeoTIFF(.tif) 后再上传。'
        }, status=400)

    prepared = None
    analyzer = None
    try:
        prepared = _prepare_landuse_analysis_input(
            landuse_file,
            requested_attr=request.data.get('landuse_attr'),
        )
        analyzer_cls = LandUseAnalyzer if LandUseAnalyzer is not None else RasterioLandUseAnalyzer
        analyzer = analyzer_cls(prepared['raster_input'])

        if not analyzer.load_landuse_data():
            return Response({'error': '土地利用数据加载失败'}, status=400)

        structure_results, structure_summary = _landuse_structure_payload(analyzer)
        stress_results, stress_summary = _landuse_stress_payload(analyzer)
        visualization = _landuse_visualization_payload(
            request,
            analyzer,
            landuse_file.name,
            raster_abs=prepared.get('raster_input'),
        )

        return Response({
            'message': '生态环境指数计算完成',
            'results': {
                'structure': structure_results,
                'stress': stress_results,
            },
            'summary': {
                **structure_summary,
                **stress_summary,
            },
            'visualization': visualization,
            'meta': _landuse_analysis_meta(analyzer_cls),
        })
    except ValueError as exc:
        return Response({'error': str(exc)}, status=400)
    except RuntimeError as exc:
        status_code = 503 if 'gdal' in str(exc).lower() or 'osgeo' in str(exc).lower() else 500
        return Response({'error': str(exc)}, status=status_code)
    except Exception as exc:
        logger.exception('计算土地利用综合指数失败')
        return Response({'error': f'计算失败: {exc}'}, status=500)
    finally:
        if analyzer is not None:
            analyzer.close()
        if prepared:
            _cleanup_temp_paths(prepared.get('cleanup_files'), prepared.get('cleanup_dirs'))


# 气候监测相关视图
class ClimateDataFileViewSet(viewsets.ModelViewSet):
    """气候数据文件视图集"""
    queryset = ClimateDataFile.objects.all()
    serializer_class = ClimateDataFileSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [permissions.AllowAny]

    def get_permissions(self):
        if _allow_anonymous_analysis_uploads():
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]
    
    def get_serializer_class(self):
        """根据操作选择序列化器"""
        if self.action == 'create':
            return ClimateDataFileUploadSerializer
        return ClimateDataFileSerializer
    
    def perform_create(self, serializer):
        """创建时设置上传用户"""
        if self.request.user.is_authenticated:
            serializer.save(uploaded_by=self.request.user)
        else:
            serializer.save(uploaded_by=None)
    
    @action(detail=True, methods=['post'])
    def analyze(self, request, pk=None):
        """开始气候数据分析"""
        try:
            from .climate_analysis import analyze_climate_data
            from .tasks import analyze_climate_data_task
            
            data_file = self.get_object()
            
            # 验证文件状态
            if data_file.status != 'uploaded':
                return Response({
                    'error': f'文件状态不正确，当前状态: {data_file.get_status_display()}'
                }, status=400)
            
            # 获取分析类型
            analysis_type = request.data.get('analysis_type', 'comprehensive')
            
            # 更新文件状态
            data_file.status = 'processing'
            data_file.save()
            
            # 创建处理任务
            task = ProcessingTask.objects.create(
                task_type=f'气候数据分析 - {analysis_type}',
                status='pending',
                created_by=request.user if request.user.is_authenticated else None
            )
            
            # 启动异步分析任务
            # 确保参数类型正确
            file_id_str = str(data_file.id)
            task_id_str = str(task.id)
            analyze_climate_data_task.delay(file_id_str, task_id_str, analysis_type)
            
            return Response({
                'success': True,
                'message': '分析任务已启动',
                'task_id': task.id,
                'file_id': data_file.id
            })
            
        except Exception as e:
            logger.error(f"启动气候数据分析失败: {str(e)}")
            return Response({
                'error': f'启动分析失败: {str(e)}'
            }, status=500)
    
    @action(detail=True, methods=['get'])
    def results(self, request, pk=None):
        """获取分析结果"""
        try:
            data_file = self.get_object()
            results = ClimateAnalysisResult.objects.filter(data_file=data_file).order_by('-created_at')
            
            if not results.exists():
                return Response({
                    'error': '暂无分析结果'
                }, status=404)
            
            latest_result = results.first()
            serializer = ClimateAnalysisResultSerializer(latest_result)
            
            return Response({
                'success': True,
                'data': serializer.data
            })
            
        except Exception as e:
            logger.error(f"获取分析结果失败: {str(e)}")
            return Response({
                'error': f'获取结果失败: {str(e)}'
            }, status=500)


def validate_climate_file(file_obj):
    """验证气候数据文件"""
    errors = []
    
    # 1. 检查文件是否存在
    if not file_obj:
        errors.append('文件对象不存在')
        return errors
    
    # 2. 检查文件大小（栅格数据可能较大，后端会落盘并分块统计）
    max_size = getattr(settings, 'MAX_UPLOAD_SIZE', 10 * 1024 * 1024 * 1024)
    if file_obj.size > max_size:
        errors.append(f'文件大小不能超过{max_size / (1024*1024*1024):.1f}GB，当前大小: {file_obj.size / (1024*1024):.2f}MB')
    
    # 3. 检查文件是否为空
    if file_obj.size == 0:
        errors.append('文件不能为空')
    
    # 4. 检查文件类型
    file_name = file_obj.name.lower()
    if file_name.endswith(('.shp', '.dbf', '.shx', '.prj', '.cpg', '.sbn', '.sbx')):
        errors.append('请将完整 Shapefile 组件打包为一个 ZIP 后上传，系统会自动读取属性表进行气候统计分析')
        return errors
    supported_extensions = ('.csv', '.xlsx', '.xls', '.tif', '.tiff', '.zip')
    if not file_name.endswith(supported_extensions):
        errors.append('支持 CSV、Excel、GeoTIFF 直接上传；ADF 或完整 Shapefile 组件请打包为 ZIP 后上传')

    # 扩展名只能作为第一层提示，接口还要确认文件本身确实是 ZIP。
    if file_name.endswith('.zip'):
        try:
            file_obj.file.seek(0)
            is_valid_zip = zipfile.is_zipfile(file_obj.file)
            file_obj.file.seek(0)
        except Exception:
            is_valid_zip = False
        if not is_valid_zip:
            errors.append('上传文件不是有效的 ZIP 压缩包，请重新打包后上传')
    
    # 5. 检查文件名
    if not file_name or file_name.strip() == '':
        errors.append('文件名不能为空')
    
    # 6. 检查文件名长度
    if len(file_name) > 255:
        errors.append('文件名过长，不能超过255个字符')
    
    return errors


def _detect_climate_file_capabilities(file_obj, file_type):
    file_name = getattr(file_obj, 'name', '') or ''
    file_path = None
    if isinstance(file_obj, str):
        file_path = file_obj
    else:
        try:
            file_path = getattr(file_obj, 'path', None)
        except Exception:
            file_path = None

    supported_metrics = ['temperature', 'precipitation', 'humidity', 'wind_speed']
    detected_mode = 'table'
    inferred_metric = None
    unsupported_for_climate = False
    manual_selection_required = False
    detected_category = 'climate_table'
    reason = None
    source_type = 'climate_table'
    field_mapping = {}

    if file_type in ['csv', 'xlsx', 'xls', 'tif', 'tiff', 'zip']:
        from .climate_analysis import detect_climate_file_capabilities as detect_climate_source_capabilities
        raster_capability = detect_climate_source_capabilities(file_path or file_name, file_type)
        inferred_metric = raster_capability.get('inferred_metric')
        supported_metrics = raster_capability.get('supported_metrics', [])
        detected_mode = raster_capability.get('detected_mode', 'single_metric_raster')
        unsupported_for_climate = raster_capability.get('unsupported_for_climate', False)
        manual_selection_required = raster_capability.get('manual_selection_required', False)
        detected_category = raster_capability.get('detected_category', 'single_metric_raster')
        reason = raster_capability.get('reason')
        source_type = raster_capability.get('source_type', 'single_metric_raster')
        field_mapping = raster_capability.get('field_mapping') or {}

    metric_labels = {
        'temperature': '温度',
        'precipitation': '降水量',
        'humidity': '湿度',
        'wind_speed': '风速'
    }

    return {
        'detected_mode': detected_mode,
        'inferred_metric': inferred_metric,
        'supported_metrics': supported_metrics,
        'supported_metric_labels': [metric_labels[item] for item in supported_metrics if item in metric_labels],
        'unsupported_for_climate': unsupported_for_climate,
        'manual_selection_required': manual_selection_required,
        'detected_category': detected_category,
        'reason': reason,
        'source_type': source_type,
        'field_mapping': field_mapping,
    }

@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def upload_climate_data(request):
    """上传气候数据文件"""
    try:
        # 验证请求数据
        if not request.data:
            return Response({
                'error': '请求数据为空'
            }, status=400)
        
        # 验证文件是否存在
        if 'file' not in request.FILES:
            return Response({
                'error': '没有找到文件'
            }, status=400)
        
        file_obj = request.FILES['file']
        
        # 验证文件
        file_errors = validate_climate_file(file_obj)
        if file_errors:
            return Response({
                'error': '文件验证失败',
                'details': file_errors
            }, status=400)
        
        # 验证请求数据
        required_fields = ['name']
        for field in required_fields:
            if field not in request.data or not request.data[field]:
                return Response({
                    'error': f'缺少必需字段: {field}'
                }, status=400)
        
        # 验证字段长度
        if len(request.data['name']) > 255:
            return Response({
                'error': '名称过长，不能超过255个字符'
            }, status=400)
        
        # 序列化数据
        serializer = ClimateDataFileUploadSerializer(data=request.data)
        if serializer.is_valid():
            file_type = Path(file_obj.name).suffix.lower().lstrip('.')
            
            # 创建文件记录
            try:
                data_file = ClimateDataFile.objects.create(
                    name=serializer.validated_data['name'],
                    file=file_obj,
                    file_type=file_type,
                    description=serializer.validated_data.get('description', ''),
                    uploaded_by=request.user if request.user.is_authenticated else None
                )
                capabilities = _detect_climate_file_capabilities(data_file.file, file_type)
                
                logger.info(f"气候数据文件上传成功: {data_file.id} - {data_file.name}")
                
                return Response({
                    'success': True,
                    'file_id': data_file.id,
                    'message': '文件上传成功',
                    'capabilities': capabilities,
                })
            except Exception as e:
                logger.error(f"创建文件记录失败: {str(e)}")
                return Response({
                    'error': '文件保存失败',
                    'details': str(e)
                }, status=500)
        else:
            logger.warning(f"文件上传数据验证失败: {serializer.errors}")
            return Response({
                'error': '数据验证失败',
                'details': serializer.errors
            }, status=400)
            
    except Exception as e:
        logger.error(f"文件上传异常: {str(e)}")
        return Response({
            'error': '文件上传失败',
            'details': str(e)
        }, status=500)


def validate_analysis_request(data):
    """验证分析请求数据"""
    errors = []
    
    # 1. 检查必需字段
    required_fields = ['file_id', 'analysis_type']
    for field in required_fields:
        if field not in data or not data[field]:
            errors.append(f'缺少必需字段: {field}')
    
    # 2. 验证file_id格式
    if 'file_id' in data and data['file_id']:
        try:
            import uuid
            uuid.UUID(data['file_id'])
        except (ValueError, TypeError):
            errors.append('file_id格式无效，应为UUID格式')
    
    # 3. 验证analysis_type
    if 'analysis_type' in data and data['analysis_type']:
        valid_types = ['comprehensive', 'temperature', 'precipitation', 'humidity', 'wind']
        if data['analysis_type'] not in valid_types:
            errors.append(f'analysis_type无效，支持的类型: {", ".join(valid_types)}')
    
    return errors

@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def analyze_climate_data_api(request):
    """气候数据分析API"""
    try:
        # 验证请求数据
        if not request.data:
            return Response({
                'error': '请求数据为空'
            }, status=400)
        
        # 验证分析请求
        validation_errors = validate_analysis_request(request.data)
        if validation_errors:
            return Response({
                'error': '请求数据验证失败',
                'details': validation_errors
            }, status=400)
        
        serializer = ClimateAnalysisRequestSerializer(data=request.data)
        if serializer.is_valid():
            file_id = serializer.validated_data['file_id']
            analysis_type = serializer.validated_data['analysis_type']
            
            # 验证文件是否存在
            try:
                data_file = ClimateDataFile.objects.get(id=file_id)
            except ClimateDataFile.DoesNotExist:
                logger.warning(f"分析请求失败: 文件不存在 - {file_id}")
                return Response({
                    'error': '文件不存在'
                }, status=404)
            except Exception as e:
                logger.error(f"查询文件失败: {str(e)}")
                return Response({
                    'error': '文件查询失败'
                }, status=500)
            
            # 检查文件状态
            if data_file.status != 'uploaded':
                logger.warning(f"分析请求失败: 文件状态不正确 - {data_file.id}, 状态: {data_file.status}")
                return Response({
                    'error': f'文件状态不正确，当前状态: {data_file.get_status_display()}'
                }, status=400)

            capabilities = _detect_climate_file_capabilities(data_file.file, data_file.file_type)
            if capabilities.get('unsupported_for_climate'):
                return Response({
                    'error': capabilities.get('reason') or '当前文件不适用于气候监测统计',
                    'capabilities': capabilities,
                    'suggestion': '请将该文件上传到遥感生态指数分析模块进行处理'
                }, status=400)

            # 检查文件是否真的存在
            if not data_file.file or not data_file.file.name:
                logger.error(f"文件记录存在但文件不存在: {data_file.id}")
                return Response({
                    'error': '文件数据损坏，请重新上传'
                }, status=400)
            
            # 更新文件状态
            try:
                data_file.status = 'processing'
                data_file.save()
                logger.info(f"文件状态更新为processing: {data_file.id}")
            except Exception as e:
                logger.error(f"更新文件状态失败: {str(e)}")
                return Response({
                    'error': '更新文件状态失败'
                }, status=500)
            
            # 创建处理任务
            try:
                task = ProcessingTask.objects.create(
                    task_type=f'气候数据分析 - {analysis_type}',
                    status='pending',
                    created_by=request.user if request.user.is_authenticated else None
                )
                logger.info(f"创建分析任务: {task.id} - {task.task_type}")
            except Exception as e:
                logger.error(f"创建处理任务失败: {str(e)}")
                return Response({
                    'error': '创建分析任务失败'
                }, status=500)
            
            # 启动分析任务
            from .tasks import analyze_climate_data_task
            from django.conf import settings
            
            # 在开发环境中直接执行任务，生产环境中使用异步
            if getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', False):
                # 开发环境：直接执行
                try:
                    # 确保参数类型正确
                    file_id_str = str(file_id)
                    task_id_str = str(task.id)
                    result = analyze_climate_data_task(file_id_str, task_id_str, analysis_type)
                    logger.info(f"任务直接执行完成: {result}")
                except Exception as e:
                    logger.error(f"任务直接执行失败: {str(e)}")
                    task.status = 'failed'
                    task.error_message = str(e)
                    task.save()
            else:
                # 生产环境：异步执行
                # 确保参数类型正确
                file_id_str = str(file_id)
                task_id_str = str(task.id)
                analyze_climate_data_task.delay(file_id_str, task_id_str, analysis_type)
            
            return Response({
                'success': True,
                'task_id': task.id,
                'message': '分析任务已启动'
            })
        else:
            return Response({
                'error': '数据验证失败',
                'details': serializer.errors
            }, status=400)
            
    except Exception as e:
        logger.error(f"气候数据分析API失败: {str(e)}")
        return Response({
            'error': f'分析失败: {str(e)}'
        }, status=500)


@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def get_climate_analysis_results(request, task_id):
    """获取气候分析结果"""
    try:
        task = ProcessingTask.objects.get(id=task_id)
        
        if task.status != 'completed':
            return Response({
                'success': False,
                'status': task.status,
                'message': '分析尚未完成'
            })
        
        # 查找对应的分析结果
        try:
            # 根据任务类型查找对应的分析结果
            if '气候数据分析' in task.task_type:
                # 查找气候分析结果
                from .models import ClimateAnalysisResult
                
                # 查找最近的气候分析结果
                results = ClimateAnalysisResult.objects.filter(processing_task=task).order_by('-created_at')
                
                if results.exists():
                    latest_result = results.first()
                elif ' - ' in task.task_type:
                    analysis_type = task.task_type.split(' - ', 1)[1]
                    latest_result = ClimateAnalysisResult.objects.filter(
                        analysis_type=analysis_type
                    ).order_by('-created_at').first()
                else:
                    latest_result = None

                if latest_result is not None:
                    serializer = ClimateAnalysisResultSerializer(latest_result)
                    
                    return Response({
                        'success': True,
                        'status': task.status,
                        'task_id': task.id,
                        'message': '分析完成',
                        'data': serializer.data
                    })
                else:
                    return Response({
                        'success': False,
                        'status': task.status,
                        'message': '未找到分析结果数据'
                    })
            else:
                # 其他类型的任务
                return Response({
                    'success': True,
                    'status': task.status,
                    'task_id': task.id,
                    'message': '分析完成'
                })
                
        except Exception as e:
            logger.error(f"查找分析结果失败: {str(e)}")
            return Response({
                'success': False,
                'status': task.status,
                'message': f'查找分析结果失败: {str(e)}'
            })
        
    except ProcessingTask.DoesNotExist:
        return Response({
            'error': '任务不存在'
        }, status=404)
    except Exception as e:
        logger.error(f"获取气候分析结果失败: {str(e)}")
        return Response({
            'error': f'获取结果失败: {str(e)}'
        }, status=500)


# 业务图层上传/发布
class BusinessLayerViewSet(viewsets.ModelViewSet):
    """业务图层：上传用户成果数据并发布为GeoServer WMS/WFS/WCS服务"""
    queryset = BusinessLayer.objects.all()
    serializer_class = BusinessLayerSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [permissions.AllowAny]

    def get_permissions(self):
        public_actions = {'list', 'retrieve'}
        if self.action in public_actions or _allow_anonymous_business_layer_admin():
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def get_serializer_class(self):
        if self.action == 'create':
            request_data = getattr(self.request, 'data', None)
            if request_data and request_data.get('service_url'):
                return BusinessLayerServiceSerializer
            return BusinessLayerUploadSerializer
        return BusinessLayerSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        layer = serializer.save(
            uploaded_by=request.user if request.user.is_authenticated else None,
            status='uploaded'
        )

        try:
            if layer.service_url:
                self._register_external_service_layer(layer)
            else:
                self._publish_layer(layer)
            _log_business_layer_action(
                layer,
                'upload',
                'success' if layer.status == 'published' else 'info',
                '业务图层已创建',
                operator=request.user,
                details={'source_format': layer.source_format, 'status': layer.status}
            )
        except Exception as exc:
            logger.error(f"业务图层发布失败: {exc}")
            import traceback
            logger.error(traceback.format_exc())
            layer.status = 'failed'
            layer.error_message = str(exc)
            layer.save(update_fields=['status', 'error_message', 'updated_at'])
            _log_business_layer_action(layer, 'upload', 'failed', str(exc), operator=request.user)

        layer.refresh_from_db()
        response_status = status.HTTP_201_CREATED if layer.status == 'published' else status.HTTP_202_ACCEPTED
        return Response(BusinessLayerSerializer(layer, context={'request': request}).data, status=response_status)

    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        """重新发布已上传的业务图层"""
        layer = self.get_object()
        try:
            if layer.service_url:
                self._register_external_service_layer(layer)
            else:
                self._publish_layer(layer)
            _log_business_layer_action(layer, 'publish', 'success', '业务图层发布成功', operator=request.user)
        except Exception as exc:
            layer.status = 'failed'
            layer.error_message = str(exc)
            layer.save(update_fields=['status', 'error_message', 'updated_at'])
            _log_business_layer_action(layer, 'publish', 'failed', str(exc), operator=request.user)
            return Response(BusinessLayerSerializer(layer, context={'request': request}).data, status=500)

        layer.refresh_from_db()
        return Response(BusinessLayerSerializer(layer, context={'request': request}).data)

    @action(detail=True, methods=['post'])
    def unpublish(self, request, pk=None):
        """撤销GeoServer发布，但保留用户上传的源文件和系统记录"""
        layer = self.get_object()
        try:
            self._unpublish_layer(layer)
            _log_business_layer_action(layer, 'unpublish', 'success', '业务图层已撤销发布', operator=request.user)
        except Exception as exc:
            logger.error(f"业务图层撤销发布失败: {exc}")
            _log_business_layer_action(layer, 'unpublish', 'failed', str(exc), operator=request.user)
            return Response({'error': str(exc)}, status=500)

        layer.refresh_from_db()
        return Response(BusinessLayerSerializer(layer, context={'request': request}).data)

    def destroy(self, request, *args, **kwargs):
        """删除业务图层记录；如果已发布，先同步清理GeoServer服务"""
        layer = self.get_object()
        layer_name = layer.name
        if layer.status == 'published' or layer.geoserver_store_name:
            self._unpublish_layer(layer, raise_on_error=False)
        _log_business_layer_action(layer, 'delete', 'success', f'业务图层 {layer_name} 已删除', operator=request.user)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        layer = self.get_object()
        queryset = layer.audit_logs.all()
        return Response(BusinessLayerAuditLogSerializer(queryset, many=True).data)

    @action(detail=True, methods=['post'])
    def style(self, request, pk=None):
        layer = self.get_object()
        serializer = BusinessLayerStyleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        style_config = serializer.validated_data

        try:
            self._apply_business_layer_style(layer, style_config, operator=request.user)
        except Exception as exc:
            logger.error(f"业务图层样式更新失败: {exc}")
            _log_business_layer_action(layer, 'style_update', 'failed', str(exc), operator=request.user)
            return Response({'error': str(exc)}, status=400)

        layer.refresh_from_db()
        return Response(BusinessLayerSerializer(layer, context={'request': request}).data)

    def _publish_layer(self, layer):
        from .geoserver_config import get_geoserver_manager

        layer.status = 'publishing'
        layer.error_message = ''
        layer.save(update_fields=['status', 'error_message', 'updated_at'])

        if not layer.file:
            raise ValueError('当前业务图层没有源文件，无法发布到 GeoServer')

        geoserver = get_geoserver_manager()
        geoserver.create_workspace()

        source_path = layer.file.path
        layer_name = _safe_layer_name(layer.name or os.path.splitext(os.path.basename(source_path))[0])

        if layer.layer_type == 'vector':
            extract_dir = os.path.join(settings.MEDIA_ROOT, 'business_layers', str(layer.id), 'vector')
            if layer.source_format == 'kml':
                shp_path = _convert_kml_to_shapefile(source_path, extract_dir, layer_name)
                charset = 'UTF-8'
            else:
                is_valid_zip, zip_message = validate_shapefile_zip(source_path)
                if not is_valid_zip:
                    raise ValueError(zip_message)

                shp_path = _extract_shapefile_zip(source_path, extract_dir)
                cpg_path = os.path.splitext(shp_path)[0] + '.cpg'
                charset = 'GBK'
                if os.path.exists(cpg_path):
                    with open(cpg_path, 'r', encoding='utf-8', errors='ignore') as cpg_file:
                        charset = cpg_file.read().strip() or charset

            published = geoserver.publish_shapefile(layer_name, shp_path, charset=charset)
            store_name = f'{layer_name}_store'
            metadata = {
                **(layer.metadata or {}),
                'source_shp_path': shp_path,
                'charset': charset,
                'source_origin': 'upload',
                **_vector_layer_metadata(shp_path),
            }
        else:
            store_name = f'{layer_name}_store'
            published = geoserver.publish_raster(store_name, layer_name, source_path)
            metadata = {
                **(layer.metadata or {}),
                'source_raster_path': source_path,
                'source_origin': 'upload',
                **_raster_layer_metadata(source_path),
            }

        urls = _build_ogc_urls(geoserver, layer_name, layer.layer_type)
        health = _check_layer_service_availability(layer=type('LayerProbe', (), {
            'layer_type': layer.layer_type,
            'wms_url': urls['wms_url'],
            'wfs_url': urls['wfs_url'],
            'wcs_url': urls['wcs_url'],
            'service_type_name': None,
            'geoserver_layer_name': layer_name,
            'geoserver_workspace': geoserver.workspace,
            'service_srs': metadata.get('crs'),
            'metadata': metadata,
        })())
        layer.geoserver_workspace = geoserver.workspace
        layer.geoserver_store_name = store_name
        layer.geoserver_layer_name = layer_name
        layer.wms_url = urls['wms_url']
        layer.wfs_url = urls['wfs_url']
        layer.wcs_url = urls['wcs_url']
        layer.metadata = metadata
        layer.status = 'published' if published else 'failed'
        layer.error_message = '' if published else 'GeoServer发布失败，请检查GeoServer服务、文件路径和日志'
        layer.published_at = timezone.now() if published else None
        layer.service_srs = metadata.get('crs')
        layer.service_health_status = health['service_health_status'] if published else 'unhealthy'
        layer.service_health_message = health['service_health_message'] if published else layer.error_message
        layer.service_checked_at = health['service_checked_at'] if published else timezone.now()
        layer.save()

        if published:
            self._apply_business_layer_style(layer)

        if not published:
            raise RuntimeError(layer.error_message)

    def _register_external_service_layer(self, layer):
        metadata = dict(layer.metadata or {})
        metadata['is_external_service'] = True
        metadata['service_registered_at'] = timezone.now().isoformat()
        metadata['source_origin'] = 'external_service'

        service_url = (layer.service_url or '').strip()
        service_type_name = (layer.service_type_name or '').strip()

        if layer.source_format == 'wms':
            layer.wms_url = service_url
            layer.wfs_url = None
            layer.wcs_url = None
        elif layer.source_format == 'wfs':
            layer.wms_url = None
            layer.wfs_url = service_url
            layer.wcs_url = None
        elif layer.source_format == 'wcs':
            layer.wms_url = None
            layer.wfs_url = None
            layer.wcs_url = service_url

        layer.geoserver_workspace = None
        layer.geoserver_store_name = None
        layer.geoserver_layer_name = service_type_name or layer.name
        layer.metadata = metadata
        layer.status = 'published'
        layer.error_message = ''
        layer.published_at = timezone.now()
        health = _check_layer_service_availability(layer)
        layer.service_health_status = health['service_health_status']
        layer.service_health_message = health['service_health_message']
        layer.service_checked_at = health['service_checked_at']
        layer.save()
        if layer.source_format == 'wms' and layer.style_config:
            _log_business_layer_action(layer, 'style_update', 'info', '外部服务已记录样式配置，需由外部服务端实际生效', operator=None)

    def _unpublish_layer(self, layer, raise_on_error=True):
        from .geoserver_config import get_geoserver_manager

        metadata = dict(layer.metadata or {})
        if metadata.get('is_external_service'):
            metadata['last_unpublished_at'] = timezone.now().isoformat()
            layer.status = 'uploaded'
            layer.error_message = ''
            layer.wms_url = None
            layer.wfs_url = None
            layer.wcs_url = None
            layer.published_at = None
            layer.service_health_status = 'unknown'
            layer.service_health_message = '服务已撤销发布'
            layer.service_checked_at = timezone.now()
            layer.metadata = metadata
            layer.save(update_fields=[
                'status', 'error_message', 'wms_url', 'wfs_url', 'wcs_url',
                'published_at', 'service_health_status', 'service_health_message',
                'service_checked_at', 'metadata', 'updated_at'
            ])
            return

        geoserver = get_geoserver_manager()
        store_name = layer.geoserver_store_name
        if not store_name and layer.geoserver_layer_name:
            store_name = f'{layer.geoserver_layer_name}_store'

        success = True
        if store_name:
            if layer.layer_type == 'vector':
                success = geoserver.delete_datastore(store_name, recurse=True)
            else:
                success = geoserver.delete_coveragestore(store_name, recurse=True)

        if not success and raise_on_error:
            raise RuntimeError('GeoServer服务清理失败，请检查GeoServer是否启动或手动删除对应存储')

        metadata = dict(layer.metadata or {})
        metadata['last_unpublished_at'] = timezone.now().isoformat()
        layer.status = 'uploaded'
        layer.error_message = '' if success else 'GeoServer服务清理失败，数据库记录已保留'
        layer.geoserver_workspace = None
        layer.geoserver_store_name = None
        layer.geoserver_layer_name = None
        layer.wms_url = None
        layer.wfs_url = None
        layer.wcs_url = None
        layer.published_at = None
        layer.service_health_status = 'unknown'
        layer.service_health_message = '服务已撤销发布'
        layer.service_checked_at = timezone.now()
        layer.metadata = metadata
        layer.save()

    def _apply_business_layer_style(self, layer, style_config=None, operator=None):
        from .geoserver_config import get_geoserver_manager

        next_style_config = dict(layer.style_config or {})
        if style_config:
            next_style_config.update(style_config)

        if layer.metadata.get('is_external_service'):
            layer.style_name = next_style_config.get('style_name') or layer.style_name
            layer.style_config = next_style_config
            if style_config and 'sld_content' in style_config:
                layer.sld_content = style_config.get('sld_content') or None
            layer.save(update_fields=['style_name', 'style_config', 'sld_content', 'updated_at'])
            _log_business_layer_action(
                layer,
                'style_update',
                'info',
                '外部服务图层仅记录样式配置，未直接改写远程服务样式',
                operator=operator,
                details={'style_name': layer.style_name, 'style_config': layer.style_config}
            )
            return

        if not layer.geoserver_layer_name:
            raise ValueError('当前图层尚未发布到 GeoServer，不能应用样式')

        geoserver = get_geoserver_manager()
        metadata = dict(layer.metadata or {})
        if layer.layer_type == 'vector':
            vector_meta = metadata.get('style_vector_meta') or {}
            if not vector_meta:
                source_path = metadata.get('source_shp_path')
                geometry_type = 'polygon'
                classification_field = next_style_config.get('classification_field')
                min_value = None
                max_value = None
                if source_path:
                    try:
                        from osgeo import ogr
                        datasource = ogr.Open(source_path)
                        if datasource:
                            source_layer = datasource.GetLayer(0)
                            geom_name = source_layer.GetGeomType()
                            if geom_name in [1, 4]:
                                geometry_type = 'point'
                            elif geom_name in [2, 5]:
                                geometry_type = 'line'
                            if classification_field:
                                values = []
                                for feature in source_layer:
                                    value = feature.GetField(classification_field)
                                    if value is not None:
                                        try:
                                            values.append(float(value))
                                        except (TypeError, ValueError):
                                            pass
                                if values:
                                    min_value = min(values)
                                    max_value = max(values)
                            datasource = None
                    except Exception as exc:
                        logger.warning(f'读取矢量样式元数据失败: {exc}')
                vector_meta = {
                    'geometry_type': geometry_type,
                    'min_value': min_value,
                    'max_value': max_value,
                }
            next_style_config.setdefault('geometry_type', vector_meta.get('geometry_type') or 'polygon')
            if vector_meta.get('min_value') is not None:
                next_style_config['min_value'] = vector_meta['min_value']
            if vector_meta.get('max_value') is not None:
                next_style_config['max_value'] = vector_meta['max_value']
            generated_sld = next_style_config.get('sld_content') or _vector_style_sld(layer.geoserver_layer_name, next_style_config)
        else:
            raster_meta = metadata.get('style_raster_meta') or {}
            if not raster_meta:
                source_path = metadata.get('source_raster_path')
                if source_path and os.path.exists(source_path):
                    try:
                        with rasterio.open(source_path) as dataset:
                            data = dataset.read(1, masked=True)
                            valid_data = data.compressed() if hasattr(data, 'compressed') else data.flatten()
                            if valid_data.size:
                                inferred_rgb = _infer_raster_rgb_bands(dataset)
                                raster_meta = {
                                    'min_value': float(np.min(valid_data)),
                                    'max_value': float(np.max(valid_data)),
                                    'nodata': dataset.nodata,
                                    'band_count': dataset.count,
                                    'rgb_bands': inferred_rgb,
                                }
                    except Exception as exc:
                        logger.warning(f'读取栅格样式元数据失败: {exc}')
            next_style_config.setdefault('min_value', raster_meta.get('min_value', 0.0))
            next_style_config.setdefault('max_value', raster_meta.get('max_value', 100.0))
            next_style_config.setdefault('nodata', raster_meta.get('nodata'))
            next_style_config.setdefault('band_count', raster_meta.get('band_count') or metadata.get('band_count') or 1)
            if next_style_config.get('band_count', 1) >= 3:
                rgb_bands = (
                    raster_meta.get('rgb_bands')
                    or metadata.get('rgb_bands')
                    or {'red_band': 3, 'green_band': 2, 'blue_band': 1}
                )
                next_style_config.setdefault('red_band', rgb_bands.get('red_band', 3))
                next_style_config.setdefault('green_band', rgb_bands.get('green_band', 2))
                next_style_config.setdefault('blue_band', rgb_bands.get('blue_band', 1))
            generated_sld = next_style_config.get('sld_content') or _raster_style_sld(layer.geoserver_layer_name, next_style_config)

        style_name = next_style_config.get('style_name') or layer.style_name or f'{layer.geoserver_layer_name}_style'
        created = geoserver.create_style(style_name, generated_sld)
        if not created:
            raise RuntimeError('GeoServer 样式创建或更新失败')
        if not geoserver.apply_style_to_layer(layer.geoserver_layer_name, style_name):
            raise RuntimeError('GeoServer 样式应用失败')

        layer.style_name = style_name
        layer.style_config = {key: value for key, value in next_style_config.items() if key != 'sld_content'}
        layer.sld_content = generated_sld
        layer.metadata = metadata
        layer.save(update_fields=['style_name', 'style_config', 'sld_content', 'metadata', 'updated_at'])
        _log_business_layer_action(
            layer,
            'style_update',
            'success',
            '业务图层样式已更新',
            operator=operator,
            details={'style_name': style_name, 'style_config': layer.style_config}
        )


# 叠加分析相关视图集

class EcologicalIndexFileViewSet(viewsets.ModelViewSet):
    """生态指数文件视图集"""
    queryset = EcologicalIndexFile.objects.all()
    serializer_class = EcologicalIndexFileSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [AllowAny]

    def get_permissions(self):
        if _allow_anonymous_overlay_admin():
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def get_serializer_class(self):
        if self.action == 'create':
            return EcologicalIndexFileUploadSerializer
        return EcologicalIndexFileSerializer

    def create(self, request, *args, **kwargs):
        upload_serializer = self.get_serializer(data=request.data)
        upload_serializer.is_valid(raise_exception=True)
        self.perform_create(upload_serializer)
        instance = upload_serializer.instance
        response_serializer = EcologicalIndexFileSerializer(instance, context={'request': request})
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    def perform_create(self, serializer):
        """处理文件上传"""
        instance = serializer.save(uploaded_by=self.request.user if self.request.user.is_authenticated else None)

        # 处理上传的JSON文件
        try:
            file_content = instance.file.read().decode('utf-8')
            indices_data = json.loads(file_content)

            # 保存解析后的数据
            instance.indices_data = indices_data
            instance.timestamp = timezone.now()
            instance.status = 'completed'
            instance.processed_at = timezone.now()
            instance.save()

        except Exception as e:
            instance.status = 'failed'
            instance.error_message = f"文件解析失败: {str(e)}"
            instance.save()
            logger.error(f"生态指数文件解析失败: {str(e)}")


class EcologicalProjectFileViewSet(viewsets.ModelViewSet):
    """生态修复工程文件视图集"""
    queryset = EcologicalProjectFile.objects.all()
    serializer_class = EcologicalProjectFileSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [AllowAny]

    def get_permissions(self):
        if _allow_anonymous_overlay_admin():
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def get_serializer_class(self):
        if self.action == 'create':
            return EcologicalProjectFileUploadSerializer
        return EcologicalProjectFileSerializer

    def create(self, request, *args, **kwargs):
        upload_serializer = self.get_serializer(data=request.data)
        upload_serializer.is_valid(raise_exception=True)
        self.perform_create(upload_serializer)
        instance = upload_serializer.instance
        response_serializer = EcologicalProjectFileSerializer(instance, context={'request': request})
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    def perform_create(self, serializer):
        """处理文件上传"""
        instance = serializer.save(uploaded_by=self.request.user if self.request.user.is_authenticated else None)

        # 处理上传的GeoJSON文件
        try:
            file_content = instance.file.read().decode('utf-8')
            geojson_data = json.loads(file_content)

            # 验证GeoJSON格式
            if geojson_data.get('type') != 'FeatureCollection':
                raise ValueError("文件必须是有效的GeoJSON FeatureCollection格式")

            # 保存解析后的数据
            instance.geojson_data = geojson_data
            instance.status = 'completed'
            instance.processed_at = timezone.now()
            instance.save()

        except Exception as e:
            instance.status = 'failed'
            instance.error_message = f"文件解析失败: {str(e)}"
            instance.save()
            logger.error(f"生态修复工程文件解析失败: {str(e)}")


class OverlayAnalysisTaskViewSet(viewsets.ModelViewSet):
    """叠加分析任务视图集"""
    queryset = OverlayAnalysisTask.objects.all()
    serializer_class = OverlayAnalysisTaskSerializer
    authentication_classes = []
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser, JSONParser]  # 支持文件上传

    def get_permissions(self):
        public_actions = {'list', 'retrieve', 'risk_statistics', 'available_rsei_sources', 'uploaded_layer_metadata', 'uploaded_vector_geojson'}
        if self.action in public_actions:
            return [permissions.AllowAny()]
        if _allow_anonymous_overlay_admin():
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def get_serializer_class(self):
        if self.action == 'create':
            return OverlayAnalysisTaskCreateSerializer
        return OverlayAnalysisTaskSerializer

    def perform_create(self, serializer):
        """创建叠加分析任务"""
        instance = serializer.save(created_by=self.request.user if self.request.user.is_authenticated else None)

        # 异步执行分析（这里简化为同步执行）
        try:
            from .overlay_analysis import perform_overlay_analysis
            perform_overlay_analysis(str(instance.id))
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            logger.error(f"启动叠加分析失败: {str(e)}")
            logger.error(f"错误堆栈:\n{error_trace}")
            instance.status = 'failed'
            instance.error_message = str(e)
            instance.save()
            # 不要重新抛出异常，让DRF正常返回创建成功的响应
            # 前端可以通过轮询任务状态来获取失败信息

    @action(detail=False, methods=['get'], url_path='uploaded-layer-metadata')
    def uploaded_layer_metadata(self, request):
        """获取叠加分析上传图层的描述元数据"""
        configs = _get_overlay_layer_configs()
        metadata = _load_overlay_metadata()
        payload = {}
        for layer_type, config in configs.items():
            layer_meta = metadata.get(layer_type, {})
            published = any(os.path.exists(path) for path in config['paths'])
            payload[layer_type] = {
                'label': config['label'],
                'layer_name': layer_meta.get('layer_name') or config['layer_name'],
                'file_name': layer_meta.get('file_name') or '',
                'description': layer_meta.get('description') or '',
                'updated_at': layer_meta.get('updated_at'),
                'source_type': layer_meta.get('source_type') or '',
                'source_image_id': layer_meta.get('source_image_id') or '',
                'source_image_name': layer_meta.get('source_image_name') or '',
                'source_result_id': layer_meta.get('source_result_id') or '',
                'source_result_created_at': layer_meta.get('source_result_created_at'),
                'service_mode': layer_meta.get('service_mode') or ('geoserver' if layer_meta.get('geoserver_published') else 'local'),
                'geoserver_published': bool(layer_meta.get('geoserver_published')),
                'published': published,
            }

            if config['kind'] == 'raster' and published:
                raster_path = config['paths'][0]
                visualization_rel = None
                source_type = payload[layer_type].get('source_type') or ''
                if os.path.exists(raster_path):
                    try:
                        with rasterio.open(raster_path) as dataset:
                            bounds = dataset.bounds
                            crs = dataset.crs.to_string() if dataset.crs else 'EPSG:4326'
                            payload[layer_type]['bounds'] = [bounds.left, bounds.bottom, bounds.right, bounds.top]
                            payload[layer_type]['crs'] = crs
                    except Exception as exc:
                        logger.warning(f"读取叠加生态栅格范围失败: {exc}")

                source_result_id = payload[layer_type].get('source_result_id')
                if source_result_id:
                    try:
                        index_obj = EcologicalIndex.objects.get(id=source_result_id)
                        if getattr(index_obj, 'visualization_file', None):
                            visualization_rel = index_obj.visualization_file.name
                            payload[layer_type]['visualization_file_url'] = _media_url(request, visualization_rel)
                    except EcologicalIndex.DoesNotExist:
                        pass
                    except Exception as exc:
                        logger.warning(f"读取叠加生态结果可视化地址失败: {exc}")

                try:
                    result_file_rel = os.path.relpath(raster_path, settings.MEDIA_ROOT).replace('\\', '/')
                    compare_overlay = _build_compare_overlay_payload(
                        request=request,
                        raster_abs=raster_path,
                        result_file_rel=result_file_rel,
                        visualization_rel=visualization_rel,
                        source_filename=payload[layer_type].get('file_name') or os.path.basename(raster_path),
                        style_hint='rsei',
                        infer_background_value=source_type == 'uploaded_raster' or layer_type == 'ecology_uploaded',
                    )
                    if compare_overlay:
                        payload[layer_type]['overlay_image_url'] = compare_overlay.get('overlay_image_url')
                except Exception as exc:
                    logger.warning(f"生成叠加生态透明覆盖图失败: {exc}")
            elif config['kind'] == 'vector' and published:
                shp_path = _overlay_vector_shp_path(layer_type)
                if shp_path and os.path.exists(shp_path):
                    payload[layer_type]['geojson_url'] = _overlay_vector_geojson_url(layer_type)
                    try:
                        if shapefile is not None:
                            with shapefile.Reader(shp_path) as reader:
                                payload[layer_type]['bounds'] = list(reader.bbox) if reader.bbox else None
                                payload[layer_type]['feature_count'] = len(reader)
                        else:
                            geojson = _shapefile_to_geojson(shp_path)
                            payload[layer_type]['bounds'] = _geojson_feature_collection_bounds(geojson)
                            payload[layer_type]['feature_count'] = len(geojson.get('features') or [])
                    except Exception as exc:
                        logger.warning(f"读取叠加矢量元数据失败: {exc}")

        return Response({
            'success': True,
            'data': payload,
        })

    @action(detail=False, methods=['get'], url_path='uploaded-vector-geojson')
    def uploaded_vector_geojson(self, request):
        """返回叠加分析已上传矢量的 GeoJSON，用于 GeoServer 不可用时本地显示。"""
        layer_type = request.query_params.get('data_type')
        configs = _get_overlay_layer_configs()
        config = configs.get(layer_type)
        if not config or config.get('kind') != 'vector':
            return Response({
                'success': False,
                'message': '不支持的矢量图层类型'
            }, status=400)

        shp_path = _overlay_vector_shp_path(layer_type)
        if not shp_path or not os.path.exists(shp_path):
            return Response({
                'success': False,
                'message': f"{config['label']}文件不存在，请先上传。"
            }, status=404)

        try:
            geojson = _shapefile_to_geojson(shp_path)
            feature_count = len(geojson.get('features') or [])
            return Response({
                'success': True,
                'data_type': layer_type,
                'feature_count': feature_count,
                'geojson': geojson,
            })
        except Exception as exc:
            logger.exception(f"读取{config['label']}GeoJSON失败")
            return Response({
                'success': False,
                'message': f"{config['label']}解析失败: {exc}"
            }, status=500)

    @action(detail=False, methods=['post'], url_path='sync-latest-rsei')
    def sync_latest_rsei(self, request):
        """将最新或指定影像的RSEI结果同步为叠加分析生态图层"""
        remote_sensing_image_id = request.data.get('remote_sensing_image_id') or request.query_params.get('remote_sensing_image_id')
        result = _sync_latest_rsei_to_overlay(remote_sensing_image_id=remote_sensing_image_id)
        status_code = 200 if result.get('success') or result.get('reason') == 'no_rsei_result' else 400
        return Response(result, status=status_code)

    @action(detail=False, methods=['get'], url_path='available-rsei-sources')
    def available_rsei_sources(self, request):
        """获取可用于叠加分析的RSEI结果来源列表"""
        return Response({
            'success': True,
            'data': _list_available_rsei_sources()
        })

    @action(detail=False, methods=['delete'], url_path='clear-rsei-cache')
    def clear_rsei_cache(self, request):
        """清理叠加分析可选的系统生成 RSEI 缓存和当前生态栅格挂接。"""
        ecology_config = _get_overlay_layer_configs()['ecology_synced']
        removed_paths = []

        try:
            from .geoserver_config import geoserver_manager
            geoserver_manager.delete_coveragestore(ecology_config['store'], recurse=True)
        except Exception as exc:
            logger.warning(f"清理RSEI缓存时删除GeoServer生态图层失败: {exc}")

        for path in ecology_config['paths']:
            try:
                if os.path.exists(path):
                    os.remove(path)
                    removed_paths.append(path)
            except Exception as exc:
                logger.warning(f"清理RSEI缓存时删除叠加生态栅格失败 {path}: {exc}")

        generated_description = '通过遥感生态指数分析页面生成的 RSEI 结果源影像'
        generated_images = list(RemoteSensingImage.objects.filter(description=generated_description))
        media_root = os.path.abspath(str(settings.MEDIA_ROOT))
        cleanup_paths = []
        cleanup_dirs = []

        for image in generated_images:
            try:
                if image.file_path:
                    cleanup_paths.append(image.file_path.path)
            except Exception:
                pass
            try:
                if image.thumbnail:
                    cleanup_paths.append(image.thumbnail.path)
            except Exception:
                pass
            cleanup_dirs.append(os.path.join(settings.MEDIA_ROOT, 'ecological_indices', str(image.id)))

        deleted_sources = len(generated_images)
        if generated_images:
            RemoteSensingImage.objects.filter(id__in=[image.id for image in generated_images]).delete()

        def is_under_media(path):
            try:
                abs_path = os.path.abspath(str(path))
                return os.path.commonpath([media_root, abs_path]) == media_root
            except Exception:
                return False

        for path in cleanup_paths:
            if not path or not is_under_media(path):
                continue
            try:
                if os.path.exists(path):
                    os.remove(path)
                    removed_paths.append(path)
            except Exception as exc:
                logger.warning(f"清理RSEI缓存文件失败 {path}: {exc}")

        for path in cleanup_dirs:
            if not path or not is_under_media(path):
                continue
            try:
                if os.path.isdir(path):
                    remove_tree(path)
                    removed_paths.append(path)
            except Exception as exc:
                logger.warning(f"清理RSEI缓存目录失败 {path}: {exc}")

        _clear_overlay_metadata('ecology_synced')

        return Response({
            'success': True,
            'message': 'RSEI缓存已清除',
            'deleted_sources': deleted_sources,
            'removed_paths': removed_paths,
        })

    @action(detail=False, methods=['delete'], url_path='delete-uploaded-layer')
    def delete_uploaded_layer(self, request):
        """删除叠加分析中已上传并发布的固定业务图层"""
        layer_type = request.query_params.get('data_type') or request.data.get('data_type')
        layer_configs = _get_overlay_layer_configs()

        if layer_type not in layer_configs:
            return Response({
                'success': False,
                'message': '不支持的数据类型'
            }, status=400)

        if layer_type in {'economy', 'engineering'}:
            target_layer_types = [layer_type, *(f'{layer_type}_{suffix}' for suffix in VECTOR_GEOMETRY_SUFFIXES.keys())]
        else:
            target_layer_types = [layer_type]

        group_label = layer_configs[layer_type]['label']
        removed_paths = []
        geoserver_success = True
        for target_layer_type in target_layer_types:
            config = layer_configs.get(target_layer_type)
            if not config:
                continue

            try:
                from .geoserver_config import geoserver_manager
                if config['kind'] == 'raster':
                    geoserver_success = geoserver_manager.delete_coveragestore(config['store'], recurse=True) and geoserver_success
                else:
                    geoserver_success = geoserver_manager.delete_datastore(config['store'], recurse=True) and geoserver_success
            except Exception as exc:
                geoserver_success = False
                logger.warning(f"删除{config['label']}GeoServer服务失败: {exc}")

            for path in config['paths']:
                try:
                    if os.path.isdir(path):
                        remove_tree(path)
                        removed_paths.append(path)
                    elif os.path.exists(path):
                        os.remove(path)
                        removed_paths.append(path)
                except Exception as exc:
                    logger.warning(f"删除本地文件失败 {path}: {exc}")

            _clear_overlay_metadata(target_layer_type)

        return Response({
            'success': geoserver_success,
            'message': f"{group_label}已删除" if geoserver_success else f"{group_label}本地记录已清理，但GeoServer服务删除可能未完成",
            'data_type': layer_type,
            'removed_paths': removed_paths,
        })

    @action(detail=True, methods=['post'])
    def restart_analysis(self, request, pk=None):
        """重新启动分析"""
        task = self.get_object()

        if task.status in ['processing']:
            return Response({
                'error': '任务正在进行中，无法重新启动'
            }, status=400)

        try:
            # 重置任务状态
            task.status = 'pending'
            task.progress = 0
            task.current_step = None
            task.error_message = None
            task.analysis_results = {}
            task.overall_risk_level = None
            task.started_at = None
            task.completed_at = None
            task.save()

            # 重新执行分析
            from .overlay_analysis import perform_overlay_analysis
            perform_overlay_analysis(str(task.id))

            return Response({
                'message': '分析已重新启动',
                'task_id': task.id
            })

        except Exception as e:
            logger.error(f"重新启动分析失败: {str(e)}")
            return Response({
                'error': f'重新启动失败: {str(e)}'
            }, status=500)

    @action(detail=False, methods=['get'])
    def risk_statistics(self, request):
        """获取风险统计信息"""
        try:
            # 统计各风险等级的任务数量
            risk_stats = {}
            for choice in OverlayAnalysisTask.RISK_LEVEL_CHOICES:
                level = choice[0]
                count = OverlayAnalysisTask.objects.filter(
                    overall_risk_level=level,
                    status='completed'
                ).count()
                risk_stats[level] = count

            # 统计任务状态
            status_stats = {}
            for choice in OverlayAnalysisTask.STATUS_CHOICES:
                status = choice[0]
                count = OverlayAnalysisTask.objects.filter(status=status).count()
                status_stats[status] = count

            return Response({
                'risk_distribution': risk_stats,
                'status_distribution': status_stats,
                'total_tasks': OverlayAnalysisTask.objects.count(),
                'completed_tasks': OverlayAnalysisTask.objects.filter(status='completed').count()
            })

        except Exception as e:
            logger.error(f"获取风险统计失败: {str(e)}")
            return Response({
                'error': f'获取统计信息失败: {str(e)}'
            }, status=500)

    @action(detail=True, methods=['post'])
    def republish_raster_layers(self, request, pk=None):
        """重新发布栅格图层到GeoServer"""
        task = self.get_object()
        
        try:
            from .geoserver_config import get_geoserver_manager
            
            geoserver = get_geoserver_manager()
            
            # 确保工作空间存在
            geoserver.create_workspace()
            
            # 清理旧的CoverageStore（如果需要）
            coverage_store_name = f"overlay_{task.id}"
            geoserver.delete_coveragestore(coverage_store_name, recurse=True)
            
            # 获取栅格文件
            published_layers = {}
            raster_metadata = task.raster_layers_metadata.copy() if task.raster_layers_metadata else {}
            error_messages = []  # 收集错误信息
            
            # 发布风险栅格
            if task.risk_raster_file:
                risk_file_path = task.risk_raster_file.path
                if os.path.exists(risk_file_path):
                    layer_name = f"risk_layer_{task.id}"
                    logger.info(f"开始重新发布风险栅格图层: {layer_name}")
                    logger.info(f"栅格文件路径: {risk_file_path}")
                    
                    # 先删除可能存在的旧图层（如果名称不同）
                    try:
                        full_layer_name = f"{geoserver.workspace}:{layer_name}"
                        old_layer_check = geoserver.get_layer_info(full_layer_name)
                        if old_layer_check:
                            logger.info(f"发现旧图层 {layer_name}，尝试删除")
                            # 尝试通过GeoServer REST API删除图层
                            try:
                                delete_url = f"{geoserver.base_url}/rest/layers/{full_layer_name}.json"
                                import requests
                                response = requests.delete(delete_url, auth=geoserver.auth, timeout=30)
                                if response.status_code in [200, 204]:
                                    logger.info(f"旧图层 {layer_name} 删除成功")
                                else:
                                    logger.warning(f"删除旧图层返回状态码: {response.status_code}")
                            except Exception as del_error:
                                logger.warning(f"删除旧图层时出错: {del_error}")
                            time.sleep(1)
                    except Exception as e:
                        logger.warning(f"检查旧图层时出错（可能不存在）: {e}")
                    
                    publish_result = geoserver.publish_raster(coverage_store_name, layer_name, risk_file_path)
                    logger.info(f"publish_raster 返回结果: {publish_result}")
                    
                    if publish_result:
                        # 等待一下让GeoServer处理
                        time.sleep(3)  # 增加等待时间，确保重命名完成
                        
                        # 验证图层是否存在（先尝试期望的名称）
                        full_layer_name = f"{geoserver.workspace}:{layer_name}"
                        layer_check = geoserver.get_layer_info(full_layer_name)
                        logger.info(f"图层验证结果（期望名称 {layer_name}）: {layer_check is not None}")
                        
                        # 如果期望名称的图层不存在，尝试查找实际创建的图层名称（可能是CoverageStore名称）
                        actual_layer_name = layer_name
                        if not layer_check:
                            logger.info(f"⚠️ 期望图层名称 {layer_name} 不存在，尝试查找实际创建的图层...")
                            # 检查CoverageStore中的Coverage名称
                            try:
                                coverage_list = geoserver._make_request('GET', f'workspaces/{geoserver.workspace}/coveragestores/{coverage_store_name}/coverages.json')
                                if coverage_list and 'coverages' in coverage_list:
                                    coverages = coverage_list['coverages'].get('coverage', [])
                                    if isinstance(coverages, list) and len(coverages) > 0:
                                        coverage_obj = coverages[0]
                                        if isinstance(coverage_obj, dict):
                                            actual_layer_name = coverage_obj.get('name', layer_name)
                                        else:
                                            actual_layer_name = coverage_store_name  # 使用CoverageStore名称
                                    elif isinstance(coverages, dict):
                                        actual_layer_name = coverages.get('name', layer_name)
                                    else:
                                        actual_layer_name = coverage_store_name  # 使用CoverageStore名称
                                    
                                    logger.info(f"找到实际图层名称: {actual_layer_name}")
                                    # 验证实际图层是否存在
                                    full_actual_name = f"{geoserver.workspace}:{actual_layer_name}"
                                    layer_check = geoserver.get_layer_info(full_actual_name)
                                    if layer_check:
                                        logger.info(f"✅ 找到实际创建的图层: {actual_layer_name}")
                                        layer_name = actual_layer_name  # 使用实际图层名称
                                    else:
                                        logger.warning(f"⚠️ 实际图层名称 {actual_layer_name} 也不存在，可能GeoServer尚未完全处理")
                            except Exception as e:
                                logger.warning(f"⚠️ 查找实际图层名称时出错: {e}")
                        
                        if layer_check:
                            # 为图层创建并应用默认样式
                            style_name = f"{layer_name}_style"
                            logger.info(f"为图层 {layer_name} 创建样式: {style_name}")
                            
                            # 从栅格文件读取统计信息，以创建合适的样式
                            # 快速模式：使用默认值域，避免长时间读取栅格数据
                            logger.info(f"快速模式：使用默认值域创建样式（避免长时间读取栅格数据）")
                            min_val, max_val = (0.0, 5.0)
                            
                            # 可选：尝试快速读取统计信息（不阻塞）
                            try:
                                import threading
                                result = [None]
                                def quick_get_stats():
                                    try:
                                        result[0] = geoserver._get_raster_statistics(risk_file_path)
                                    except:
                                        pass
                                
                                thread = threading.Thread(target=quick_get_stats)
                                thread.daemon = True
                                thread.start()
                                thread.join(timeout=3)  # 3秒超时
                                
                                if result[0] and not thread.is_alive():
                                    min_val, max_val = result[0]
                                    logger.info(f"✅ 快速获取到统计信息，更新值域: {min_val} - {max_val}")
                            except:
                                pass
                            
                            logger.info(f"使用栅格值域创建样式: {min_val} - {max_val}")
                            
                            sld_content = geoserver._create_default_raster_sld(min_val, max_val)
                            if geoserver.create_style(style_name, sld_content):
                                logger.info(f"样式 {style_name} 创建成功，开始应用到图层")
                                if geoserver.apply_style_to_layer(layer_name, style_name):
                                    logger.info(f"✅ 样式已成功应用到图层 {layer_name}")
                                else:
                                    logger.warning(f"⚠️ 样式应用到图层失败，但图层已发布")
                            else:
                                logger.warning(f"⚠️ 样式创建失败，但图层已发布")
                            
                            wms_url = f"{geoserver.base_url}/ows?service=WMS&version=1.3.0&request=GetMap&layers={geoserver.workspace}:{layer_name}&format=image/png&transparent=true"
                            
                            if 'risk_layer' not in raster_metadata:
                                raster_metadata['risk_layer'] = {}
                            
                            raster_metadata['risk_layer'].update({
                                'wms_url': wms_url,
                                'published': True
                            })
                            
                            published_layers['risk_layer'] = {
                                'layer_name': layer_name,
                                'wms_url': wms_url
                            }
                            logger.info(f"✅ 风险栅格图层重新发布成功: {layer_name}")
                        else:
                            error_msg = f"图层 {layer_name} 发布后验证失败（图层在GeoServer中不存在，实际图层名称: {actual_layer_name}）"
                            logger.error(f"❌ {error_msg}")
                            error_messages.append(error_msg)
                    else:
                        error_msg = f"风险栅格图层发布失败: {layer_name}（publish_raster返回False）"
                        logger.error(f"❌ {error_msg}")
                        error_messages.append(error_msg)
                else:
                    error_msg = f"风险栅格文件不存在: {risk_file_path}"
                    logger.error(f"❌ {error_msg}")
                    error_messages.append(error_msg)
            else:
                error_msg = "任务没有关联的风险栅格文件"
                logger.warning(f"⚠️ {error_msg}")
                error_messages.append(error_msg)
            
            # 发布影响栅格
            if task.impact_raster_file:
                impact_file_path = task.impact_raster_file.path
                if os.path.exists(impact_file_path):
                    layer_name = f"impact_layer_{task.id}"
                    logger.info(f"开始重新发布影响栅格图层: {layer_name}")
                    logger.info(f"栅格文件路径: {impact_file_path}")
                    
                    # 先删除可能存在的旧图层（如果名称不同）
                    try:
                        full_layer_name = f"{geoserver.workspace}:{layer_name}"
                        old_layer_check = geoserver.get_layer_info(full_layer_name)
                        if old_layer_check:
                            logger.info(f"发现旧图层 {layer_name}，尝试删除")
                            # 尝试通过GeoServer REST API删除图层
                            try:
                                delete_url = f"{geoserver.base_url}/rest/layers/{full_layer_name}.json"
                                import requests
                                response = requests.delete(delete_url, auth=geoserver.auth, timeout=30)
                                if response.status_code in [200, 204]:
                                    logger.info(f"旧图层 {layer_name} 删除成功")
                                else:
                                    logger.warning(f"删除旧图层返回状态码: {response.status_code}")
                            except Exception as del_error:
                                logger.warning(f"删除旧图层时出错: {del_error}")
                            time.sleep(1)
                    except Exception as e:
                        logger.warning(f"检查旧图层时出错（可能不存在）: {e}")
                    
                    publish_result = geoserver.publish_raster(coverage_store_name, layer_name, impact_file_path)
                    logger.info(f"publish_raster 返回结果: {publish_result}")
                    
                    if publish_result:
                        # 等待一下让GeoServer处理
                        time.sleep(3)  # 增加等待时间，确保重命名完成
                        
                        # 验证图层是否存在（先尝试期望的名称）
                        full_layer_name = f"{geoserver.workspace}:{layer_name}"
                        layer_check = geoserver.get_layer_info(full_layer_name)
                        logger.info(f"图层验证结果（期望名称 {layer_name}）: {layer_check is not None}")
                        
                        # 如果期望名称的图层不存在，尝试查找实际创建的图层名称（可能是CoverageStore名称）
                        actual_layer_name = layer_name
                        if not layer_check:
                            logger.info(f"⚠️ 期望图层名称 {layer_name} 不存在，尝试查找实际创建的图层...")
                            # 检查CoverageStore中的Coverage名称
                            try:
                                coverage_list = geoserver._make_request('GET', f'workspaces/{geoserver.workspace}/coveragestores/{coverage_store_name}/coverages.json')
                                if coverage_list and 'coverages' in coverage_list:
                                    coverages = coverage_list['coverages'].get('coverage', [])
                                    if isinstance(coverages, list) and len(coverages) > 0:
                                        coverage_obj = coverages[0]
                                        if isinstance(coverage_obj, dict):
                                            actual_layer_name = coverage_obj.get('name', layer_name)
                                        else:
                                            actual_layer_name = coverage_store_name  # 使用CoverageStore名称
                                    elif isinstance(coverages, dict):
                                        actual_layer_name = coverages.get('name', layer_name)
                                    else:
                                        actual_layer_name = coverage_store_name  # 使用CoverageStore名称
                                    
                                    logger.info(f"找到实际图层名称: {actual_layer_name}")
                                    # 验证实际图层是否存在
                                    full_actual_name = f"{geoserver.workspace}:{actual_layer_name}"
                                    layer_check = geoserver.get_layer_info(full_actual_name)
                                    if layer_check:
                                        logger.info(f"✅ 找到实际创建的图层: {actual_layer_name}")
                                        layer_name = actual_layer_name  # 使用实际图层名称
                                    else:
                                        logger.warning(f"⚠️ 实际图层名称 {actual_layer_name} 也不存在，可能GeoServer尚未完全处理")
                            except Exception as e:
                                logger.warning(f"⚠️ 查找实际图层名称时出错: {e}")
                        
                        if layer_check:
                            # 为图层创建并应用默认样式
                            style_name = f"{layer_name}_style"
                            logger.info(f"为图层 {layer_name} 创建样式: {style_name}")
                            
                            # 从栅格文件读取统计信息，以创建合适的样式
                            # 快速模式：使用默认值域，避免长时间读取栅格数据
                            logger.info(f"快速模式：使用默认值域创建样式（避免长时间读取栅格数据）")
                            min_val, max_val = (0.0, 5.0)
                            
                            # 可选：尝试快速读取统计信息（不阻塞）
                            try:
                                import threading
                                result = [None]
                                def quick_get_stats():
                                    try:
                                        result[0] = geoserver._get_raster_statistics(impact_file_path)
                                    except:
                                        pass
                                
                                thread = threading.Thread(target=quick_get_stats)
                                thread.daemon = True
                                thread.start()
                                thread.join(timeout=3)  # 3秒超时
                                
                                if result[0] and not thread.is_alive():
                                    min_val, max_val = result[0]
                                    logger.info(f"✅ 快速获取到统计信息，更新值域: {min_val} - {max_val}")
                            except:
                                pass
                            
                            logger.info(f"使用栅格值域创建样式: {min_val} - {max_val}")
                            
                            sld_content = geoserver._create_default_raster_sld(min_val, max_val)
                            if geoserver.create_style(style_name, sld_content):
                                logger.info(f"样式 {style_name} 创建成功，开始应用到图层")
                                if geoserver.apply_style_to_layer(layer_name, style_name):
                                    logger.info(f"✅ 样式已成功应用到图层 {layer_name}")
                                else:
                                    logger.warning(f"⚠️ 样式应用到图层失败，但图层已发布")
                            else:
                                logger.warning(f"⚠️ 样式创建失败，但图层已发布")
                            
                            wms_url = f"{geoserver.base_url}/ows?service=WMS&version=1.3.0&request=GetMap&layers={geoserver.workspace}:{layer_name}&format=image/png&transparent=true"
                            
                            if 'impact_layer' not in raster_metadata:
                                raster_metadata['impact_layer'] = {}
                            
                            raster_metadata['impact_layer'].update({
                                'wms_url': wms_url,
                                'published': True
                            })
                            
                            published_layers['impact_layer'] = {
                                'layer_name': layer_name,
                                'wms_url': wms_url
                            }
                            logger.info(f"✅ 影响栅格图层重新发布成功: {layer_name}")
                        else:
                            error_msg = f"图层 {layer_name} 发布后验证失败（图层在GeoServer中不存在，实际图层名称: {actual_layer_name}）"
                            logger.error(f"❌ {error_msg}")
                            error_messages.append(error_msg)
                    else:
                        error_msg = f"影响栅格图层发布失败: {layer_name}（publish_raster返回False）"
                        logger.error(f"❌ {error_msg}")
                        error_messages.append(error_msg)
                else:
                    error_msg = f"影响栅格文件不存在: {impact_file_path}"
                    logger.error(f"❌ {error_msg}")
                    error_messages.append(error_msg)
            else:
                error_msg = "任务没有关联的影响栅格文件"
                logger.warning(f"⚠️ {error_msg}")
                error_messages.append(error_msg)
            
            # 检查是否有成功发布的图层
            if not published_layers or len(published_layers) == 0:
                error_detail = '没有图层成功发布。'
                if error_messages:
                    error_detail += ' 失败原因: ' + '; '.join(error_messages)
                else:
                    error_detail += ' 请检查后端日志和GeoServer状态'
                
                logger.error(f"❌ {error_detail}")
                return Response({
                    'error': error_detail,
                    'error_details': error_messages,
                    'published_layers': {},
                    'updated_metadata': raster_metadata
                }, status=500)
            
            # 更新任务的栅格图层元数据
            task.raster_layers_metadata = raster_metadata
            task.save()
            
            # 更新分析结果中的栅格图层信息
            if task.analysis_results and 'raster_layers' in task.analysis_results:
                for key in published_layers:
                    if key in task.analysis_results['raster_layers']:
                        task.analysis_results['raster_layers'][key].update(published_layers[key])
                task.save()
            
            logger.info(f"✅ 重新发布完成，成功发布 {len(published_layers)} 个图层: {list(published_layers.keys())}")
            return Response({
                'message': f'栅格图层重新发布成功，共发布 {len(published_layers)} 个图层',
                'published_layers': published_layers,
                'updated_metadata': raster_metadata
            })
            
        except Exception as e:
            logger.error(f"重新发布栅格图层失败: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return Response({
                'error': f'重新发布失败: {str(e)}'
            }, status=500)
    
    @action(detail=False, methods=['post'], url_path='upload-ecology-raster', parser_classes=[MultiPartParser, FormParser])
    def upload_ecology_raster(self, request):
        """上传生态指数栅格数据"""
        # 最简化测试版本
        logger.info("=== 收到上传请求 ===")
        
        try:
            logger.info(f"请求方法: {request.method}")
            logger.info(f"Content-Type: {request.content_type}")
            logger.info(f"FILES: {list(request.FILES.keys())}")
            
            if 'file' not in request.FILES:
                logger.warning("未找到上传文件")
                return Response({
                    'success': False,
                    'message': '未找到上传文件'
                }, status=400)
            
            uploaded_file = request.FILES['file']
            file_name = uploaded_file.name
            description = (request.data.get('description') or '').strip()
            logger.info(f"接收到文件: {file_name}, 大小: {uploaded_file.size} bytes")
            
            # 验证文件类型
            if not file_name.lower().endswith(('.tif', '.tiff')):
                return Response({
                    'success': False,
                    'message': '仅支持GeoTIFF格式 (.tif, .tiff)'
                }, status=400)
            
            # 验证文件大小（最大100MB）
            if uploaded_file.size > 1024 * 1024 * 1024:
                return Response({
                    'success': False,
                    'message': '文件大小超过1GB限制'
                }, status=400)
            
            # 保存文件
            import os
            from django.conf import settings
            
            upload_dir = os.path.join(settings.MEDIA_ROOT, 'ecological_projects')
            os.makedirs(upload_dir, exist_ok=True)
            logger.info(f"上传目录: {upload_dir}")
            
            overlay_config = _get_overlay_layer_configs()['ecology_uploaded']
            save_path = overlay_config['paths'][0]
            
            # 保存上传的文件
            logger.info(f"开始保存文件到: {save_path}")
            with open(save_path, 'wb+') as destination:
                for chunk in uploaded_file.chunks():
                    destination.write(chunk)
            
            logger.info(f"✅ 生态栅格文件已保存: {save_path}")
            
            # 发布到GeoServer
            logger.info("🚀 开始发布到GeoServer...")
            try:
                from .geoserver_config import geoserver_manager
                
                logger.info(
                    f"调用publish_raster: coverage_store={overlay_config['store']}, "
                    f"layer={overlay_config['layer_name']}, file={save_path}"
                )
                success = geoserver_manager.publish_raster(
                    coverage_store_name=overlay_config['store'],
                    layer_name=overlay_config['layer_name'],
                    file_path=save_path,
                    style_type='ecology_rsei'
                )
                logger.info(f"publish_raster返回值: {success}")
                
                if success:
                    logger.info("✅ GeoServer发布成功")
                    metadata = _update_overlay_metadata(
                        'ecology_uploaded',
                        description=description,
                        file_name=file_name,
                        layer_name=overlay_config['layer_name'],
                        source_type='uploaded_raster',
                        source_image_id='',
                        source_image_name='',
                        source_result_id='',
                        source_result_created_at=None,
                        service_mode='geoserver',
                        geoserver_published=True,
                    )
                    return Response({
                        'success': True,
                        'message': '生态指数栅格上传成功并已发布到GeoServer',
                        'file_name': file_name,
                        'layer_name': overlay_config['layer_name'],
                        'description': description,
                        'metadata': metadata,
                    })
                else:
                    logger.warning("⚠️ GeoServer发布失败")
                    metadata = _update_overlay_metadata(
                        'ecology_uploaded',
                        description=description,
                        file_name=file_name,
                        layer_name=overlay_config['layer_name'],
                        source_type='uploaded_raster',
                        source_image_id='',
                        source_image_name='',
                        source_result_id='',
                        source_result_created_at=None,
                        service_mode='local',
                        geoserver_published=False,
                    )
                    return Response({
                        'success': True,
                        'message': '生态指数栅格已上传，GeoServer未连接，当前使用本地栅格覆盖图显示。',
                        'warning': 'GeoServer发布失败，已启用本地覆盖图兜底。',
                        'file_name': file_name,
                        'save_path': save_path,
                        'metadata': metadata,
                    })
            except Exception as geo_error:
                logger.error(f"GeoServer发布异常: {str(geo_error)}")
                import traceback
                logger.error(traceback.format_exc())
                metadata = _update_overlay_metadata(
                    'ecology_uploaded',
                    description=description,
                    file_name=file_name,
                    layer_name=overlay_config['layer_name'],
                    source_type='uploaded_raster',
                    source_image_id='',
                    source_image_name='',
                    source_result_id='',
                    source_result_created_at=None,
                    service_mode='local',
                    geoserver_published=False,
                )
                return Response({
                    'success': True,
                    'message': f'生态指数栅格已上传，GeoServer发布失败，当前使用本地栅格覆盖图显示。',
                    'warning': str(geo_error),
                    'file_name': file_name,
                    'save_path': save_path,
                    'metadata': metadata,
                })
                
        except Exception as e:
            logger.error(f"❌ 上传生态栅格失败: {str(e)}")
            import traceback
            error_trace = traceback.format_exc()
            logger.error(f"错误堆栈:\n{error_trace}")
            
            # 返回更详细的错误信息
            error_message = str(e)
            if hasattr(e, '__cause__') and e.__cause__:
                error_message = f"{error_message} (原因: {str(e.__cause__)})"
            
            return Response({
                'success': False,
                'message': f'上传失败: {error_message}',
                'error_detail': error_trace[:500] if len(error_trace) > 500 else error_trace  # 限制长度
            }, status=500)
    
    @action(detail=False, methods=['post'], url_path='upload-economy-vector', parser_classes=[MultiPartParser, FormParser])
    def upload_economy_vector(self, request):
        """上传经济数据矢量，支持同一ZIP内包含点/线/面Shapefile。"""
        try:
            if 'file' not in request.FILES:
                return Response({
                    'success': False,
                    'message': '未找到上传文件'
                }, status=400)
            
            uploaded_file = request.FILES['file']
            file_name = uploaded_file.name
            description = (request.data.get('description') or '').strip()
            
            # 验证文件类型
            if not file_name.lower().endswith('.zip'):
                return Response({
                    'success': False,
                    'message': '仅支持Shapefile压缩包 (.zip)'
                }, status=400)
            
            # 验证文件大小
            if uploaded_file.size > 1024 * 1024 * 1024:
                return Response({
                    'success': False,
                    'message': '文件大小超过1GB限制'
                }, status=400)
            return _overlay_business_vector_upload_response(uploaded_file, description, 'economy')
                
        except Exception as e:
            logger.error(f"上传经济矢量失败: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return Response({
                'success': False,
                'message': f'上传失败: {str(e)}'
            }, status=500)
    
    @action(detail=False, methods=['post'], url_path='upload-engineering-vector', parser_classes=[MultiPartParser, FormParser])
    def upload_engineering_vector(self, request):
        """上传工程项目矢量，支持同一ZIP内包含点/线/面Shapefile。"""
        try:
            if 'file' not in request.FILES:
                return Response({
                    'success': False,
                    'message': '未找到上传文件'
                }, status=400)
            
            uploaded_file = request.FILES['file']
            file_name = uploaded_file.name
            description = (request.data.get('description') or '').strip()
            
            # 验证文件类型
            if not file_name.lower().endswith('.zip'):
                return Response({
                    'success': False,
                    'message': '仅支持Shapefile压缩包 (.zip)'
                }, status=400)
            
            # 验证文件大小
            if uploaded_file.size > 1024 * 1024 * 1024:
                return Response({
                    'success': False,
                    'message': '文件大小超过1GB限制'
                }, status=400)
            return _overlay_business_vector_upload_response(uploaded_file, description, 'engineering')
                
        except Exception as e:
            logger.error(f"上传工程矢量失败: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return Response({
                'success': False,
                'message': f'上传失败: {str(e)}'
            }, status=500)
