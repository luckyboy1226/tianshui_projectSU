from django.db import models
from users.models import User
import uuid


class RemoteSensingImage(models.Model):
    """遥感影像数据模型"""
    IMAGE_TYPE_CHOICES = [
        ('landsat8', 'Landsat 8'),
        ('landsat9', 'Landsat 9'),
        ('sentinel2', 'Sentinel-2'),
        ('custom', '自定义'),
    ]
    
    PROCESSING_STATUS_CHOICES = [
        ('pending', '待处理'),
        ('processing', '处理中'),
        ('completed', '已完成'),
        ('failed', '处理失败'),
        ('cancelled', '已取消'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, verbose_name='影像名称')
    description = models.TextField(blank=True, null=True, verbose_name='描述')
    image_type = models.CharField(max_length=20, choices=IMAGE_TYPE_CHOICES, verbose_name='影像类型')
    file_path = models.FileField(upload_to='remote_sensing/', verbose_name='影像文件')
    thumbnail = models.ImageField(upload_to='thumbnails/', blank=True, null=True, verbose_name='缩略图')
    
    # 地理信息（简化版本，不使用GIS字段）
    center_lat = models.FloatField(verbose_name='中心纬度')
    center_lon = models.FloatField(verbose_name='中心经度')
    
    # 时间信息
    acquisition_date = models.DateField(verbose_name='获取日期')
    processing_date = models.DateTimeField(auto_now_add=True, verbose_name='处理时间')
    
    # 元数据
    resolution = models.FloatField(blank=True, null=True, verbose_name='分辨率(米)')
    bands_count = models.IntegerField(blank=True, null=True, verbose_name='波段数')
    file_size = models.BigIntegerField(blank=True, null=True, verbose_name='文件大小(字节)')
    
    # 状态
    is_processed = models.BooleanField(default=False, verbose_name='是否已处理')
    processing_status = models.CharField(max_length=20, choices=PROCESSING_STATUS_CHOICES, default='pending', verbose_name='处理状态')
    
    # 用户信息
    uploaded_by = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, verbose_name='上传用户', default=None)
    
    class Meta:
        verbose_name = '遥感影像'
        verbose_name_plural = '遥感影像'
        db_table = 'remote_sensing_images'
        ordering = ['-acquisition_date']
    
    def __str__(self):
        return f"{self.name} ({self.acquisition_date})"


