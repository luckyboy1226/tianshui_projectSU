"""
使用GDAL进行土地利用分析和生态环境指数计算
包括生态环境结构指数和生态环境胁迫指数
"""

import numpy as np
from osgeo import gdal, osr
import matplotlib
matplotlib.use('Agg')  # 使用非交互式后端
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.colors import ListedColormap

# 设置中文字体支持
plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans', 'Arial Unicode MS', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题
import os
import json
import pandas as pd
from scipy import ndimage
from sklearn.cluster import KMeans
import logging

# 设置GDAL错误处理
gdal.UseExceptions()

logger = logging.getLogger(__name__)

# Landscape-connectivity calculations allocate several arrays of the same size.
# Keeping the longest analysis dimension bounded prevents a single uploaded TIFF
# from exhausting the deployment machine while still retaining a useful spatial
# resolution for interactive analysis.
MAX_ANALYSIS_SIDE = 4096


class LandUseAnalyzer:
    """土地利用分析器"""
    
    def __init__(self, landuse_path):
        """
        初始化土地利用分析器
        
        Args:
            landuse_path: 土地利用分类栅格文件路径
        """
        self.landuse_path = landuse_path
        self.dataset = None
        self.landuse_data = None
        self.geotransform = None
        self.projection = None
        self.source_width = None
        self.source_height = None
        self.analysis_scale_x = 1.0
        self.analysis_scale_y = 1.0
        
        # 土地利用分类定义
        self.landuse_classes = {
            1: {'name': '耕地', 'color': '#FFFF00', 'fragility': 0.3},
            2: {'name': '林地', 'color': '#228B22', 'fragility': 0.1},
            3: {'name': '草地', 'color': '#90EE90', 'fragility': 0.2},
            4: {'name': '水域', 'color': '#0000FF', 'fragility': 0.4},
            5: {'name': '建设用地', 'color': '#FF0000', 'fragility': 0.8},
            6: {'name': '未利用地', 'color': '#808080', 'fragility': 0.9},
            7: {'name': '湿地', 'color': '#00FFFF', 'fragility': 0.5},
            8: {'name': '园地', 'color': '#32CD32', 'fragility': 0.2}
        }
    
    def load_landuse_data(self):
        """加载土地利用数据"""
        try:
            self.dataset = gdal.Open(self.landuse_path, gdal.GA_ReadOnly)
            if self.dataset is None:
                raise ValueError(f"无法打开土地利用文件: {self.landuse_path}")
            
            # 获取基本信息
            self.geotransform = self.dataset.GetGeoTransform()
            self.projection = self.dataset.GetProjection()
            
            # 获取影像尺寸
            self.source_width = self.dataset.RasterXSize
            self.source_height = self.dataset.RasterYSize
            self.width = self.source_width
            self.height = self.source_height
            
            # 读取土地利用数据
            band = self.dataset.GetRasterBand(1)
            longest_side = max(self.source_width, self.source_height)
            if longest_side > MAX_ANALYSIS_SIDE:
                scale = int(np.ceil(longest_side / MAX_ANALYSIS_SIDE))
                self.width = max(1, int(np.ceil(self.source_width / scale)))
                self.height = max(1, int(np.ceil(self.source_height / scale)))
                self.analysis_scale_x = self.source_width / self.width
                self.analysis_scale_y = self.source_height / self.height
                # Nearest-neighbour keeps the land-use category values intact.
                self.landuse_data = band.ReadAsArray(
                    buf_xsize=self.width,
                    buf_ysize=self.height,
                    resample_alg=gdal.GRIORA_NearestNeighbour,
                ).astype(np.int32)
                gt = self.geotransform
                self.geotransform = (
                    gt[0], gt[1] * self.analysis_scale_x, gt[2],
                    gt[3], gt[4], gt[5] * self.analysis_scale_y,
                )
                logger.warning(
                    '土地利用数据过大，已按最近邻重采样用于交互分析: %sx%s -> %sx%s',
                    self.source_width, self.source_height, self.width, self.height,
                )
            else:
                self.landuse_data = band.ReadAsArray().astype(np.int32)
            
            # 获取无效值
            self.no_data_value = band.GetNoDataValue()
            if self.no_data_value is not None:
                self.landuse_data[self.landuse_data == self.no_data_value] = -9999
            
            logger.info(f"成功加载土地利用数据: {self.landuse_path}")
            logger.info(f"分析数据尺寸: {self.width} x {self.height}")
            return True
            
        except Exception as e:
            logger.error(f"加载土地利用数据失败: {e}")
            return False
    
    def get_landuse_statistics(self):
        """获取土地利用统计信息"""
        try:
            if self.landuse_data is None:
                raise ValueError("土地利用数据未加载")
            
            # 计算各类面积
            total_pixels = self.landuse_data.size
            valid_pixels = np.sum(self.landuse_data != -9999)
            
            # 获取像素面积（平方米）
            pixel_width = abs(self.geotransform[1])
            pixel_height = abs(self.geotransform[5])
            pixel_area = pixel_width * pixel_height
            
            # 统计各类面积
            class_stats = {}
            for class_id, class_info in self.landuse_classes.items():
                class_pixels = np.sum(self.landuse_data == class_id)
                class_area = class_pixels * pixel_area / 1000000  # 转换为平方公里
                class_ratio = class_pixels / valid_pixels * 100
                
                class_stats[class_id] = {
                    'name': class_info['name'],
                    'color': class_info['color'],
                    'pixels': int(class_pixels),
                    'area_km2': float(class_area),
                    'ratio_percent': float(class_ratio),
                    'fragility': class_info['fragility']
                }
            
            # 总体统计
            total_stats = {
                'total_pixels': int(total_pixels),
                'valid_pixels': int(valid_pixels),
                'pixel_area_m2': float(pixel_area),
                'total_area_km2': float(valid_pixels * pixel_area / 1000000),
                'classes': class_stats
            }
            
            return total_stats
            
        except Exception as e:
            logger.error(f"计算土地利用统计信息失败: {e}")
            return None
    
    def calculate_fragmentation_index(self):
        """
        计算破碎度指数
        反映景观破碎化程度
        """
        try:
            if self.landuse_data is None:
                raise ValueError("土地利用数据未加载")
            
            # 创建有效数据掩膜
            valid_mask = self.landuse_data != -9999
            
            # 计算斑块数量
            labeled_array, num_features = ndimage.label(valid_mask)
            
            # 计算总面积
            total_area = np.sum(valid_mask)
            
            # 计算破碎度指数
            if total_area > 0:
                fragmentation_index = (num_features - 1) / (num_features - 1 + np.sqrt(total_area / total_area))
            else:
                fragmentation_index = 0
            
            # 按土地利用类型计算破碎度
            class_fragmentation = {}
            for class_id, class_info in self.landuse_classes.items():
                class_mask = self.landuse_data == class_id
                if np.sum(class_mask) > 0:
                    labeled_class, num_patches = ndimage.label(class_mask)
                    class_area = np.sum(class_mask)
                    
                    if num_patches > 1:
                        class_fi = (num_patches - 1) / (num_patches - 1 + np.sqrt(class_area / total_area))
                    else:
                        class_fi = 0
                    
                    class_fragmentation[class_id] = {
                        'name': class_info['name'],
                        'patches': int(num_patches),
                        'area': int(class_area),
                        'fragmentation_index': float(class_fi)
                    }
            
            return {
                'overall_fragmentation': float(fragmentation_index),
                'total_patches': int(num_features),
                'total_area': int(total_area),
                'class_fragmentation': class_fragmentation
            }
            
        except Exception as e:
            logger.error(f"计算破碎度指数失败: {e}")
            return None
    
    def calculate_cohesion_index(self):
        """
        计算内聚力指数
        反映景观连通性
        """
        try:
            if self.landuse_data is None:
                raise ValueError("土地利用数据未加载")
            
            # 创建有效数据掩膜
            valid_mask = self.landuse_data != -9999
            
            # 计算斑块面积
            labeled_array, num_features = ndimage.label(valid_mask)
            
            if num_features == 0:
                return {'cohesion_index': 0.0}
            
            # np.bincount avoids scanning the whole raster once per patch.
            patch_areas = np.bincount(labeled_array.ravel())[1:]
            total_area = np.sum(patch_areas)
            
            # 计算内聚力指数
            if total_area > 0:
                # 简化的内聚力计算
                cohesion_index = (1 - np.sum(patch_areas / np.sqrt(patch_areas * total_area))) * 100
                cohesion_index = max(0, min(100, cohesion_index))  # 限制在[0, 100]范围
            else:
                cohesion_index = 0
            
            return {
                'cohesion_index': float(cohesion_index),
                'total_patches': int(num_features),
                'total_area': int(total_area),
                # Returning every patch area can create a response with millions
                # of values.  The aggregate index and patch count are sufficient
                # for the web UI and keep the API response bounded.
                'largest_patch_area': int(patch_areas.max()) if patch_areas.size else 0,
                'mean_patch_area': float(patch_areas.mean()) if patch_areas.size else 0.0,
            }
            
        except Exception as e:
            logger.error(f"计算内聚力指数失败: {e}")
            return None
    
    def calculate_diversity_index(self):
        """
        计算多样性指数（Shannon多样性指数）
        反映土地利用类型的多样性
        """
        try:
            if self.landuse_data is None:
                raise ValueError("土地利用数据未加载")
            
            # 统计各类面积
            class_counts = {}
            valid_pixels = 0
            
            for class_id in self.landuse_classes.keys():
                count = np.sum(self.landuse_data == class_id)
                if count > 0:
                    class_counts[class_id] = count
                    valid_pixels += count
            
            if valid_pixels == 0:
                return {'shannon_diversity': 0.0, 'simpson_diversity': 0.0}
            
            # 计算Shannon多样性指数
            shannon_diversity = 0.0
            simpson_diversity = 0.0
            
            for class_id, count in class_counts.items():
                pi = count / valid_pixels
                if pi > 0:
                    shannon_diversity -= pi * np.log(pi)
                    simpson_diversity += pi * pi
            
            # Simpson多样性指数
            simpson_diversity = 1 - simpson_diversity
            
            # 计算Pielou均匀度指数
            max_shannon = np.log(len(class_counts))
            if max_shannon > 0:
                pielou_evenness = shannon_diversity / max_shannon
            else:
                pielou_evenness = 0
            
            return {
                'shannon_diversity': float(shannon_diversity),
                'simpson_diversity': float(simpson_diversity),
                'pielou_evenness': float(pielou_evenness),
                'class_count': len(class_counts),
                'total_pixels': int(valid_pixels),
                'class_proportions': {str(k): float(v/valid_pixels) for k, v in class_counts.items()}
            }
            
        except Exception as e:
            logger.error(f"计算多样性指数失败: {e}")
            return None
    
    def calculate_fragility_index(self):
        """
        计算脆弱度指数
        反映生态系统对环境变化的敏感程度
        """
        try:
            if self.landuse_data is None:
                raise ValueError("土地利用数据未加载")
            
            # 统计各类面积
            class_areas = {}
            total_valid_area = 0
            
            for class_id, class_info in self.landuse_classes.items():
                area = np.sum(self.landuse_data == class_id)
                if area > 0:
                    class_areas[class_id] = {
                        'area': area,
                        'fragility': class_info['fragility']
                    }
                    total_valid_area += area
            
            if total_valid_area == 0:
                return {'fragility_index': 0.0}
            
            # 计算脆弱度指数
            fragility_index = 0.0
            class_fragility = {}
            
            for class_id, info in class_areas.items():
                pi = info['area'] / total_valid_area
                fragility_index += pi * info['fragility']
                
                class_fragility[class_id] = {
                    'name': self.landuse_classes[class_id]['name'],
                    'area': int(info['area']),
                    'proportion': float(pi),
                    'fragility': float(info['fragility']),
                    'contribution': float(pi * info['fragility'])
                }
            
            return {
                'fragility_index': float(fragility_index),
                'total_area': int(total_valid_area),
                'class_fragility': class_fragility
            }
            
        except Exception as e:
            logger.error(f"计算脆弱度指数失败: {e}")
            return None
    
    def calculate_soil_erosion_index(self, slope_path=None, rainfall_path=None):
        """
        计算土壤侵蚀指数
        基于RUSLE模型简化版本
        
        Args:
            slope_path: 坡度数据路径（可选）
            rainfall_path: 降雨数据路径（可选）
        """
        try:
            if self.landuse_data is None:
                raise ValueError("土地利用数据未加载")
            
            # 简化的土壤侵蚀指数计算
            # 基于土地利用类型的侵蚀敏感性
            
            erosion_sensitivity = {
                1: 0.3,  # 耕地 - 中等敏感
                2: 0.1,  # 林地 - 低敏感
                3: 0.2,  # 草地 - 低敏感
                4: 0.0,  # 水域 - 无侵蚀
                5: 0.8,  # 建设用地 - 高敏感
                6: 0.9,  # 未利用地 - 极高敏感
                7: 0.1,  # 湿地 - 低敏感
                8: 0.3   # 园地 - 中等敏感
            }
            
            # 计算侵蚀指数
            total_area = 0
            erosion_sum = 0
            class_erosion = {}
            
            for class_id, sensitivity in erosion_sensitivity.items():
                area = np.sum(self.landuse_data == class_id)
                if area > 0:
                    total_area += area
                    erosion_sum += area * sensitivity
                    
                    class_erosion[class_id] = {
                        'name': self.landuse_classes[class_id]['name'],
                        'area': int(area),
                        'sensitivity': float(sensitivity),
                        'erosion_contribution': float(area * sensitivity)
                    }
            
            if total_area == 0:
                return {'soil_erosion_index': 0.0}
            
            soil_erosion_index = erosion_sum / total_area
            
            return {
                'soil_erosion_index': float(soil_erosion_index),
                'total_area': int(total_area),
                'class_erosion': class_erosion
            }
            
        except Exception as e:
            logger.error(f"计算土壤侵蚀指数失败: {e}")
            return None
    
    def calculate_unused_land_ratio(self):
        """计算未利用地面积比例"""
        try:
            if self.landuse_data is None:
                raise ValueError("土地利用数据未加载")
            
            # 未利用地类别ID
            unused_land_classes = [6]  # 未利用地
            
            total_valid_area = np.sum(self.landuse_data != -9999)
            unused_area = 0
            
            for class_id in unused_land_classes:
                unused_area += np.sum(self.landuse_data == class_id)
            
            if total_valid_area == 0:
                return {'unused_land_ratio': 0.0}
            
            unused_land_ratio = unused_area / total_valid_area * 100
            
            return {
                'unused_land_ratio': float(unused_land_ratio),
                'unused_area': int(unused_area),
                'total_area': int(total_valid_area)
            }
            
        except Exception as e:
            logger.error(f"计算未利用地比例失败: {e}")
            return None
    
    def calculate_development_ratio(self):
        """计算耕地、建设用地面积比例"""
        try:
            if self.landuse_data is None:
                raise ValueError("土地利用数据未加载")
            
            # 开发用地类别
            development_classes = {
                1: '耕地',
                5: '建设用地'
            }
            
            total_valid_area = np.sum(self.landuse_data != -9999)
            development_area = 0
            class_development = {}
            
            for class_id, class_name in development_classes.items():
                area = np.sum(self.landuse_data == class_id)
                if area > 0:
                    development_area += area
                    class_development[class_id] = {
                        'name': class_name,
                        'area': int(area),
                        'ratio': float(area / total_valid_area * 100)
                    }
            
            if total_valid_area == 0:
                return {'development_ratio': 0.0}
            
            development_ratio = development_area / total_valid_area * 100
            
            return {
                'development_ratio': float(development_ratio),
                'development_area': int(development_area),
                'total_area': int(total_valid_area),
                'class_development': class_development
            }
            
        except Exception as e:
            logger.error(f"计算开发用地比例失败: {e}")
            return None
    
    def calculate_land_degradation_index(self):
        """计算土地退化指数"""
        try:
            if self.landuse_data is None:
                raise ValueError("土地利用数据未加载")
            
            # 土地退化敏感性权重
            degradation_sensitivity = {
                1: 0.4,  # 耕地 - 中等退化风险
                2: 0.1,  # 林地 - 低退化风险
                3: 0.2,  # 草地 - 低退化风险
                4: 0.0,  # 水域 - 无退化
                5: 0.9,  # 建设用地 - 高退化
                6: 1.0,  # 未利用地 - 极高退化
                7: 0.3,  # 湿地 - 中等退化风险
                8: 0.4   # 园地 - 中等退化风险
            }
            
            total_area = 0
            degradation_sum = 0
            class_degradation = {}
            
            for class_id, sensitivity in degradation_sensitivity.items():
                area = np.sum(self.landuse_data == class_id)
                if area > 0:
                    total_area += area
                    degradation_sum += area * sensitivity
                    
                    class_degradation[class_id] = {
                        'name': self.landuse_classes[class_id]['name'],
                        'area': int(area),
                        'sensitivity': float(sensitivity),
                        'degradation_contribution': float(area * sensitivity)
                    }
            
            if total_area == 0:
                return {'land_degradation_index': 0.0}
            
            land_degradation_index = degradation_sum / total_area
            
            return {
                'land_degradation_index': float(land_degradation_index),
                'total_area': int(total_area),
                'class_degradation': class_degradation
            }
            
        except Exception as e:
            logger.error(f"计算土地退化指数失败: {e}")
            return None
    
    def create_landuse_visualization(self, output_path):
        """创建土地利用可视化图片"""
        try:
            if self.landuse_data is None:
                raise ValueError("土地利用数据未加载")
            
            # 创建输出目录
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # 准备数据
            masked_data = np.ma.masked_where(self.landuse_data == -9999, self.landuse_data)
            
            # 创建颜色映射
            colors_list = []
            labels = []
            
            for class_id, class_info in self.landuse_classes.items():
                colors_list.append(class_info['color'])
                labels.append(f"{class_id}: {class_info['name']}")
            
            cmap = ListedColormap(colors_list)
            cmap = cmap.copy()
            cmap.set_bad((1, 1, 1, 0))
            
            # 创建图形：左侧独立图例，中间分布图，右侧面积比例图，避免图例压在图上。
            fig = plt.figure(figsize=(16, 8), facecolor='white')
            gs = fig.add_gridspec(
                1,
                3,
                width_ratios=[0.26, 1.12, 0.9],
                left=0.04,
                right=0.98,
                top=0.88,
                bottom=0.12,
                wspace=0.08,
            )
            ax_legend = fig.add_subplot(gs[0, 0])
            ax1 = fig.add_subplot(gs[0, 1])
            ax2 = fig.add_subplot(gs[0, 2])
            
            # 主图：土地利用分布
            im1 = ax1.imshow(masked_data, cmap=cmap, vmin=1, vmax=len(self.landuse_classes), interpolation='nearest')
            ax1.set_title('土地利用分布图', fontsize=14, fontweight='bold', pad=12)
            ax1.axis('off')
            
            stats = self.get_landuse_statistics()

            # 左侧图例：独立展示，减少对地图和饼图的遮挡。
            ax_legend.axis('off')
            legend_elements = []
            for class_id, class_info in self.landuse_classes.items():
                ratio = None
                if stats and class_id in stats.get('classes', {}):
                    ratio = stats['classes'][class_id].get('ratio_percent')
                suffix = f"  {ratio:.1f}%" if ratio is not None else ""
                legend_elements.append(
                    patches.Patch(color=class_info['color'], label=f"{class_id}: {class_info['name']}{suffix}")
                )
            if legend_elements:
                ax_legend.legend(
                    handles=legend_elements,
                    loc='center left',
                    ncol=1,
                    frameon=True,
                    facecolor='white',
                    edgecolor='#d8dee8',
                    fontsize=9,
                    labelspacing=0.8,
                    handlelength=1.2,
                    borderpad=0.8
                )
            
            # 子图：面积比例饼图
            if stats:
                areas = []
                colors_pie = []
                
                for class_id, class_info in self.landuse_classes.items():
                    if class_id in stats['classes']:
                        area = stats['classes'][class_id]['area_km2']
                        if area > 0:
                            areas.append(area)
                            colors_pie.append(class_info['color'])
                
                if areas:
                    wedges, texts = ax2.pie(
                        areas,
                        labels=None,
                        colors=colors_pie,
                        autopct=None,
                        startangle=90,
                        counterclock=False,
                        radius=0.92,
                        wedgeprops={'linewidth': 0.8, 'edgecolor': 'white'}
                    )
                    ax2.set_title('土地利用面积比例', fontsize=14, fontweight='bold', pad=12)
                    ax2.axis('equal')
            
            plt.savefig(output_path, dpi=220, bbox_inches='tight', pad_inches=0.12)
            plt.close(fig)
            
            logger.info(f"土地利用可视化图片已保存到: {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"创建土地利用可视化失败: {e}")
            return False
    
    def calculate_all_indices(self, output_dir):
        """计算所有生态环境指数"""
        try:
            # 创建输出目录
            os.makedirs(output_dir, exist_ok=True)
            
            # 计算各种指数
            results = {}
            
            # 基础统计
            landuse_stats = self.get_landuse_statistics()
            if landuse_stats:
                results['landuse_statistics'] = landuse_stats
            
            # 生态环境结构指数
            fragmentation = self.calculate_fragmentation_index()
            if fragmentation:
                results['fragmentation_index'] = fragmentation
            
            cohesion = self.calculate_cohesion_index()
            if cohesion:
                results['cohesion_index'] = cohesion
            
            diversity = self.calculate_diversity_index()
            if diversity:
                results['diversity_index'] = diversity
            
            fragility = self.calculate_fragility_index()
            if fragility:
                results['fragility_index'] = fragility
            
            # 生态环境胁迫指数
            soil_erosion = self.calculate_soil_erosion_index()
            if soil_erosion:
                results['soil_erosion_index'] = soil_erosion
            
            unused_land = self.calculate_unused_land_ratio()
            if unused_land:
                results['unused_land_ratio'] = unused_land
            
            development = self.calculate_development_ratio()
            if development:
                results['development_ratio'] = development
            
            land_degradation = self.calculate_land_degradation_index()
            if land_degradation:
                results['land_degradation_index'] = land_degradation
            
            # 保存结果
            results_path = os.path.join(output_dir, 'land_use_analysis_results.json')
            with open(results_path, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False, default=str)
            
            # 创建可视化
            vis_path = os.path.join(output_dir, 'land_use_visualization.png')
            self.create_landuse_visualization(vis_path)
            
            logger.info(f"所有指数计算完成，结果保存在: {output_dir}")
            return results
            
        except Exception as e:
            logger.error(f"计算所有指数失败: {e}")
            return None
    
    def close(self):
        """关闭数据集"""
        if self.dataset is not None:
            self.dataset = None
            logger.info("数据集已关闭")


def analyze_landuse(landuse_path, output_dir):
    """
    土地利用分析的便捷函数
    
    Args:
        landuse_path: 土地利用分类栅格文件路径
        output_dir: 输出目录
    """
    try:
        # 创建分析器
        analyzer = LandUseAnalyzer(landuse_path)
        
        # 加载数据
        if not analyzer.load_landuse_data():
            raise ValueError("无法加载土地利用数据")
        
        # 计算所有指数
        results = analyzer.calculate_all_indices(output_dir)
        
        # 关闭分析器
        analyzer.close()
        
        return results
        
    except Exception as e:
        logger.error(f"土地利用分析失败: {e}")
        return None


if __name__ == "__main__":
    # 测试代码
    import sys
    
    if len(sys.argv) != 3:
        print("用法: python gdal_land_use_analysis.py <landuse_raster> <output_dir>")
        sys.exit(1)
    
    landuse_path = sys.argv[1]
    output_dir = sys.argv[2]
    
    # 设置日志
    logging.basicConfig(level=logging.INFO)
    
    # 进行土地利用分析
    results = analyze_landuse(landuse_path, output_dir)
    
    if results:
        print("分析完成！")
        for index_name, stats in results.items():
            print(f"\n{index_name}:")
            if isinstance(stats, dict):
                for key, value in stats.items():
                    if isinstance(value, dict):
                        print(f"  {key}:")
                        for sub_key, sub_value in value.items():
                            print(f"    {sub_key}: {sub_value}")
                    else:
                        print(f"  {key}: {value}")
    else:
        print("分析失败！") 
