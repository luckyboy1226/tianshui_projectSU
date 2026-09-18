from urllib.parse import parse_qsl, urlsplit

from rest_framework import serializers
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
from users.serializers import UserSerializer


class RemoteSensingImageSerializer(serializers.ModelSerializer):
    """遥感影像序列化器"""
    uploaded_by = UserSerializer(read_only=True)
    file_size_mb = serializers.SerializerMethodField()
    processing_status_display = serializers.CharField(source='get_processing_status_display', read_only=True)
    
    class Meta:
        model = RemoteSensingImage
        fields = [
            'id', 'name', 'description', 'image_type', 'file_path', 'thumbnail',
            'center_lat', 'center_lon', 'acquisition_date', 'processing_date',
            'resolution', 'bands_count', 'file_size', 'file_size_mb',
            'is_processed', 'processing_status', 'processing_status_display',
            'uploaded_by'
        ]
        read_only_fields = ['id', 'processing_date', 'file_size', 'uploaded_by']
    
    def get_file_size_mb(self, obj):
        """获取文件大小（MB）"""
        if obj.file_size:
            return round(obj.file_size / (1024 * 1024), 2)
        return None


class EcologicalIndexSerializer(serializers.ModelSerializer):
    """生态指数序列化器"""
    remote_sensing_image = RemoteSensingImageSerializer(read_only=True)
    index_type_display = serializers.CharField(source='get_index_type_display', read_only=True)
    
    class Meta:
        model = EcologicalIndex
        fields = [
            'id', 'remote_sensing_image', 'index_type', 'index_type_display',
            'result_file', 'visualization_file', 'min_value', 'max_value',
            'mean_value', 'std_value', 'excellent_area', 'good_area',
            'moderate_area', 'poor_area', 'bad_area', 'processing_time',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class RSEIResultSerializer(serializers.ModelSerializer):
    """RSEI结果序列化器"""
    remote_sensing_image = RemoteSensingImageSerializer(read_only=True)
    greenness = EcologicalIndexSerializer(read_only=True)
    wetness = EcologicalIndexSerializer(read_only=True)
    dryness = EcologicalIndexSerializer(read_only=True)
    heat = EcologicalIndexSerializer(read_only=True)
    rsei_result = EcologicalIndexSerializer(read_only=True)
    
    class Meta:
        model = RSEIResult
        fields = [
            'id', 'remote_sensing_image', 'greenness', 'wetness', 'dryness', 'heat',
            'rsei_result', 'pc1_variance', 'pc2_variance', 'pc3_variance', 'pc4_variance',
            'greenness_weight', 'wetness_weight', 'dryness_weight', 'heat_weight',
            'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class ProcessingTaskSerializer(serializers.ModelSerializer):
    """处理任务序列化器"""
    remote_sensing_image = RemoteSensingImageSerializer(read_only=True)
    remote_sensing_image_id = serializers.UUIDField(write_only=True)  # 添加ID字段用于创建
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = ProcessingTask
        fields = [
            'id', 'remote_sensing_image', 'remote_sensing_image_id', 'task_type', 'status', 'status_display',
            'progress', 'current_step', 'error_message',
            'priority', 'queue_name', 'celery_task_id', 'dispatch_status', 'dispatch_attempts',
            'dispatching_at', 'last_dispatch_error',
            'created_at', 'started_at', 'completed_at'
        ]
        read_only_fields = ['id', 'celery_task_id', 'dispatch_status', 'dispatch_attempts', 'dispatching_at', 'last_dispatch_error', 'created_at', 'started_at', 'completed_at']
        
    def create(self, validated_data):
        """处理remote_sensing_image_id字段"""
        remote_sensing_image_id = validated_data.pop('remote_sensing_image_id')
        remote_sensing_image = RemoteSensingImage.objects.get(id=remote_sensing_image_id)
        return ProcessingTask.objects.create(
            remote_sensing_image=remote_sensing_image,
            **validated_data
        )


class RemoteSensingImageUploadSerializer(serializers.ModelSerializer):
    """遥感影像上传序列化器"""
    file = serializers.FileField(write_only=True)  # 添加file字段用于文件上传
    
    class Meta:
        model = RemoteSensingImage
        fields = ['id', 'name', 'description', 'image_type', 'file', 'acquisition_date', 'center_lat', 'center_lon']
        read_only_fields = ['id']  # id字段为只读，由Django自动生成
    
    def create(self, validated_data):
        """重写create方法，将file字段映射到file_path"""
        file_obj = validated_data.pop('file')
        validated_data['file_path'] = file_obj
        return super().create(validated_data)
    
    def validate_file(self, value):
        """验证文件格式"""
        if not value:
            raise serializers.ValidationError("文件不能为空")
            
        allowed_extensions = ['.tif', '.tiff', '.img', '.hdf', '.nc', '.zip', '.jpg', '.jpeg', '.png']
        file_extension = value.name.lower()
        
        if not any(file_extension.endswith(ext) for ext in allowed_extensions):
            raise serializers.ValidationError(
                f"不支持的文件格式。支持的格式: {', '.join(allowed_extensions)}"
            )
        
        # 检查文件大小（大栅格由后端落盘后分块处理）
        max_size = 20 * 1024 * 1024 * 1024
        if value.size > max_size:
            raise serializers.ValidationError("文件大小不能超过20GB")
        
        return value
    
    def validate(self, data):
        """整体验证"""
        # 确保必需字段存在
        required_fields = ['name', 'image_type', 'acquisition_date', 'center_lat', 'center_lon']
        for field in required_fields:
            if not data.get(field):
                raise serializers.ValidationError(f"字段 {field} 是必需的")
        
        # 验证坐标范围
        if data.get('center_lat') and (data['center_lat'] < -90 or data['center_lat'] > 90):
            raise serializers.ValidationError("纬度必须在-90到90之间")
        
        if data.get('center_lon') and (data['center_lon'] < -180 or data['center_lon'] > 180):
            raise serializers.ValidationError("经度必须在-180到180之间")
        
        return data


class EcologicalIndexCalculationSerializer(serializers.Serializer):
    """生态指数计算请求序列化器"""
    remote_sensing_image_id = serializers.UUIDField()
    indices = serializers.ListField(
        child=serializers.ChoiceField(choices=EcologicalIndex.INDEX_TYPE_CHOICES),
        min_length=1
    )
    
    def validate_remote_sensing_image_id(self, value):
        """验证遥感影像是否存在"""
        try:
            RemoteSensingImage.objects.get(id=value)
        except RemoteSensingImage.DoesNotExist:
            raise serializers.ValidationError("指定的遥感影像不存在")
        return value


class RSEICalculationSerializer(serializers.Serializer):
    """RSEI计算请求序列化器"""
    remote_sensing_image_id = serializers.UUIDField()
    
    def validate_remote_sensing_image_id(self, value):
        """验证遥感影像是否存在"""
        try:
            RemoteSensingImage.objects.get(id=value)
        except RemoteSensingImage.DoesNotExist:
            raise serializers.ValidationError("指定的遥感影像不存在")
        return value


class EcologicalIndexStatisticsSerializer(serializers.Serializer):
    """生态指数统计信息序列化器"""
    index_type = serializers.CharField()
    total_area = serializers.FloatField()
    excellent_percentage = serializers.FloatField()
    good_percentage = serializers.FloatField()
    moderate_percentage = serializers.FloatField()
    poor_percentage = serializers.FloatField()
    bad_percentage = serializers.FloatField()
    mean_value = serializers.FloatField()
    std_value = serializers.FloatField() 


class CitizenFeedbackSerializer(serializers.ModelSerializer):
    """民众意见反馈序列化器"""
    created_by = UserSerializer(read_only=True)
    category_display = serializers.CharField(source='get_category_display', read_only=True)

    class Meta:
        model = CitizenFeedback
        fields = ['id', 'category', 'category_display', 'title', 'content', 'contact', 'created_by', 'created_at']
        read_only_fields = ['id', 'created_by', 'created_at']


class ClimateDataFileSerializer(serializers.ModelSerializer):
    """气候数据文件序列化器"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    uploaded_by_username = serializers.SerializerMethodField()
    
    def get_uploaded_by_username(self, obj):
        """安全获取上传用户名"""
        return obj.uploaded_by.username if obj.uploaded_by else None
    
    class Meta:
        model = ClimateDataFile
        fields = [
            'id', 'name', 'file', 'file_type', 'description', 'status', 'status_display',
            'uploaded_by', 'uploaded_by_username', 'created_at', 'processed_at', 'error_message'
        ]
        read_only_fields = ['id', 'uploaded_by', 'created_at', 'processed_at']


class ClimateDataFileUploadSerializer(serializers.ModelSerializer):
    """气候数据文件上传序列化器"""
    
    class Meta:
        model = ClimateDataFile
        fields = ['name', 'file', 'description']
    
    def validate_file(self, value):
        """验证文件类型"""
        lower_name = value.name.lower()
        if lower_name.endswith(('.shp', '.dbf', '.shx', '.prj', '.cpg', '.sbn', '.sbx')):
            raise serializers.ValidationError(
                "请将完整 Shapefile 组件打包为一个 ZIP 后上传，系统会自动读取属性表进行气候统计分析"
            )
        if not lower_name.endswith(('.csv', '.xlsx', '.xls', '.tif', '.tiff', '.zip')):
            raise serializers.ValidationError(
                "支持 CSV、Excel、GeoTIFF 直接上传；ADF 或完整 Shapefile 组件请打包为 ZIP 后上传"
            )
        return value


class ClimateAnalysisResultSerializer(serializers.ModelSerializer):
    """气候分析结果序列化器"""
    data_file_name = serializers.CharField(source='data_file.name', read_only=True)
    processing_task = serializers.UUIDField(source='processing_task_id', read_only=True)
    
    class Meta:
        model = ClimateAnalysisResult
        fields = [
            'id', 'data_file', 'data_file_name', 'processing_task', 'analysis_type',
            'temperature_avg', 'temperature_max', 'temperature_min', 'temperature_std',
            'precipitation_avg', 'precipitation_max', 'precipitation_min', 'precipitation_std',
            'humidity_avg', 'humidity_max', 'humidity_min', 'humidity_std',
            'wind_speed_avg', 'wind_speed_max', 'wind_speed_min', 'wind_speed_std',
            'chart_data', 'report_file', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class BusinessLayerSerializer(serializers.ModelSerializer):
    """业务图层序列化器"""
    uploaded_by_username = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    layer_type_display = serializers.CharField(source='get_layer_type_display', read_only=True)
    source_format_display = serializers.CharField(source='get_source_format_display', read_only=True)
    recent_logs = serializers.SerializerMethodField()

    class Meta:
        model = BusinessLayer
        fields = [
            'id', 'name', 'description', 'layer_type', 'layer_type_display',
            'source_format', 'source_format_display', 'file', 'status', 'status_display',
            'service_url', 'service_type_name', 'service_srs', 'style_name', 'style_config', 'sld_content',
            'service_health_status', 'service_health_message', 'service_checked_at',
            'geoserver_workspace', 'geoserver_store_name', 'geoserver_layer_name',
            'wms_url', 'wfs_url', 'wcs_url', 'metadata', 'error_message',
            'uploaded_by', 'uploaded_by_username', 'created_at', 'updated_at', 'published_at', 'recent_logs'
        ]
        read_only_fields = [
            'id', 'layer_type', 'source_format', 'status',
            'service_url', 'service_type_name', 'service_srs', 'style_name', 'style_config', 'sld_content',
            'service_health_status', 'service_health_message', 'service_checked_at',
            'geoserver_workspace', 'geoserver_store_name', 'geoserver_layer_name',
            'wms_url', 'wfs_url', 'wcs_url', 'metadata', 'error_message',
            'uploaded_by', 'created_at', 'updated_at', 'published_at', 'recent_logs'
        ]

    def get_uploaded_by_username(self, obj):
        return obj.uploaded_by.username if obj.uploaded_by else None

    def get_recent_logs(self, obj):
        logs = getattr(obj, 'audit_logs', None)
        if logs is None:
            logs = obj.audit_logs.all()
        recent = list(logs.all()[:5])
        return BusinessLayerAuditLogSerializer(recent, many=True).data


class BusinessLayerUploadSerializer(serializers.ModelSerializer):
    """业务图层上传序列化器"""

    class Meta:
        model = BusinessLayer
        fields = ['id', 'name', 'description', 'file']
        read_only_fields = ['id']

    def validate_file(self, value):
        lower_name = value.name.lower()
        allowed = ('.zip', '.kml', '.tif', '.tiff')
        if not lower_name.endswith(allowed):
            raise serializers.ValidationError('只支持 Shapefile ZIP、KML 或 GeoTIFF(.tif/.tiff)')
        max_size = 20 * 1024 * 1024 * 1024
        if value.size > max_size:
            raise serializers.ValidationError('文件大小不能超过20GB')
        return value

    def validate(self, data):
        uploaded_file = data.get('file')
        lower_name = uploaded_file.name.lower() if uploaded_file else ''
        if lower_name.endswith('.zip'):
            data['layer_type'] = 'vector'
            data['source_format'] = 'shapefile'
        elif lower_name.endswith('.kml'):
            data['layer_type'] = 'vector'
            data['source_format'] = 'kml'
        elif lower_name.endswith(('.tif', '.tiff')):
            data['layer_type'] = 'raster'
            data['source_format'] = 'geotiff'
        return data


class BusinessLayerServiceSerializer(serializers.ModelSerializer):
    """外部标准服务图层接入序列化器"""

    service_type_name = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    service_srs = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    style_name = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    class Meta:
        model = BusinessLayer
        fields = [
            'id', 'name', 'description', 'layer_type', 'source_format',
            'service_url', 'service_type_name', 'service_srs', 'style_name'
        ]
        read_only_fields = ['id']

    def validate(self, data):
        source_format = data.get('source_format')
        layer_type = data.get('layer_type')
        service_url = (data.get('service_url') or '').strip()
        service_type_name = (data.get('service_type_name') or '').strip()

        if source_format not in ['wms', 'wfs', 'wcs']:
            raise serializers.ValidationError('外部服务图层仅支持 WMS/WFS/WCS')
        if not service_url:
            raise serializers.ValidationError('请填写标准服务地址')
        if layer_type not in ['vector', 'raster']:
            raise serializers.ValidationError('请指定图层类型')

        if source_format == 'wfs' and layer_type != 'vector':
            raise serializers.ValidationError('WFS 只能对应矢量图层')
        if source_format == 'wcs' and layer_type != 'raster':
            raise serializers.ValidationError('WCS 只能对应栅格图层')

        parsed = urlsplit(service_url)
        params = {key.lower(): value for key, value in parse_qsl(parsed.query, keep_blank_values=True)}
        declared_service = (params.get('service') or '').lower()
        if declared_service and declared_service != source_format:
            raise serializers.ValidationError(f'服务地址中声明的是 {declared_service.upper()}，与当前选择不一致')

        if source_format == 'wms':
            layers = params.get('layers') or service_type_name
            if not layers:
                raise serializers.ValidationError('WMS 服务请提供图层名称，或在地址中带上 layers 参数')
        elif source_format == 'wfs':
            type_name = params.get('typename') or params.get('typenames') or service_type_name
            if not type_name:
                raise serializers.ValidationError('WFS 服务请提供 typeName，或在地址中带上 typeName 参数')

        return data


class BusinessLayerStyleSerializer(serializers.Serializer):
    style_name = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    fill_color = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    stroke_color = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    stroke_width = serializers.FloatField(required=False, min_value=0)
    fill_opacity = serializers.FloatField(required=False, min_value=0, max_value=1)
    classification_field = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    color_scheme = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    raster_color_ramp = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    raster_opacity = serializers.FloatField(required=False, min_value=0, max_value=1)
    nodata = serializers.FloatField(required=False, allow_null=True)
    sld_content = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate(self, data):
        fill_color = data.get('fill_color')
        stroke_color = data.get('stroke_color')
        for color_value in [fill_color, stroke_color]:
            if color_value and not color_value.startswith('#'):
                raise serializers.ValidationError('颜色值请使用 #RRGGBB 格式')
        return data


class BusinessLayerAuditLogSerializer(serializers.ModelSerializer):
    action_display = serializers.CharField(source='get_action_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = BusinessLayerAuditLog
        fields = [
            'id', 'action', 'action_display', 'status', 'status_display',
            'operator', 'operator_name', 'message', 'details', 'created_at'
        ]
        read_only_fields = fields


class ClimateAnalysisRequestSerializer(serializers.Serializer):
    """气候分析请求序列化器"""
    file_id = serializers.UUIDField()
    analysis_type = serializers.ChoiceField(
        choices=[
            ('comprehensive', '综合分析'),
            ('temperature', '温度分析'),
            ('precipitation', '降水分析'),
            ('humidity', '湿度分析'),
            ('wind', '风速分析'),
        ],
        default='comprehensive'
    )


class EcologicalIndexFileSerializer(serializers.ModelSerializer):
    """生态指数文件序列化器"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    uploaded_by_username = serializers.SerializerMethodField()
    
    def get_uploaded_by_username(self, obj):
        """安全获取上传用户名"""
        return obj.uploaded_by.username if obj.uploaded_by else None

    class Meta:
        model = EcologicalIndexFile
        fields = [
            'id', 'filename', 'file', 'description', 'status', 'status_display',
            'indices_data', 'timestamp', 'uploaded_by', 'uploaded_by_username',
            'created_at', 'processed_at', 'error_message'
        ]
        read_only_fields = ['id', 'uploaded_by', 'created_at', 'processed_at']


class EcologicalIndexFileUploadSerializer(serializers.ModelSerializer):
    """生态指数文件上传序列化器"""

    class Meta:
        model = EcologicalIndexFile
        fields = ['filename', 'file', 'description']

    def validate_file(self, value):
        """验证文件类型"""
        if not value.name.lower().endswith('.json'):
            raise serializers.ValidationError("只支持JSON文件格式")
        return value


class EcologicalProjectFileSerializer(serializers.ModelSerializer):
    """生态修复工程文件序列化器"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    uploaded_by_username = serializers.SerializerMethodField()
    
    def get_uploaded_by_username(self, obj):
        """安全获取上传用户名"""
        return obj.uploaded_by.username if obj.uploaded_by else None

    class Meta:
        model = EcologicalProjectFile
        fields = [
            'id', 'filename', 'file', 'description', 'status', 'status_display',
            'geojson_data', 'uploaded_by', 'uploaded_by_username',
            'created_at', 'processed_at', 'error_message'
        ]
        read_only_fields = ['id', 'uploaded_by', 'created_at', 'processed_at']


class EcologicalProjectFileUploadSerializer(serializers.ModelSerializer):
    """生态修复工程文件上传序列化器"""

    class Meta:
        model = EcologicalProjectFile
        fields = ['filename', 'file', 'description']

    def validate_file(self, value):
        """验证文件类型"""
        if not value.name.lower().endswith('.json'):
            raise serializers.ValidationError("只支持JSON文件格式")
        return value


class OverlayAnalysisTaskSerializer(serializers.ModelSerializer):
    """叠加分析任务序列化器"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    risk_level_display = serializers.CharField(source='get_overall_risk_level_display', read_only=True)
    ecological_index_file_name = serializers.CharField(source='ecological_index_file.filename', read_only=True)
    ecological_project_file_name = serializers.CharField(source='ecological_project_file.filename', read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = OverlayAnalysisTask
        fields = [
            'id', 'name', 'description', 'ecological_index_file', 'ecological_project_file',
            'ecological_index_file_name', 'ecological_project_file_name',
            'status', 'status_display', 'progress', 'current_step',
            'analysis_results', 'overall_risk_level', 'risk_level_display',
            'error_message', 'created_by', 'created_by_username',
            'created_at', 'started_at', 'completed_at'
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'started_at', 'completed_at']


class OverlayAnalysisTaskCreateSerializer(serializers.ModelSerializer):
    """叠加分析任务创建序列化器"""

    class Meta:
        model = OverlayAnalysisTask
        fields = ['id', 'name', 'description', 'ecological_index_file', 'ecological_project_file', 'status', 'progress']
        read_only_fields = ['id', 'status', 'progress']

    def validate(self, data):
        """验证关联文件状态"""
        ecological_index_file = data.get('ecological_index_file')
        ecological_project_file = data.get('ecological_project_file')

        if ecological_index_file and ecological_index_file.status not in ['uploaded', 'completed']:
            raise serializers.ValidationError("生态指数文件必须上传完成后才能进行叠加分析")

        if ecological_project_file and ecological_project_file.status not in ['uploaded', 'completed']:
            raise serializers.ValidationError("生态修复工程文件必须上传完成后才能进行叠加分析")

        return data