class EcologicalIndex(models.Model):
    """生态指数模型"""
    INDEX_TYPE_CHOICES = [
        ('ndvi', 'NDVI - 归一化植被指数'),
        ('ndwi', 'NDWI - 归一化水体指数'),
        ('ndbi', 'NDBI - 归一化建筑指数'),
        ('ndsi', 'NDSI - 归一化积雪指数'),
        ('rsei', 'RSEI - 遥感生态指数'),
        ('wetness', '湿度指数'),
        ('dryness', '干度指数'),
        ('heat', '热度指数'),
        ('greenness', '绿度指数'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    remote_sensing_image = models.ForeignKey(RemoteSensingImage, on_delete=models.CASCADE, verbose_name='遥感影像')
    index_type = models.CharField(max_length=20, choices=INDEX_TYPE_CHOICES, verbose_name='指数类型')
    
    # 计算结果
    result_file = models.FileField(upload_to='ecological_indices/', verbose_name='结果文件')
    visualization_file = models.ImageField(upload_to='visualizations/', verbose_name='可视化图片')
    
    # 统计信息
    min_value = models.FloatField(blank=True, null=True, verbose_name='最小值')
    max_value = models.FloatField(blank=True, null=True, verbose_name='最大值')
    mean_value = models.FloatField(blank=True, null=True, verbose_name='平均值')
    std_value = models.FloatField(blank=True, null=True, verbose_name='标准差')
    
    # 分类统计
    excellent_area = models.FloatField(blank=True, null=True, verbose_name='优秀面积(km²)')
    good_area = models.FloatField(blank=True, null=True, verbose_name='良好面积(km²)')
    moderate_area = models.FloatField(blank=True, null=True, verbose_name='中等面积(km²)')
    poor_area = models.FloatField(blank=True, null=True, verbose_name='较差面积(km²)')
    bad_area = models.FloatField(blank=True, null=True, verbose_name='差面积(km²)')
    
    # 用户信息
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='创建用户')
    
    # 处理信息
    processing_time = models.FloatField(blank=True, null=True, verbose_name='处理时间(秒)')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    
    class Meta:
        verbose_name = '生态指数'
        verbose_name_plural = '生态指数'
        db_table = 'ecological_indices'
        unique_together = ['remote_sensing_image', 'index_type']
    
    def __str__(self):
        return f"{self.remote_sensing_image.name} - {self.get_index_type_display()}"


class RSEIResult(models.Model):
    """RSEI综合生态指数结果模型"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    remote_sensing_image = models.ForeignKey(RemoteSensingImage, on_delete=models.CASCADE, verbose_name='遥感影像')
    
    # RSEI各分量
    greenness = models.ForeignKey(EcologicalIndex, on_delete=models.CASCADE, related_name='rsei_greenness', verbose_name='绿度指数')
    wetness = models.ForeignKey(EcologicalIndex, on_delete=models.CASCADE, related_name='rsei_wetness', verbose_name='湿度指数')
    dryness = models.ForeignKey(EcologicalIndex, on_delete=models.CASCADE, related_name='rsei_dryness', verbose_name='干度指数')
    heat = models.ForeignKey(EcologicalIndex, on_delete=models.CASCADE, related_name='rsei_heat', verbose_name='热度指数')
    
    # RSEI结果
    rsei_result = models.ForeignKey(EcologicalIndex, on_delete=models.CASCADE, related_name='rsei_final', verbose_name='RSEI结果')
    
    # 主成分分析结果
    pc1_variance = models.FloatField(verbose_name='第一主成分方差贡献率')
    pc2_variance = models.FloatField(verbose_name='第二主成分方差贡献率')
    pc3_variance = models.FloatField(verbose_name='第三主成分方差贡献率')
    pc4_variance = models.FloatField(verbose_name='第四主成分方差贡献率')
    
    # 权重
    greenness_weight = models.FloatField(verbose_name='绿度权重')
    wetness_weight = models.FloatField(verbose_name='湿度权重')
    dryness_weight = models.FloatField(verbose_name='干度权重')
    heat_weight = models.FloatField(verbose_name='热度权重')
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    
    class Meta:
        verbose_name = 'RSEI结果'
        verbose_name_plural = 'RSEI结果'
        db_table = 'rsei_results'
    
    def __str__(self):
        return f"RSEI - {self.remote_sensing_image.name}"


class ProcessingTask(models.Model):
    """处理任务模型"""
    TASK_STATUS_CHOICES = [
        ('pending', '等待中'),
        ('retrying', '恢复重试中'),
        ('processing', '处理中'),
        ('completed', '已完成'),
        ('failed', '失败'),
        ('cancelled', '已取消'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    remote_sensing_image = models.ForeignKey(RemoteSensingImage, on_delete=models.CASCADE, null=True, blank=True, verbose_name='遥感影像')
    task_type = models.CharField(max_length=50, verbose_name='任务类型')
    status = models.CharField(max_length=20, choices=TASK_STATUS_CHOICES, default='pending', verbose_name='任务状态')

    # 高并发提交控制。request_fingerprint 用于审计；active_fingerprint 只在任务未结束时
    # 保持唯一，作为数据库级 single-flight 锁，避免同一影像被重复计算。
    idempotency_key = models.CharField(max_length=128, null=True, blank=True, unique=True, verbose_name='幂等请求键')
    request_fingerprint = models.CharField(max_length=64, blank=True, default='', verbose_name='请求指纹')
    request_payload = models.JSONField(default=dict, blank=True, verbose_name='任务请求参数')
    active_fingerprint = models.CharField(max_length=64, null=True, blank=True, unique=True, verbose_name='活跃任务指纹')
    priority = models.CharField(
        max_length=10,
        choices=[('high', '高'), ('normal', '普通'), ('low', '低')],
        default='normal',
        verbose_name='任务优先级',
    )
    queue_name = models.CharField(max_length=32, default='geo.default', verbose_name='队列名称')
    celery_task_id = models.CharField(max_length=255, blank=True, default='', verbose_name='Celery任务ID')
    dispatch_status = models.CharField(
        max_length=20,
        choices=[('pending', '待投递'), ('dispatching', '投递中'), ('dispatched', '已投递'), ('failed', '投递失败')],
        default='pending',
        verbose_name='投递状态',
    )
    dispatch_attempts = models.PositiveIntegerField(default=0, verbose_name='投递尝试次数')
    dispatching_at = models.DateTimeField(blank=True, null=True, verbose_name='最近投递认领时间')
    last_dispatch_error = models.TextField(blank=True, default='', verbose_name='最近投递错误')
    worker_identifier = models.CharField(max_length=255, blank=True, default='', verbose_name='执行Worker标识')
    last_heartbeat_at = models.DateTimeField(blank=True, null=True, verbose_name='最近执行心跳')
    lease_expires_at = models.DateTimeField(blank=True, null=True, verbose_name='执行租约到期')
    attempt_count = models.PositiveIntegerField(default=0, verbose_name='执行尝试次数')
    retry_count = models.PositiveIntegerField(default=0, verbose_name='恢复重试次数')
    max_retry_count = models.PositiveIntegerField(default=2, verbose_name='最大恢复重试次数')
    failed_at = models.DateTimeField(blank=True, null=True, verbose_name='失败时间')
    failure_code = models.CharField(max_length=64, blank=True, default='', verbose_name='失败代码')
    recovery_action = models.CharField(max_length=128, blank=True, default='', verbose_name='最近恢复动作')
    
    # 进度信息
    progress = models.IntegerField(default=0, verbose_name='进度百分比')
    current_step = models.CharField(max_length=100, blank=True, null=True, verbose_name='当前步骤')
    
    # 错误信息
    error_message = models.TextField(blank=True, null=True, verbose_name='错误信息')
    
    # 用户信息
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='创建用户')
    
    # 时间信息
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    started_at = models.DateTimeField(blank=True, null=True, verbose_name='开始时间')
    completed_at = models.DateTimeField(blank=True, null=True, verbose_name='完成时间')
    
    class Meta:
        verbose_name = '处理任务'
        verbose_name_plural = '处理任务'
        db_table = 'processing_tasks'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'priority', 'created_at'], name='processing_task_queue_idx'),
            models.Index(fields=['dispatch_status', 'created_at'], name='processing_task_dispatch_idx'),
            models.Index(fields=['status', 'lease_expires_at'], name='processing_task_lease_idx'),
        ]
    
    def __str__(self):
        image_name = self.remote_sensing_image.name if self.remote_sensing_image else '无关联影像'
        return f"{self.task_type} - {image_name} ({self.get_status_display()})"


class CitizenFeedback(models.Model):
    """民众意见反馈模型"""
    CATEGORY_CHOICES = [
        ('suggestion', '功能建议'),
        ('bug', '问题报告'),
        ('data_issue', '数据纠错'),
        ('other', '其他'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, verbose_name='反馈类型')
    title = models.CharField(max_length=80, verbose_name='标题')
    content = models.TextField(verbose_name='详细描述')
    contact = models.CharField(max_length=120, blank=True, null=True, verbose_name='联系方式')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='提交用户')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='提交时间')

    class Meta:
        verbose_name = '民众意见反馈'
        verbose_name_plural = '民众意见反馈'
        db_table = 'citizen_feedbacks'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_category_display()} - {self.title[:20]}"


class ClimateDataFile(models.Model):
    """气候数据文件模型"""
    STATUS_CHOICES = [
        ('uploaded', '已上传'),
        ('processing', '处理中'),
        ('completed', '完成'),
        ('failed', '失败'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, verbose_name='文件名')
    file = models.FileField(upload_to='climate_data/', verbose_name='文件')
    file_type = models.CharField(
        max_length=10,
        choices=[
            ('csv', 'CSV'),
            ('xlsx', 'Excel'),
            ('xls', 'Excel 97-2003'),
            ('tif', 'GeoTIFF'),
            ('tiff', 'GeoTIFF'),
            ('zip', 'ZIP'),
        ],
        default='zip',
        verbose_name='文件类型'
    )
    description = models.TextField(blank=True, null=True, verbose_name='描述')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='uploaded', verbose_name='状态')
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='上传用户')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    processed_at = models.DateTimeField(null=True, blank=True, verbose_name='处理完成时间')
    error_message = models.TextField(blank=True, null=True, verbose_name='错误信息')
    
    class Meta:
        verbose_name = '气候数据文件'
        verbose_name_plural = '气候数据文件'
        db_table = 'climate_data_files'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"


class ClimateAnalysisResult(models.Model):
    """气候分析结果模型"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    data_file = models.ForeignKey(ClimateDataFile, on_delete=models.CASCADE, related_name='analysis_results', verbose_name='数据文件')
    processing_task = models.ForeignKey('ProcessingTask', on_delete=models.SET_NULL, null=True, blank=True, related_name='climate_results', verbose_name='处理任务')
    analysis_type = models.CharField(max_length=50, default='comprehensive', verbose_name='分析类型')
    
    # 统计数据
    temperature_avg = models.FloatField(null=True, blank=True, verbose_name='平均温度')
    temperature_max = models.FloatField(null=True, blank=True, verbose_name='最高温度')
    temperature_min = models.FloatField(null=True, blank=True, verbose_name='最低温度')
    temperature_std = models.FloatField(null=True, blank=True, verbose_name='温度标准差')
    
    precipitation_avg = models.FloatField(null=True, blank=True, verbose_name='平均降水量')
    precipitation_max = models.FloatField(null=True, blank=True, verbose_name='最大降水量')
    precipitation_min = models.FloatField(null=True, blank=True, verbose_name='最小降水量')
    precipitation_std = models.FloatField(null=True, blank=True, verbose_name='降水量标准差')
    
    humidity_avg = models.FloatField(null=True, blank=True, verbose_name='平均湿度')
    humidity_max = models.FloatField(null=True, blank=True, verbose_name='最大湿度')
    humidity_min = models.FloatField(null=True, blank=True, verbose_name='最小湿度')
    humidity_std = models.FloatField(null=True, blank=True, verbose_name='湿度标准差')
    
    wind_speed_avg = models.FloatField(null=True, blank=True, verbose_name='平均风速')
    wind_speed_max = models.FloatField(null=True, blank=True, verbose_name='最大风速')
    wind_speed_min = models.FloatField(null=True, blank=True, verbose_name='最小风速')
    wind_speed_std = models.FloatField(null=True, blank=True, verbose_name='风速标准差')
    
    # 图表数据（JSON格式存储）
    chart_data = models.JSONField(default=dict, verbose_name='图表数据')
    
    # 分析报告
    report_file = models.FileField(upload_to='climate_reports/', null=True, blank=True, verbose_name='分析报告')
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    
    class Meta:
        verbose_name = '气候分析结果'
        verbose_name_plural = '气候分析结果'
        db_table = 'climate_analysis_results'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.data_file.name} - {self.analysis_type}"


