"""Prepare a calibrated seven-band Landsat C2 L2 raster for real GIS benchmarks."""

from contextlib import ExitStack
from pathlib import Path
import re

import rasterio
from django.core.management.base import BaseCommand, CommandError


REFLECTIVE_BANDS = ('B2', 'B3', 'B4', 'B5', 'B6', 'B7')
DESCRIPTIONS = ('SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7', 'ST_B10')


class Command(BaseCommand):
    help = '将真实 Landsat C2 L2 SR_B2..B7 与 ST_B10 按窗口合成为校准的 7 波段 GeoTIFF。'

    def add_arguments(self, parser):
        parser.add_argument('--source-dir', required=True, help='包含 Landsat *_SR_B2.TIF..*_SR_B7.TIF、*_ST_B10.TIF 和 MTL.txt 的目录')
        parser.add_argument('--output', required=True, help='输出七波段 GeoTIFF 的绝对或相对路径')

    def handle(self, *args, **options):
        source_dir = Path(options['source_dir']).expanduser().resolve()
        output = Path(options['output']).expanduser().resolve()
        if not source_dir.is_dir():
            raise CommandError(f'源目录不存在：{source_dir}')
        if output.exists():
            raise CommandError(f'输出已存在，拒绝覆盖：{output}')

        def find_one(pattern):
            matches = list(source_dir.glob(pattern))
            if len(matches) != 1:
                raise CommandError(f'未找到唯一的 {pattern}：{source_dir}')
            return matches[0]

        source_paths = [find_one(f'*_SR_{band}.TIF') for band in REFLECTIVE_BANDS]
        source_paths.append(find_one('*_ST_B10.TIF'))
        mtl_path = find_one('*_MTL.txt')
        mtl = mtl_path.read_text(encoding='utf-8', errors='replace')

        def mtl_number(key):
            match = re.search(rf'^\s*{re.escape(key)}\s*=\s*([-+0-9.eE]+)', mtl, re.MULTILINE)
            if not match:
                raise CommandError(f'MTL 中缺少参数：{key}')
            return float(match.group(1))

        reflective_scale = mtl_number('REFLECTANCE_MULT_BAND_2')
        reflective_offset = mtl_number('REFLECTANCE_ADD_BAND_2')
        temperature_scale = mtl_number('TEMPERATURE_MULT_BAND_ST_B10')
        temperature_offset = mtl_number('TEMPERATURE_ADD_BAND_ST_B10')

        output.parent.mkdir(parents=True, exist_ok=True)
        with ExitStack() as stack:
            datasets = [stack.enter_context(rasterio.open(path)) for path in source_paths]
            reference = datasets[0]
            for path, dataset in zip(source_paths[1:], datasets[1:]):
                if (
                    dataset.width != reference.width
                    or dataset.height != reference.height
                    or dataset.crs != reference.crs
                    or dataset.transform != reference.transform
                ):
                    raise CommandError(f'栅格网格与 B2 不一致：{path}')

            profile = reference.profile.copy()
            profile.update(
                driver='GTiff',
                count=len(datasets),
                dtype=reference.dtypes[0],
                nodata=0,
                tiled=True,
                blockxsize=256,
                blockysize=256,
                compress='deflate',
                predictor=2,
                BIGTIFF='IF_SAFER',
            )
            with rasterio.open(output, 'w', **profile) as destination:
                for _, window in reference.block_windows(1):
                    for index, dataset in enumerate(datasets, start=1):
                        destination.write(dataset.read(1, window=window), index, window=window)
                destination.descriptions = DESCRIPTIONS
                destination.scales = (reflective_scale,) * 6 + (temperature_scale,)
                destination.offsets = (reflective_offset,) * 6 + (temperature_offset,)
                destination.update_tags(
                    LANDSAT_PRODUCT_ID=re.search(r'LANDSAT_PRODUCT_ID\s*=\s*"([^"]+)"', mtl).group(1),
                    PROCESSING_LEVEL='L2SP',
                    BAND_MAPPING='blue=SR_B2,green=SR_B3,red=SR_B4,nir=SR_B5,swir1=SR_B6,swir2=SR_B7,thermal=ST_B10',
                    THERMAL_UNITS='kelvin',
                    SOURCE_MTL=str(mtl_path),
                )

        self.stdout.write(self.style.SUCCESS(f'已生成真实 Landsat 七波段基准栅格：{output}'))
