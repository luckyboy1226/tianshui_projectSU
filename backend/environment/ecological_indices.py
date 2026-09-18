import numpy as np
import rasterio
from rasterio.mask import mask
from rasterio.warp import calculate_default_transform, reproject, Resampling
import matplotlib.pyplot as plt
import matplotlib.colors as colors
from matplotlib.colors import LinearSegmentedColormap
import matplotlib
import matplotlib.font_manager as fm

# 设置matplotlib后端和中文字体支持
matplotlib.use('Agg')  # 使用非交互式后端
plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans', 'Arial Unicode MS', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题
import os
import tempfile
import time
from PIL import Image
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
import logging
from .band_mapping import (
    get_band_descriptions,
    get_band_scale_offset,
    get_tasseled_cap_coefficients,
    infer_standard_band_mapping,
    thermal_band_is_calibrated,
    thermal_conversion_parameters,
    uses_approximate_tasseled_cap,
)

logger = logging.getLogger(__name__)


class EcologicalIndexCalculator:
    """生态指数计算器"""
    
    def __init__(self, image_path):
        """
        初始化计算器
        
        Args:
            image_path: 遥感影像文件路径
        """
        self.image_path = image_path
        self.dataset = None
        self.bands = None
        self.metadata = None
        self._sensor_band_mapping = None
        self._scaled_band_cache = {}
        self.stage_timings = {}
        # 科学栅格保持全分辨率；仅 PNG 预览降采样。
        self.preview_max_dimension = 2048
        self.statistics_chunk_rows = 512
        self.output_options = {
            'tiled': True,
            'blockxsize': 512,
            'blockysize': 512,
            'BIGTIFF': 'IF_SAFER',
        }
        # NONE（默认）优先低延迟；DEFLATE/ZSTD 用于存储或网络 I/O 优先场景。
        compression = os.environ.get('GIS_RASTER_COMPRESSION', 'NONE').strip().lower()
        if compression in {'deflate', 'zstd'}:
            self.output_options.update({'compress': compression, 'predictor': 3})

    def _record_stage(self, name, started_at):
        """累计记录可由任务/压测命令读取的结构化阶段耗时（秒）。"""
        self.stage_timings[name] = round(self.stage_timings.get(name, 0.0) + time.perf_counter() - started_at, 6)
        
    def load_image(self):
        """加载遥感影像"""
        try:
            logger.info(f"开始加载影像: {self.image_path}")
            logger.info(f"文件是否存在: {os.path.exists(self.image_path)}")
            
            if not os.path.exists(self.image_path):
                logger.error(f"影像文件不存在: {self.image_path}")
                return False
            
            # 尝试使用rasterio打开
            try:
                self.dataset = rasterio.open(self.image_path)
                logger.info(f"rasterio成功打开文件")
                
                # rasterio成功，正常读取
                self.bands = self.dataset.read()
                self.metadata = self.dataset.meta
                self._sensor_band_mapping = None
                self._scaled_band_cache = {}
                
                # 安全检查数组形状
                if self.bands is not None and hasattr(self.bands, 'shape') and len(self.bands.shape) >= 3:
                    logger.info(f"rasterio读取成功，波段数: {self.bands.shape[0]}, 形状: {self.bands.shape}")
                else:
                    logger.error(f"rasterio读取的数据形状异常: {self.bands.shape if self.bands is not None else 'None'}")
                    return False
                
            except Exception as rasterio_error:
                logger.error(f"rasterio打开失败: {rasterio_error}")
                
                # 尝试使用PIL作为备选方案
                try:
                    logger.info("尝试使用PIL加载影像")
                    pil_image = Image.open(self.image_path)
                    
                    # 转换为numpy数组
                    pil_array = np.array(pil_image)
                    logger.info(f"PIL图像原始形状: {pil_array.shape}")
                    
                    if len(pil_array.shape) == 3:
                        # RGB图像，调整维度顺序为(rasterio格式)
                        self.bands = np.transpose(pil_array, (2, 0, 1))
                        self.metadata = {
                            'driver': 'PNG',
                            'height': pil_array.shape[0],
                            'width': pil_array.shape[1],
                            'count': pil_array.shape[2],
                            'dtype': str(pil_array.dtype),
                            'crs': None,
                            'transform': None
                        }
                        self._sensor_band_mapping = None
                        self._scaled_band_cache = {}
                        logger.info(f"PIL加载成功，转置后波段数: {self.bands.shape[0]}, 形状: {self.bands.shape}")
                    else:
                        logger.error(f"PIL图像不是3D数组，形状: {pil_array.shape}")
                        return False
                        
                except Exception as pil_error:
                    logger.error(f"PIL加载也失败: {pil_error}")
                    import traceback
                    traceback.print_exc()
                    return False
            
            # 检查波段数
            if hasattr(self, 'bands') and self.bands is not None:
                # 安全检查数组形状
                if not hasattr(self.bands, 'shape') or len(self.bands.shape) < 3:
                    logger.error(f"影像数据形状异常: {self.bands.shape if self.bands is not None else 'None'}")
                    return False
                
                band_count = self.bands.shape[0]
                logger.info(f"成功加载影像: {self.image_path}, 波段数: {band_count}")
                logger.info(f"影像形状: {self.bands.shape}")
                
                if band_count < 3:
                    logger.warning(f"影像波段数不足: {band_count}，至少需要3个波段")
                    return False
                    
                return True
            else:
                logger.error("bands属性未正确设置")
                return False
                
        except Exception as e:
            logger.error(f"加载影像失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _check_band_availability(self, required_bands):
        """检查是否有足够的波段进行计算"""
        if self.bands is None:
            return False
        
        available_bands = self.bands.shape[0]
        if available_bands < required_bands:
            logger.warning(f"需要{required_bands}个波段，但只有{available_bands}个波段")
            return False
        
        return True

    def _normalized_band_descriptions(self):
        """返回标准化后的波段描述到0基索引的映射。"""
        descriptions = get_band_descriptions(self.dataset)
        mapping = {}
        for index, description in enumerate(descriptions):
            normalized = str(description or '').strip().upper()
            if normalized:
                mapping[normalized] = index
        return mapping

    def _get_sensor_band_mapping(self):
        """根据常见栅格波段组织方式推断标准RSEI所需波段位置。"""
        if self.bands is None or not hasattr(self.bands, 'shape') or len(self.bands.shape) < 3:
            return None

        if self._sensor_band_mapping is None:
            self._sensor_band_mapping = infer_standard_band_mapping(
                dataset=self.dataset,
                band_count=int(self.bands.shape[0]),
            )
            if self._sensor_band_mapping:
                logger.info(f"识别到波段映射: {self._sensor_band_mapping}")
        return self._sensor_band_mapping

    def _get_scaled_band_by_index(self, band_index):
        """按scale/offset还原指定0基波段数据。"""
        if band_index in self._scaled_band_cache:
            return self._scaled_band_cache[band_index]

        if self.bands is None or band_index < 0 or band_index >= self.bands.shape[0]:
            return None

        raw_band = self.bands[band_index].astype(np.float32, copy=False)
        scale, offset = get_band_scale_offset(self.dataset, band_index, band_count=self.bands.shape[0])
        scaled_band = raw_band * np.float32(scale) + np.float32(offset)
        self._scaled_band_cache[band_index] = scaled_band
        return scaled_band

    def _get_band_array(self, band_name):
        """获取指定波段数组。"""
        mapping = self._get_sensor_band_mapping()
        if not mapping:
            return None

        band_index = mapping.get(band_name)
        if band_index is None:
            return None

        return self._get_scaled_band_by_index(band_index)

    def _safe_normalized_difference(self, band_a, band_b):
        """安全计算归一化差值指数。"""
        if band_a is None or band_b is None:
            return None

        # 复用 result 作为分子，避免额外保留一个 65M 像元临时数组。
        result = np.empty_like(band_a, dtype=np.float32)
        np.subtract(band_a, band_b, out=result)
        denominator = np.add(band_a, band_b, dtype=np.float32)
        valid_mask = np.isfinite(band_a) & np.isfinite(band_b) & (denominator != 0)
        np.divide(result, denominator, out=result, where=valid_mask)
        result[~valid_mask] = np.nan
        np.clip(result, -1.0, 1.0, out=result)
        return result

    def _safe_divide(self, numerator, denominator):
        """安全除法，非法值返回NaN。"""
        result = np.full_like(numerator, np.nan, dtype=np.float32)
        valid_mask = np.isfinite(numerator) & np.isfinite(denominator) & (denominator != 0)
        np.divide(numerator, denominator, out=result, where=valid_mask)
        return result

    def _normalize_to_unit_interval(self, index_data):
        """将数组按自身有效值归一化到[0, 1]。"""
        normalized = np.full_like(index_data, np.nan, dtype=np.float32)
        valid_mask = np.isfinite(index_data)
        if not np.any(valid_mask):
            return normalized

        # nanmin/nanmax 不会生成 index_data[valid_mask] 这一整幅复制。
        min_val = np.nanmin(index_data)
        max_val = np.nanmax(index_data)
        if max_val > min_val:
            np.subtract(index_data, min_val, out=normalized, where=valid_mask)
            np.divide(normalized, max_val - min_val, out=normalized, where=valid_mask)
        else:
            normalized[valid_mask] = 0.0
        return normalized
    
    def calculate_ndvi(self):
        """计算NDVI（归一化植被指数）"""
        try:
            if not hasattr(self, 'bands') or self.bands is None:
                logger.error("没有加载影像数据")
                return None

            if not hasattr(self.bands, 'shape') or len(self.bands.shape) < 3:
                logger.error(f"影像数据形状异常: {self.bands.shape if self.bands is not None else 'None'}")
                return None

            nir = self._get_band_array('nir')
            red = self._get_band_array('red')

            if nir is None or red is None:
                available_bands = self.bands.shape[0]
                if available_bands == 3:
                    nir = self._get_scaled_band_by_index(1)
                    red = self._get_scaled_band_by_index(0)
                    logger.info("使用RGB波段近似计算NDVI")
                else:
                    logger.error(f"当前波段配置不支持NDVI计算: {available_bands}波段")
                    return None

            ndvi = self._safe_normalized_difference(nir, red)
            if ndvi is None:
                logger.error("NDVI计算失败，近红外或红波段无效")
                return None

            logger.info(f"NDVI计算完成，形状: {ndvi.shape}")
            logger.info(f"NDVI值范围: [{np.nanmin(ndvi):.4f}, {np.nanmax(ndvi):.4f}]")
            return ndvi
        except Exception as e:
            logger.error(f"计算NDVI失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def calculate_ndwi(self):
        """计算NDWI（归一化水体指数）"""
        try:
            if not hasattr(self, 'bands') or self.bands is None:
                logger.error("没有加载影像数据")
                return None

            if not hasattr(self.bands, 'shape') or len(self.bands.shape) < 3:
                logger.error(f"影像数据形状异常: {self.bands.shape if self.bands is not None else 'None'}")
                return None

            green = self._get_band_array('green')
            nir = self._get_band_array('nir')

            if green is None or nir is None:
                available_bands = self.bands.shape[0]
                if available_bands == 3:
                    green = self._get_scaled_band_by_index(1)
                    nir = self._get_scaled_band_by_index(0)
                    logger.info("使用RGB波段近似计算NDWI")
                else:
                    logger.error(f"当前波段配置不支持NDWI计算: {available_bands}波段")
                    return None

            ndwi = self._safe_normalized_difference(green, nir)
            if ndwi is None:
                logger.error("NDWI计算失败，绿波段或近红外波段无效")
                return None

            logger.info(f"NDWI计算完成，形状: {ndwi.shape}")
            logger.info(f"NDWI值范围: [{np.nanmin(ndwi):.4f}, {np.nanmax(ndwi):.4f}]")
            return ndwi
        except Exception as e:
            logger.error(f"计算NDWI失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def calculate_ndbi(self):
        """计算NDBI（归一化建筑指数）"""
        try:
            if not hasattr(self, 'bands') or self.bands is None:
                logger.error("没有加载影像数据")
                return None

            if not hasattr(self.bands, 'shape') or len(self.bands.shape) < 3:
                logger.error(f"影像数据形状异常: {self.bands.shape if self.bands is not None else 'None'}")
                return None

            swir = self._get_band_array('swir1')
            nir = self._get_band_array('nir')

            if swir is None or nir is None:
                available_bands = self.bands.shape[0]
                if available_bands == 3:
                    swir = self._get_scaled_band_by_index(2)
                    nir = self._get_scaled_band_by_index(0)
                    logger.info("使用RGB波段近似计算NDBI")
                else:
                    logger.error(f"当前波段配置不支持NDBI计算: {available_bands}波段")
                    return None

            ndbi = self._safe_normalized_difference(swir, nir)
            if ndbi is None:
                logger.error("NDBI计算失败，短波红外或近红外波段无效")
                return None

            logger.info(f"NDBI计算完成，形状: {ndbi.shape}")
            logger.info(f"NDBI值范围: [{np.nanmin(ndbi):.4f}, {np.nanmax(ndbi):.4f}]")
            return ndbi
        except Exception as e:
            logger.error(f"计算NDBI失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def calculate_ndsi(self):
        """计算NDSI（归一化积雪指数）"""
        try:
            if not self._check_band_availability(3):
                logger.warning("波段数不足，无法计算NDSI")
                return None

            green_band = self._get_band_array('green')
            swir_band = self._get_band_array('swir1')
            blue_band = self._get_band_array('blue')
            red_band = self._get_band_array('red')

            if green_band is not None and swir_band is not None:
                ndsi = self._safe_normalized_difference(green_band, swir_band)
                logger.info("使用 Green/SWIR1 计算标准NDSI")
            elif self.bands.shape[0] == 4 and green_band is not None and red_band is not None:
                ndsi = self._safe_normalized_difference(green_band, red_band)
                logger.info("当前影像缺少SWIR1，使用 Green/Red 近似计算NDSI")
            elif self.bands.shape[0] == 3 and green_band is not None and blue_band is not None:
                ndsi = self._safe_normalized_difference(green_band, blue_band)
                logger.info("当前影像为RGB，使用 Green/Blue 近似计算NDSI")
            else:
                logger.warning(f"当前波段配置不支持NDSI计算: {self.bands.shape[0]}波段")
                return None

            return np.clip(ndsi, -1, 1) if ndsi is not None else None
        except Exception as e:
            logger.error(f"计算NDSI失败: {e}")
            return None
    
    def calculate_wetness(self):
        """计算湿度指数（WET，基于标准Tasseled Cap湿度分量）"""
        try:
            mapping = self._get_sensor_band_mapping()
            if not mapping:
                logger.error("无法识别影像波段布局，不能计算湿度指数")
                return None

            blue = self._get_band_array('blue')
            green = self._get_band_array('green')
            red = self._get_band_array('red')
            nir = self._get_band_array('nir')
            swir1 = self._get_band_array('swir1')
            swir2 = self._get_band_array('swir2')

            if any(item is None for item in [blue, green, red, nir, swir1, swir2]):
                logger.warning("当前影像缺少计算WET所需的Blue/Green/Red/NIR/SWIR1/SWIR2波段")
                return None

            tc_coefficients = get_tasseled_cap_coefficients(mapping.get('profile'))
            if not tc_coefficients or 'wetness' not in tc_coefficients:
                logger.warning("当前影像缺少可用的Tasseled Cap系数，无法计算标准WET")
                return None

            coefficients = tc_coefficients['wetness']
            if uses_approximate_tasseled_cap(mapping.get('profile')):
                logger.warning(
                    "当前影像使用通用6波段近似系数计算WET，结果可用于参考，但不同传感器间不建议直接对比"
                )

            wetness = (
                coefficients[0] * blue +
                coefficients[1] * green +
                coefficients[2] * red +
                coefficients[3] * nir +
                coefficients[4] * swir1 +
                coefficients[5] * swir2
            ).astype(np.float32)

            logger.info(f"湿度指数计算完成，形状: {wetness.shape}")
            return wetness
        except Exception as e:
            logger.error(f"计算湿度指数失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def calculate_dryness(self):
        """计算干度指数（NDBSI = (SI + IBI) / 2）"""
        try:
            blue = self._get_band_array('blue')
            green = self._get_band_array('green')
            red = self._get_band_array('red')
            nir = self._get_band_array('nir')
            swir1 = self._get_band_array('swir1')

            if any(item is None for item in [blue, green, red, nir, swir1]):
                logger.warning("当前影像缺少计算NDBSI所需的Blue/Green/Red/NIR/SWIR1波段")
                return None

            si_numerator = (swir1 + red) - (nir + blue)
            si_denominator = (swir1 + red) + (nir + blue)
            si = self._safe_divide(si_numerator, si_denominator)

            ndbi_component = self._safe_divide(2.0 * swir1, swir1 + nir)
            vegetation_component = self._safe_divide(nir, nir + red)
            water_component = self._safe_divide(green, green + swir1)
            ibi_numerator = ndbi_component - (vegetation_component + water_component)
            ibi_denominator = ndbi_component + vegetation_component + water_component
            ibi = self._safe_divide(ibi_numerator, ibi_denominator)

            dryness = ((si + ibi) / 2.0).astype(np.float32)
            logger.info(f"干度指数计算完成，形状: {dryness.shape}")
            return dryness
        except Exception as e:
            logger.error(f"计算干度指数失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def calculate_heat(self):
        """计算热度指数（LST/热红外亮温分量）。"""
        try:
            mapping = self._get_sensor_band_mapping() or {}
            thermal = self._get_band_array('thermal')
            if thermal is None:
                logger.warning("当前影像缺少热红外/LST波段，无法计算标准热度指数")
                return None

            if not thermal_band_is_calibrated(mapping=mapping, dataset=self.dataset):
                logger.warning("当前影像热红外波段缺少可靠的温度量纲信息，无法计算标准热度指数")
                return None

            heat = np.where(np.isfinite(thermal), thermal, np.nan).astype(np.float32)
            scale, offset = thermal_conversion_parameters(mapping.get('profile'))
            if scale is not None and offset is not None:
                raw_scale, raw_offset = get_band_scale_offset(
                    self.dataset,
                    mapping['thermal'],
                    band_count=self.bands.shape[0],
                )
                if abs(raw_scale - 1.0) <= 1e-12 and abs(raw_offset) <= 1e-12:
                    heat = heat * np.float32(scale) + np.float32(offset)
                    logger.info("当前热红外波段缺少scale/offset元数据，已按已知传感器参数补充还原")

            logger.info(f"热度指数计算完成，形状: {heat.shape}")
            return heat
        except Exception as e:
            logger.error(f"计算热度指数失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def calculate_greenness(self):
        """计算绿度指数（标准RSEI中使用NDVI作为绿度分量）"""
        try:
            greenness = self.calculate_ndvi()
            if greenness is not None:
                logger.info(f"绿度指数计算完成，形状: {greenness.shape}")
            return greenness
        except Exception as e:
            logger.error(f"计算绿度指数失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def calculate_rsei(self, components=None):
        """计算RSEI（遥感生态指数）。

        components 为已计算的原始分量数组时直接复用，避免任务编排中对四个
        6530 万像元分量重复计算；未传入时保留旧调用方式以便兼容/基线 A/B。
        """
        try:
            logger.info("开始计算RSEI...")
            component_started = time.perf_counter()
            if components is None:
                greenness = self.calculate_greenness()
                wetness = self.calculate_wetness()
                dryness = self.calculate_dryness()
                heat = self.calculate_heat()
                self._record_stage('rsei_component_recalculation', component_started)
            else:
                greenness = components.get('greenness')
                wetness = components.get('wetness')
                dryness = components.get('dryness')
                heat = components.get('heat')
                self._record_stage('rsei_component_reuse', component_started)
            
            if greenness is None or wetness is None or dryness is None or heat is None:
                logger.warning("无法计算RSEI，某些分量指数计算失败")
                return None
            
            logger.info("所有分量指数计算成功，开始标准RSEI计算")
            
            # 检查数据形状是否一致
            if not all(hasattr(idx, 'shape') for idx in [greenness, wetness, dryness, heat]):
                logger.error("某些分量指数没有shape属性")
                return None
            
            shapes = [greenness.shape, wetness.shape, dryness.shape, heat.shape]
            if len(set(shapes)) > 1:
                logger.error(f"分量指数形状不一致: {shapes}")
                return None
            
            # 检查数组是否为空或无效
            if any(idx.size == 0 for idx in [greenness, wetness, dryness, heat]):
                logger.error("某些分量指数数组为空")
                return None
            
            # 标准RSEI先对四个分量分别归一化，再执行PCA
            try:
                normalization_started = time.perf_counter()
                greenness_n = self._normalize_to_unit_interval(greenness)
                wetness_n = self._normalize_to_unit_interval(wetness)
                dryness_n = self._normalize_to_unit_interval(dryness)
                heat_n = self._normalize_to_unit_interval(heat)
                self._record_stage('rsei_normalization', normalization_started)

                valid_mask_2d = (
                    np.isfinite(greenness_n) &
                    np.isfinite(wetness_n) &
                    np.isfinite(dryness_n) &
                    np.isfinite(heat_n)
                )

                if not np.any(valid_mask_2d):
                    logger.warning("没有有效的指数数据来计算RSEI")
                    return None

                indices_valid = np.column_stack([
                    greenness_n[valid_mask_2d],
                    wetness_n[valid_mask_2d],
                    dryness_n[valid_mask_2d],
                    heat_n[valid_mask_2d]
                ])

                logger.info(f"有效数据点数量: {len(indices_valid)}")

                pca_started = time.perf_counter()
                pca = PCA(n_components=4)
                pca_result = pca.fit_transform(indices_valid)
                self._record_stage('rsei_pca', pca_started)
                logger.info("PCA计算完成")

                pc1 = pca_result[:, 0]

                ecological_score = (
                    greenness_n[valid_mask_2d] +
                    wetness_n[valid_mask_2d] -
                    dryness_n[valid_mask_2d] -
                    heat_n[valid_mask_2d]
                )

                corr_matrix = np.corrcoef(pc1, ecological_score)
                pc1_corr = corr_matrix[0, 1] if corr_matrix.shape == (2, 2) else np.nan
                corrected_components = pca.components_.copy()

                if np.isfinite(pc1_corr) and pc1_corr < 0:
                    pc1 = -pc1
                    corrected_components[0] = -corrected_components[0]

                rsei_values = np.full(valid_mask_2d.sum(), 0.0, dtype=np.float32)
                pc1_min = np.nanmin(pc1)
                pc1_max = np.nanmax(pc1)
                if pc1_max > pc1_min:
                    rsei_values = ((pc1 - pc1_min) / (pc1_max - pc1_min)).astype(np.float32)

                rsei = np.full(greenness.shape, np.nan, dtype=np.float32)
                rsei[valid_mask_2d] = rsei_values

                logger.info("RSEI计算完成")
                return {
                    'rsei': rsei,
                    'greenness': greenness_n,
                    'wetness': wetness_n,
                    'dryness': dryness_n,
                    'heat': heat_n,
                    'pca_variance': pca.explained_variance_ratio_,
                    'pca_components': corrected_components
                }
            except Exception as pca_error:
                logger.error(f"PCA计算失败: {pca_error}")
                import traceback
                traceback.print_exc()
                return None
                
        except Exception as e:
            logger.error(f"计算RSEI失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def calculate_statistics(self, index_data, chunk_rows=None):
        """计算指数统计信息"""
        if index_data is None:
            return None
        
        try:
            # 检查数组是否有效
            if not hasattr(index_data, 'shape') or not hasattr(index_data, 'size'):
                logger.error("输入数据不是有效的numpy数组")
                return None
            
            if index_data.size == 0:
                logger.warning("输入数据为空数组")
                return None
            
            chunk_rows = self.statistics_chunk_rows if chunk_rows is None else chunk_rows
            if chunk_rows:
                return self._calculate_statistics_chunked(index_data, int(chunk_rows))

            # 兼容旧路径：一次性去除无效值
            try:
                valid_data = index_data[~np.isnan(index_data)]
            except Exception as mask_error:
                logger.error(f"创建有效数据掩码失败: {mask_error}")
                return None
            
            if len(valid_data) == 0:
                logger.warning("没有有效数据来计算统计信息")
                return None
            
            # 计算基本统计量
            try:
                stats = {
                    'min_value': float(np.nanmin(valid_data)),
                    'max_value': float(np.nanmax(valid_data)),
                    'mean_value': float(np.nanmean(valid_data)),
                    'std_value': float(np.nanstd(valid_data)),
                }
            except Exception as calc_error:
                logger.error(f"计算基本统计量失败: {calc_error}")
                return None
            
            pixel_size = 30
            if self.dataset is not None and getattr(self.dataset, 'transform', None) is not None:
                try:
                    x_res = abs(float(self.dataset.transform.a))
                    y_res = abs(float(self.dataset.transform.e))
                    if x_res > 0 and y_res > 0:
                        pixel_size = (x_res + y_res) / 2
                except Exception:
                    pixel_size = 30
            area_per_pixel = pixel_size * pixel_size / 1000000

            try:
                if stats['min_value'] >= 0 and stats['max_value'] <= 1.000001:
                    excellent_pixels = np.sum(valid_data >= 0.8)
                    good_pixels = np.sum((valid_data >= 0.6) & (valid_data < 0.8))
                    moderate_pixels = np.sum((valid_data >= 0.4) & (valid_data < 0.6))
                    poor_pixels = np.sum((valid_data >= 0.2) & (valid_data < 0.4))
                    bad_pixels = np.sum(valid_data < 0.2)
                else:
                    mean_val = stats['mean_value']
                    std_val = stats['std_value']
                    thresholds = {
                        'excellent': mean_val + 1.5 * std_val,
                        'good': mean_val + 0.5 * std_val,
                        'moderate': mean_val - 0.5 * std_val,
                        'poor': mean_val - 1.5 * std_val,
                    }
                    excellent_pixels = np.sum(valid_data >= thresholds['excellent'])
                    good_pixels = np.sum((valid_data >= thresholds['good']) & (valid_data < thresholds['excellent']))
                    moderate_pixels = np.sum((valid_data >= thresholds['moderate']) & (valid_data < thresholds['good']))
                    poor_pixels = np.sum((valid_data >= thresholds['poor']) & (valid_data < thresholds['moderate']))
                    bad_pixels = np.sum(valid_data < thresholds['poor'])
            except Exception as count_error:
                logger.error(f"计算像素数量失败: {count_error}")
                return None
            
            stats.update({
                'excellent_area': float(excellent_pixels * area_per_pixel),
                'good_area': float(good_pixels * area_per_pixel),
                'moderate_area': float(moderate_pixels * area_per_pixel),
                'poor_area': float(poor_pixels * area_per_pixel),
                'bad_area': float(bad_pixels * area_per_pixel),
            })
            
            logger.info(f"统计信息计算完成，有效数据点: {len(valid_data)}")
            return stats
            
        except Exception as e:
            logger.error(f"计算统计信息失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _calculate_statistics_chunked(self, index_data, chunk_rows):
        """分块统计，避免整幅 index_data[valid_mask] 的大数组复制。"""
        started = time.perf_counter()
        height = index_data.shape[0]
        count = 0
        total = total_sq = 0.0
        minimum = np.inf
        maximum = -np.inf
        for row_off in range(0, height, chunk_rows):
            values = index_data[row_off:row_off + chunk_rows]
            valid = values[np.isfinite(values)]
            if valid.size:
                count += valid.size
                minimum = min(minimum, float(np.min(valid)))
                maximum = max(maximum, float(np.max(valid)))
                total += float(np.sum(valid, dtype=np.float64))
                total_sq += float(np.sum(np.square(valid, dtype=np.float64), dtype=np.float64))
        if not count:
            logger.warning("没有有效数据来计算统计信息")
            return None

        mean_value = total / count
        std_value = float(np.sqrt(max(0.0, total_sq / count - mean_value * mean_value)))
        stats = {
            'min_value': float(minimum), 'max_value': float(maximum),
            'mean_value': float(mean_value), 'std_value': std_value,
        }
        if minimum >= 0 and maximum <= 1.000001:
            thresholds = None
        else:
            thresholds = {
                'excellent': mean_value + 1.5 * std_value,
                'good': mean_value + 0.5 * std_value,
                'moderate': mean_value - 0.5 * std_value,
                'poor': mean_value - 1.5 * std_value,
            }
        buckets = {'excellent': 0, 'good': 0, 'moderate': 0, 'poor': 0, 'bad': 0}
        for row_off in range(0, height, chunk_rows):
            values = index_data[row_off:row_off + chunk_rows]
            valid = values[np.isfinite(values)]
            if not valid.size:
                continue
            if thresholds is None:
                buckets['excellent'] += int(np.count_nonzero(valid >= 0.8))
                buckets['good'] += int(np.count_nonzero((valid >= 0.6) & (valid < 0.8)))
                buckets['moderate'] += int(np.count_nonzero((valid >= 0.4) & (valid < 0.6)))
                buckets['poor'] += int(np.count_nonzero((valid >= 0.2) & (valid < 0.4)))
                buckets['bad'] += int(np.count_nonzero(valid < 0.2))
            else:
                buckets['excellent'] += int(np.count_nonzero(valid >= thresholds['excellent']))
                buckets['good'] += int(np.count_nonzero((valid >= thresholds['good']) & (valid < thresholds['excellent'])))
                buckets['moderate'] += int(np.count_nonzero((valid >= thresholds['moderate']) & (valid < thresholds['good'])))
                buckets['poor'] += int(np.count_nonzero((valid >= thresholds['poor']) & (valid < thresholds['moderate'])))
                buckets['bad'] += int(np.count_nonzero(valid < thresholds['poor']))
        pixel_size = 30
        if self.dataset is not None and getattr(self.dataset, 'transform', None) is not None:
            pixel_size = (abs(float(self.dataset.transform.a)) + abs(float(self.dataset.transform.e))) / 2
        area_per_pixel = pixel_size * pixel_size / 1000000
        stats.update({f'{key}_area': float(value * area_per_pixel) for key, value in buckets.items()})
        self._record_stage('statistics', started)
        return stats
    
    def create_visualization(self, index_data, index_name, output_path):
        """创建可视化图片"""
        try:
            if index_data is None:
                logger.warning("没有数据来创建可视化")
                return False
            
            # 检查数据是否包含有效值
            if np.all(np.isnan(index_data)):
                logger.warning("所有数据都是NaN，无法创建可视化")
                return False
            
            # 检查数据形状
            if not hasattr(index_data, 'shape'):
                logger.warning("数据没有shape属性")
                return False
            
            if len(index_data.shape) != 2:
                logger.warning(f"数据形状不正确，期望2D数组，实际为{index_data.shape}")
                return False
            
            # 检查数据是否为空
            if index_data.size == 0:
                logger.warning("数据数组为空")
                return False
            
            # matplotlib后端已在文件开头设置
            
            # 创建自定义颜色映射
            colors_list = ['#8B0000', '#FF0000', '#FFA500', '#FFFF00', '#00FF00', '#006400']
            n_bins = 256
            cmap = LinearSegmentedColormap.from_list('custom', colors_list, N=n_bins)
            cmap = cmap.copy()
            cmap.set_bad((1, 1, 1, 0))

            visualization_started = time.perf_counter()
            # PNG 是预览而非科学分析产品。对最长边限为 2048 px，避免
            # Matplotlib/percentile 为全分辨率 6530 万像元建立额外副本。
            preview_data = index_data
            max_dimension = self.preview_max_dimension
            if max_dimension and max(index_data.shape) > max_dimension:
                stride = int(np.ceil(max(index_data.shape) / float(max_dimension)))
                preview_data = index_data[::stride, ::stride]
            masked_data = np.ma.masked_invalid(preview_data)
            valid_mask = ~np.ma.getmaskarray(masked_data)
            if not np.any(valid_mask):
                logger.warning("没有有效像元用于生成可视化")
                return False

            height, width = preview_data.shape
            if width >= height:
                map_width = 10.0
                map_height = max(4.5, map_width * height / width)
            else:
                map_height = 10.0
                map_width = max(4.5, map_height * width / height)

            # 为颜色条与标题预留少量空间，但保持主图严格按原始宽高比绘制。
            figure_size = (map_width + 1.6, map_height + 1.2)
            
            # 创建图形 - 添加错误检查
            try:
                fig, ax = plt.subplots(figsize=figure_size)
                if fig is None or ax is None:
                    logger.error("matplotlib创建图形失败")
                    return False
            except Exception as subplot_error:
                logger.error(f"创建子图失败: {subplot_error}")
                return False
            
            try:
                # 绘制指数图
                valid_values = masked_data.compressed()
                vmin = float(np.nanpercentile(valid_values, 2)) if valid_values.size else None
                vmax = float(np.nanpercentile(valid_values, 98)) if valid_values.size else None
                if vmin is None or vmax is None or not np.isfinite(vmin) or not np.isfinite(vmax) or abs(vmax - vmin) < 1e-12:
                    vmin = float(np.nanmin(valid_values)) if valid_values.size else 0.0
                    vmax = float(np.nanmax(valid_values)) if valid_values.size else 1.0
                if abs(vmax - vmin) < 1e-12:
                    vmax = vmin + 1e-6

                im = ax.imshow(
                    masked_data,
                    cmap=cmap,
                    aspect='equal',
                    interpolation='nearest',
                    vmin=vmin,
                    vmax=vmax,
                )
                ax.set_box_aspect(height / width)
                
                # 添加颜色条
                cbar = plt.colorbar(im, ax=ax, shrink=0.8)
                cbar.set_label(f'{index_name} 值', fontsize=12)
                
                # 设置标题和标签
                ax.set_title(f'{index_name} 分布图', fontsize=16, fontweight='bold')
                
                # 去除坐标轴刻度
                ax.set_xticks([])
                ax.set_yticks([])
                for spine in ax.spines.values():
                    spine.set_visible(False)
                
                # 保存图片
                plt.tight_layout()
                plt.savefig(output_path, dpi=300, bbox_inches='tight', pad_inches=0.08)
                plt.close(fig)  # 明确关闭图形
                self._record_stage('png_visualization', visualization_started)
                
                logger.info(f"成功创建可视化图片: {output_path}")
                return True
                
            except Exception as plot_error:
                logger.error(f"绘制图像失败: {plot_error}")
                plt.close(fig)  # 确保关闭图形
                return False
                
        except Exception as e:
            logger.error(f"创建可视化失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def save_result(self, index_data, output_path):
        """保存计算结果为GeoTIFF文件"""
        try:
            if index_data is None:
                logger.warning("没有数据来保存")
                return False
            
            # 检查数据是否包含有效值
            if np.all(np.isnan(index_data)):
                logger.warning("所有数据都是NaN，无法保存")
                return False
            
            # 检查数据形状
            if not hasattr(index_data, 'shape'):
                logger.warning("数据没有shape属性")
                return False
            
            if len(index_data.shape) != 2:
                logger.warning(f"数据形状不正确，期望2D数组，实际为{index_data.shape}")
                return False
            
            # 检查数据是否为空
            if index_data.size == 0:
                logger.warning("数据数组为空")
                return False
            
            # 检查元数据
            if not self.metadata:
                logger.warning("没有元数据，无法保存")
                return False
            
            # 创建输出元数据
            output_meta = self.metadata.copy()
            output_meta.update({
                'count': 1,
                'dtype': 'float32',
                'nodata': np.nan,
            })
            output_meta.update(self.output_options)
            
            # 确保输出目录存在
            output_dir = os.path.dirname(output_path)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)
                logger.info(f"创建输出目录: {output_dir}")
            
            # 保存文件
            try:
                # 明确指定使用GeoTIFF格式，支持Float32数据类型
                output_meta['driver'] = 'GTiff'
                
                write_started = time.perf_counter()
                with rasterio.open(output_path, 'w', **output_meta) as dst:
                    # 按输出 tile 写入，避免 index_data.astype('float32') 再生成一张
                    # 全幅副本；科学结果仍是完整分辨率 Float32 GeoTIFF。
                    for row_off in range(0, index_data.shape[0], 512):
                        for col_off in range(0, index_data.shape[1], 512):
                            height = min(512, index_data.shape[0] - row_off)
                            width = min(512, index_data.shape[1] - col_off)
                            window = rasterio.windows.Window(col_off, row_off, width, height)
                            dst.write(index_data[row_off:row_off + height, col_off:col_off + width], 1, window=window)
                self._record_stage('geotiff_write', write_started)
                
                logger.info(f"成功保存结果文件: {output_path}")
                return True
                
            except Exception as write_error:
                logger.error(f"写入文件失败: {write_error}")
                return False
                
        except Exception as e:
            logger.error(f"保存结果失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def close(self):
        """关闭数据集"""
        try:
            if hasattr(self, 'dataset') and self.dataset is not None:
                self.dataset.close()
                logger.info("数据集已关闭")
            
            # 清理其他资源
            if hasattr(self, 'bands'):
                del self.bands
                self.bands = None
                self._scaled_band_cache = {}
                self._sensor_band_mapping = None
            
            if hasattr(self, 'metadata'):
                del self.metadata
                self.metadata = None
                
            logger.info("计算器资源已清理")
            
        except Exception as e:
            logger.error(f"关闭计算器时出错: {e}")
            import traceback
            traceback.print_exc() 