class BusinessLayer(models.Model):
    """用户上传并发布到GeoServer的业务图层"""
    LAYER_TYPE_CHOICES = [
        ('vector', '矢量图层'),
        ('raster', '栅格图层'),
    ]

    SOURCE_FORMAT_CHOICES = [
        ('shapefile', 'Shapefile ZIP'),
        ('kml', 'KML'),
        ('geotiff', 'GeoTIFF'),
        ('wms', '外部WMS服务'),
        ('wfs', '外部WFS服务'),
        ('wcs', '外部WCS服务'),
    ]

    STATUS_CHOICES = [
        ('uploaded', '已上传'),
        ('publishing', '发布中'),
        ('published', '已发布'),
        ('failed', '发布失败'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, verbose_name='图层名称')
    description = models.TextField(blank=True, null=True, verbose_name='描述')
    layer_type = models.CharField(max_length=20, choices=LAYER_TYPE_CHOICES, verbose_name='图层类型')
    source_format = models.CharField(max_length=20, choices=SOURCE_FORMAT_CHOICES, verbose_name='源数据格式')
    file = models.FileField(upload_to='business_layers/source/', verbose_name='源数据文件', null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='uploaded', verbose_name='发布状态')
    service_url = models.URLField(max_length=1000, blank=True, null=True, verbose_name='标准服务地址')
    service_type_name = models.CharField(max_length=255, blank=True, null=True, verbose_name='服务图层名称')
    service_srs = models.CharField(max_length=64, blank=True, null=True, verbose_name='服务坐标系')
    style_name = models.CharField(max_length=255, blank=True, null=True, verbose_name='样式名称')
    style_config = models.JSONField(default=dict, blank=True, verbose_name='样式配置')
    sld_content = models.TextField(blank=True, null=True, verbose_name='SLD内容')
    service_health_status = models.CharField(max_length=20, default='unknown', verbose_name='服务可用性状态')
    service_health_message = models.CharField(max_length=500, blank=True, null=True, verbose_name='服务可用性说明')
    service_checked_at = models.DateTimeField(blank=True, null=True, verbose_name='服务检测时间')

    geoserver_workspace = models.CharField(max_length=100, blank=True, null=True, verbose_name='GeoServer工作空间')
    geoserver_store_name = models.CharField(max_length=200, blank=True, null=True, verbose_name='GeoServer数据存储')
    geoserver_layer_name = models.CharField(max_length=200, blank=True, null=True, verbose_name='GeoServer图层名')
    wms_url = models.URLField(max_length=1000, blank=True, null=True, verbose_name='WMS地址')
    wfs_url = models.URLField(max_length=1000, blank=True, null=True, verbose_name='WFS地址')
    wcs_url = models.URLField(max_length=1000, blank=True, null=True, verbose_name='WCS地址')

    metadata = models.JSONField(default=dict, blank=True, verbose_name='图层元数据')
    error_message = models.TextField(blank=True, null=True, verbose_name='错误信息')
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='上传用户')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    published_at = models.DateTimeField(blank=True, null=True, verbose_name='发布时间')

    class Meta:
        verbose_name = '业务图层'
        verbose_name_plural = '业务图层'
        db_table = 'business_layers'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"


class BusinessLayerAuditLog(models.Model):
    """业务图层发布、删除、样式配置等操作日志"""
    ACTION_CHOICES = [
        ('upload', '上传'),
        ('publish', '发布'),
        ('unpublish', '撤销发布'),
        ('delete', '删除'),
        ('style_update', '样式更新'),
        ('health_check', '服务检测'),
    ]

    STATUS_CHOICES = [
        ('success', '成功'),
        ('failed', '失败'),
        ('info', '信息'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business_layer = models.ForeignKey(BusinessLayer, on_delete=models.CASCADE, related_name='audit_logs', verbose_name='业务图层')
    action = models.CharField(max_length=30, choices=ACTION_CHOICES, verbose_name='操作类型')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='info', verbose_name='操作结果')
    operator = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='操作人')
    operator_name = models.CharField(max_length=150, blank=True, null=True, verbose_name='操作人名称')
    message = models.CharField(max_length=500, blank=True, null=True, verbose_name='说明')
    details = models.JSONField(default=dict, blank=True, verbose_name='日志详情')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        verbose_name = '业务图层审计日志'
        verbose_name_plural = '业务图层审计日志'
        db_table = 'business_layer_audit_logs'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.business_layer.name} - {self.get_action_display()} - {self.get_status_display()}"


class EcologicalIndexFile(models.Model):
    """生态指数文件模型"""
    STATUS_CHOICES = [
        ('uploaded', '已上传'),
        ('processing', '处理中'),
        ('completed', '完成'),
        ('failed', '失败'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    filename = models.CharField(max_length=255, verbose_name='文件名')
    file = models.FileField(upload_to='ecological_indices/', verbose_name='文件')
    description = models.TextField(blank=True, null=True, verbose_name='描述')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='uploaded', verbose_name='状态')

    # 生态指数数据（JSON格式存储）
    indices_data = models.JSONField(default=dict, verbose_name='生态指数数据')

    # 时间戳
    timestamp = models.DateTimeField(null=True, blank=True, verbose_name='数据时间戳')

    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='上传用户')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    processed_at = models.DateTimeField(null=True, blank=True, verbose_name='处理完成时间')
    error_message = models.TextField(blank=True, null=True, verbose_name='错误信息')

    class Meta:
        verbose_name = '生态指数文件'
        verbose_name_plural = '生态指数文件'
        db_table = 'ecological_index_files'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.filename} ({self.get_status_display()})"


class EcologicalProjectFile(models.Model):
    """生态修复工程文件模型"""
    STATUS_CHOICES = [
        ('uploaded', '已上传'),
        ('processing', '处理中'),
        ('completed', '完成'),
        ('failed', '失败'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    filename = models.CharField(max_length=255, verbose_name='文件名')
    file = models.FileField(upload_to='ecological_projects/', verbose_name='文件')
    description = models.TextField(blank=True, null=True, verbose_name='描述')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='uploaded', verbose_name='状态')

    # GeoJSON数据
    geojson_data = models.JSONField(default=dict, verbose_name='GeoJSON数据')

    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='上传用户')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    processed_at = models.DateTimeField(null=True, blank=True, verbose_name='处理完成时间')
    error_message = models.TextField(blank=True, null=True, verbose_name='错误信息')

    class Meta:
        verbose_name = '生态修复工程文件'
        verbose_name_plural = '生态修复工程文件'
        db_table = 'ecological_project_files'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.filename} ({self.get_status_display()})"


class OverlayAnalysisTask(models.Model):
    """叠加分析任务模型"""
    STATUS_CHOICES = [
        ('pending', '等待中'),
        ('processing', '处理中'),
        ('completed', '已完成'),
        ('failed', '失败'),
        ('cancelled', '已取消'),
    ]

    RISK_LEVEL_CHOICES = [
        ('low', '低风险'),
        ('medium', '中风险'),
        ('high', '高风险'),
        ('critical', '极高风险'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, verbose_name='分析任务名称')
    description = models.TextField(blank=True, null=True, verbose_name='任务描述')

    # 关联的文件
    ecological_index_file = models.ForeignKey(EcologicalIndexFile, on_delete=models.CASCADE, verbose_name='生态指数文件')
    ecological_project_file = models.ForeignKey(EcologicalProjectFile, on_delete=models.CASCADE, verbose_name='生态修复工程文件')

    # 任务状态
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name='任务状态')
    progress = models.IntegerField(default=0, verbose_name='进度百分比')
    current_step = models.CharField(max_length=100, blank=True, null=True, verbose_name='当前步骤')

    # 分析结果
    analysis_results = models.JSONField(default=dict, verbose_name='分析结果')
    overall_risk_level = models.CharField(max_length=20, choices=RISK_LEVEL_CHOICES, null=True, blank=True, verbose_name='总体风险等级')

    # 栅格图层文件（用于空间展示）
    risk_raster_file = models.FileField(upload_to='overlay_analysis/rasters/', null=True, blank=True, verbose_name='风险等级栅格文件')
    impact_raster_file = models.FileField(upload_to='overlay_analysis/rasters/', null=True, blank=True, verbose_name='影响强度栅格文件')
    
    # 栅格图层元数据（WMS URL等）
    raster_layers_metadata = models.JSONField(default=dict, verbose_name='栅格图层元数据')

    # 错误信息
    error_message = models.TextField(blank=True, null=True, verbose_name='错误信息')

    # 用户信息
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='创建用户')

    # 时间信息
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    started_at = models.DateTimeField(blank=True, null=True, verbose_name='开始时间')
    completed_at = models.DateTimeField(blank=True, null=True, verbose_name='完成时间')

    class Meta:
        verbose_name = '叠加分析任务'
        verbose_name_plural = '叠加分析任务'
        db_table = 'overlay_analysis_tasks'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"
