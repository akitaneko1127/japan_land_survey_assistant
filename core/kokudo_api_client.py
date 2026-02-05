# -*- coding: utf-8 -*-
"""国土数値情報ダウンロードクライアント.

旧 Web API (nlftp.mlit.go.jp/ksj/api/) は廃止されたため、
直接ダウンロード URL を構築してデータを取得する。
"""

import os
import zipfile
from typing import List, Optional, Callable
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

from qgis.core import QgsVectorLayer, QgsMessageLog, Qgis


# Supported datasets
# year_style: '4digit' = 2024, '2digit' = 24
# date_suffix: N03 uses '0101' after year
# scope: 'pref' = per-prefecture, 'national' = single national file
KOKUDO_DATASETS = {
    'N03': {
        'name': '行政区域', 'category': '行政',
        'year_style': '4digit', 'date_suffix': '0101', 'scope': 'pref',
        'years': ['2025', '2024', '2023', '2022'],
    },
    'L01': {
        'name': '地価公示', 'category': '地価',
        'year_style': '2digit', 'date_suffix': '', 'scope': 'pref',
        'years': ['2021', '2020', '2019', '2018'],
    },
    'L02': {
        'name': '都道府県地価調査', 'category': '地価',
        'year_style': '2digit', 'date_suffix': '', 'scope': 'pref',
        'years': ['2021', '2020', '2019', '2018'],
    },
    'N02': {
        'name': '鉄道', 'category': '交通',
        'year_style': '2digit', 'date_suffix': '', 'scope': 'national',
        'years': ['2022', '2021', '2020', '2019'],
    },
    'A31': {
        'name': '洪水浸水想定区域', 'category': '災害',
        'year_style': '2digit', 'date_suffix': '', 'scope': 'bureau',
        'years': ['2020', '2019', '2018', '2017'],
    },
    'A33': {
        'name': '土砂災害警戒区域', 'category': '災害',
        'year_style': '2digit', 'date_suffix': '', 'scope': 'pref',
        'years': ['2020', '2019', '2018', '2017'],
    },
}

DL_BASE = 'https://nlftp.mlit.go.jp/ksj/gml/data'

# 都道府県コード → 地方整備局コード (A31 洪水浸水想定区域用)
PREF_TO_BUREAU = {
    '01': '81',  # 北海道開発局
    '02': '82', '03': '82', '04': '82', '05': '82', '06': '82', '07': '82',  # 東北
    '08': '83', '09': '83', '10': '83', '11': '83', '12': '83', '13': '83', '14': '83',  # 関東
    '15': '84', '16': '84', '17': '84', '18': '84',  # 北陸
    '19': '85', '20': '85', '21': '85', '22': '85', '23': '85',  # 中部
    '24': '86', '25': '86', '26': '86', '27': '86', '28': '86', '29': '86', '30': '86',  # 近畿
    '31': '87', '32': '87', '33': '87', '34': '87', '35': '87',  # 中国
    '36': '88', '37': '88', '38': '88', '39': '88',  # 四国
    '40': '89', '41': '89', '42': '89', '43': '89', '44': '89',
    '45': '89', '46': '89', '47': '89',  # 九州・沖縄
}


class KokudoApiClient:
    """Client for National Land Numerical Information direct downloads."""

    @staticmethod
    def _log(msg, level=Qgis.Info):
        QgsMessageLog.logMessage(msg, 'JLSA-Kokudo', level)

    @staticmethod
    def get_datasets() -> dict:
        return dict(KOKUDO_DATASETS)

    # ------------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------------

    def _build_candidate_urls(self, dataset_id: str, pref_code: str,
                               fiscal_year: str = '') -> List[str]:
        """Build candidate download URLs for a dataset + prefecture.

        各年度について SHP版 と GML版 の両方を候補に入れる。
        SHP版 を先に試行する（QGISでの読込が確実）。
        bureauスコープの場合は整備局コードも使用する。
        """
        ds = KOKUDO_DATASETS.get(dataset_id)
        if not ds:
            return []

        year_style = ds.get('year_style', '2digit')
        date_suffix = ds.get('date_suffix', '')
        scope = ds.get('scope', 'pref')
        default_years = ds.get('years', ['2024', '2023', '2022'])

        if fiscal_year:
            years_to_try = [fiscal_year]
        else:
            years_to_try = list(default_years)

        # bureauスコープ: 整備局コードを使用
        if scope == 'bureau':
            area_code = PREF_TO_BUREAU.get(pref_code, pref_code)
        else:
            area_code = pref_code

        urls = []
        for year_4 in years_to_try:
            if year_style == '4digit':
                yr = year_4
            else:
                yr = year_4[-2:]

            dir_yr = yr

            if scope == 'national':
                base = f'{dataset_id}-{yr}{date_suffix}'
            else:
                base = f'{dataset_id}-{yr}{date_suffix}_{area_code}'

            # SHP版を優先、次にGML版
            for fmt in ('SHP', 'GML'):
                fn = f'{base}_{fmt}.zip'
                url = f'{DL_BASE}/{dataset_id}/{dataset_id}-{dir_yr}/{fn}'
                urls.append(url)

        return urls

    def _find_download_url(self, dataset_id: str, pref_code: str,
                            fiscal_year: str = '') -> Optional[str]:
        """Try candidate URLs with HEAD requests, return the first valid one."""
        candidates = self._build_candidate_urls(dataset_id, pref_code,
                                                 fiscal_year)
        for url in candidates:
            self._log(f'URL 試行: {url}')
            try:
                req = Request(url, method='HEAD',
                              headers={'User-Agent': 'JLSA-QGISPlugin/1.0'})
                with urlopen(req, timeout=8) as resp:
                    if resp.status == 200:
                        self._log(f'URL 発見: {url}')
                        return url
            except Exception:
                continue
        return None

    # ------------------------------------------------------------------
    # Download & Load
    # ------------------------------------------------------------------

    def _resolve_area_codes(self, dataset_id: str,
                             pref_codes: List[str]) -> List[str]:
        """都道府県コードを実際のダウンロード用コードに変換.

        bureauスコープの場合、整備局コードに変換し重複除去する。
        """
        ds = KOKUDO_DATASETS.get(dataset_id, {})
        scope = ds.get('scope', 'pref')

        if scope == 'bureau':
            seen = set()
            area_codes = []
            for pref in pref_codes:
                bureau = PREF_TO_BUREAU.get(pref, pref)
                if bureau not in seen:
                    seen.add(bureau)
                    area_codes.append(bureau)
            return area_codes
        return list(pref_codes)

    def download_dataset(self, dataset_id: str, pref_codes: List[str],
                         fiscal_year: str = '',
                         cache_manager=None,
                         progress_callback: Optional[Callable] = None) -> List[QgsVectorLayer]:
        """Download and load dataset as QGIS layers."""
        ds = KOKUDO_DATASETS.get(dataset_id)
        if not ds:
            self._log(f'Unknown dataset: {dataset_id}', Qgis.Warning)
            return []

        # National datasets: single download regardless of pref selection
        if ds.get('scope') == 'national':
            return self._download_national(dataset_id, pref_codes,
                                            fiscal_year, cache_manager,
                                            progress_callback)

        # bureauスコープの場合、整備局コードに変換（重複除去）
        area_codes = self._resolve_area_codes(dataset_id, pref_codes)
        layers = []
        total = len(area_codes)

        for idx, area in enumerate(area_codes):
            if progress_callback:
                progress_callback(idx, total)

            # Check cache
            cache_key = f'kokudo_{dataset_id}_{area}_{fiscal_year}'
            cached = cache_manager.get_cached_file(cache_key) if cache_manager else None
            if cached:
                self._log(f'Using cached file for {dataset_id}/{area}')
                layer = self._load_shapefile_dir(cached, dataset_id, area)
                if layer:
                    layers.append(layer)
                continue

            # Find download URL via direct URL probing
            dl_url = self._find_download_url(dataset_id, area, fiscal_year)
            if not dl_url:
                self._log(f'No download URL for {dataset_id}/{area}', Qgis.Warning)
                continue

            # Download
            download_dir = (cache_manager.get_download_dir()
                            if cache_manager
                            else os.path.join(os.path.expanduser('~'), '.jlsa_tmp'))
            os.makedirs(download_dir, exist_ok=True)
            zip_path = os.path.join(download_dir, f'{dataset_id}_{area}.zip')

            try:
                self._download_file(dl_url, zip_path)
            except Exception as e:
                self._log(f'Download error: {e}', Qgis.Warning)
                continue

            # Extract
            extract_dir = os.path.join(download_dir, f'{dataset_id}_{area}')
            os.makedirs(extract_dir, exist_ok=True)
            try:
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    zf.extractall(extract_dir)
            except Exception as e:
                self._log(f'Extract error: {e}', Qgis.Warning)
                continue

            # Register in cache
            if cache_manager:
                cache_manager.register(cache_key, extract_dir,
                                       dataset=dataset_id, pref=area)

            # Load layer
            layer = self._load_shapefile_dir(extract_dir, dataset_id, area)
            if layer:
                layers.append(layer)

        if progress_callback:
            progress_callback(total, total)

        return layers

    def _download_national(self, dataset_id: str, pref_codes: List[str],
                            fiscal_year: str, cache_manager,
                            progress_callback) -> List[QgsVectorLayer]:
        """Download a national-scope dataset (single file, not per-pref)."""
        if progress_callback:
            progress_callback(0, 1)

        cache_key = f'kokudo_{dataset_id}_national_{fiscal_year}'
        cached = cache_manager.get_cached_file(cache_key) if cache_manager else None
        if cached:
            self._log(f'Using cached file for {dataset_id}/national')
            layer = self._load_shapefile_dir(cached, dataset_id, 'national')
            if progress_callback:
                progress_callback(1, 1)
            return [layer] if layer else []

        # Use empty pref code for national URL
        dl_url = self._find_download_url(dataset_id, '', fiscal_year)
        if not dl_url:
            self._log(f'No download URL for {dataset_id}/national', Qgis.Warning)
            if progress_callback:
                progress_callback(1, 1)
            return []

        download_dir = (cache_manager.get_download_dir()
                        if cache_manager
                        else os.path.join(os.path.expanduser('~'), '.jlsa_tmp'))
        os.makedirs(download_dir, exist_ok=True)
        zip_path = os.path.join(download_dir, f'{dataset_id}_national.zip')

        try:
            self._download_file(dl_url, zip_path)
        except Exception as e:
            self._log(f'Download error: {e}', Qgis.Warning)
            if progress_callback:
                progress_callback(1, 1)
            return []

        extract_dir = os.path.join(download_dir, f'{dataset_id}_national')
        os.makedirs(extract_dir, exist_ok=True)
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(extract_dir)
        except Exception as e:
            self._log(f'Extract error: {e}', Qgis.Warning)
            if progress_callback:
                progress_callback(1, 1)
            return []

        if cache_manager:
            cache_manager.register(cache_key, extract_dir,
                                   dataset=dataset_id, pref='national')

        layer = self._load_shapefile_dir(extract_dir, dataset_id, 'national')
        if progress_callback:
            progress_callback(1, 1)
        return [layer] if layer else []

    # ------------------------------------------------------------------
    # Download only (thread-safe, no QgsVectorLayer creation)
    # ------------------------------------------------------------------

    def download_dataset_paths(self, dataset_id: str, pref_codes: List[str],
                                fiscal_year: str = '',
                                cache_manager=None,
                                progress_callback: Optional[Callable] = None,
                                ) -> List[tuple]:
        """Download dataset and return (extract_dir, dataset_id, area_code) tuples.

        Does NOT create QgsVectorLayer — safe to call from worker threads.
        """
        ds = KOKUDO_DATASETS.get(dataset_id)
        if not ds:
            self._log(f'Unknown dataset: {dataset_id}', Qgis.Warning)
            return []

        if ds.get('scope') == 'national':
            result = self._download_national_path(
                dataset_id, fiscal_year, cache_manager, progress_callback)
            return [result] if result else []

        # bureauスコープの場合、整備局コードに変換（重複除去）
        area_codes = self._resolve_area_codes(dataset_id, pref_codes)
        results = []
        total = len(area_codes)

        for idx, area in enumerate(area_codes):
            if progress_callback:
                progress_callback(idx, total)

            cache_key = f'kokudo_{dataset_id}_{area}_{fiscal_year}'
            cached = (cache_manager.get_cached_file(cache_key)
                      if cache_manager else None)
            if cached:
                self._log(f'Using cached file for {dataset_id}/{area}')
                results.append((cached, dataset_id, area))
                continue

            dl_url = self._find_download_url(dataset_id, area, fiscal_year)
            if not dl_url:
                self._log(f'No download URL for {dataset_id}/{area}',
                          Qgis.Warning)
                continue

            download_dir = (cache_manager.get_download_dir()
                            if cache_manager
                            else os.path.join(os.path.expanduser('~'),
                                              '.jlsa_tmp'))
            os.makedirs(download_dir, exist_ok=True)
            zip_path = os.path.join(download_dir, f'{dataset_id}_{area}.zip')

            try:
                self._download_file(dl_url, zip_path)
            except Exception as e:
                self._log(f'Download error: {e}', Qgis.Warning)
                continue

            extract_dir = os.path.join(download_dir, f'{dataset_id}_{area}')
            os.makedirs(extract_dir, exist_ok=True)
            try:
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    zf.extractall(extract_dir)
            except Exception as e:
                self._log(f'Extract error: {e}', Qgis.Warning)
                continue

            if cache_manager:
                cache_manager.register(cache_key, extract_dir,
                                       dataset=dataset_id, pref=area)

            results.append((extract_dir, dataset_id, area))

        if progress_callback:
            progress_callback(total, total)

        return results

    def _download_national_path(self, dataset_id, fiscal_year,
                                 cache_manager, progress_callback):
        """Download national dataset, return (dir, id, 'national') or None."""
        if progress_callback:
            progress_callback(0, 1)

        cache_key = f'kokudo_{dataset_id}_national_{fiscal_year}'
        cached = (cache_manager.get_cached_file(cache_key)
                  if cache_manager else None)
        if cached:
            if progress_callback:
                progress_callback(1, 1)
            return (cached, dataset_id, 'national')

        dl_url = self._find_download_url(dataset_id, '', fiscal_year)
        if not dl_url:
            if progress_callback:
                progress_callback(1, 1)
            return None

        download_dir = (cache_manager.get_download_dir()
                        if cache_manager
                        else os.path.join(os.path.expanduser('~'),
                                          '.jlsa_tmp'))
        os.makedirs(download_dir, exist_ok=True)
        zip_path = os.path.join(download_dir, f'{dataset_id}_national.zip')

        try:
            self._download_file(dl_url, zip_path)
        except Exception as e:
            self._log(f'Download error: {e}', Qgis.Warning)
            if progress_callback:
                progress_callback(1, 1)
            return None

        extract_dir = os.path.join(download_dir, f'{dataset_id}_national')
        os.makedirs(extract_dir, exist_ok=True)
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(extract_dir)
        except Exception as e:
            self._log(f'Extract error: {e}', Qgis.Warning)
            if progress_callback:
                progress_callback(1, 1)
            return None

        if cache_manager:
            cache_manager.register(cache_key, extract_dir,
                                   dataset=dataset_id, pref='national')
        if progress_callback:
            progress_callback(1, 1)
        return (extract_dir, dataset_id, 'national')

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _download_file(self, url: str, dest: str):
        req = Request(url, headers={'User-Agent': 'JLSA-QGISPlugin/1.0'})
        with urlopen(req, timeout=300) as resp:
            total_size = resp.headers.get('Content-Length')
            if total_size:
                total_size = int(total_size)
                self._log(f'ダウンロード開始: {url} ({total_size / 1024 / 1024:.1f} MB)')
            else:
                self._log(f'ダウンロード開始: {url}')
            downloaded = 0
            with open(dest, 'wb') as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
            self._log(f'ダウンロード完了: {dest} ({downloaded / 1024 / 1024:.1f} MB)')

    @staticmethod
    def _load_shapefile_dir(directory: str, dataset_id: str,
                            pref_code: str) -> Optional[QgsVectorLayer]:
        """Find and load the first vector file in a directory.

        優先順: .shp → .geojson → .gml
        """
        log = lambda msg, lv=Qgis.Info: QgsMessageLog.logMessage(
            msg, 'JLSA-Kokudo', lv)

        found_files = []
        for root_dir, _dirs, files in os.walk(directory):
            for fn in files:
                found_files.append(fn)
        log(f'展開ディレクトリ内ファイル ({directory}): {found_files}')

        for ext in ('.shp', '.geojson', '.gml'):
            for root_dir, _dirs, files in os.walk(directory):
                for fn in files:
                    if fn.lower().endswith(ext):
                        path = os.path.join(root_dir, fn)
                        ds_info = KOKUDO_DATASETS.get(dataset_id, {})
                        name = f"{ds_info.get('name', dataset_id)}_{pref_code}"
                        layer = QgsVectorLayer(path, name, 'ogr')
                        if layer.isValid():
                            log(f'レイヤ読込成功: {fn} ({layer.featureCount()} features)')
                            return layer
                        else:
                            log(f'レイヤ読込失敗: {fn}', Qgis.Warning)
        log(f'読込可能なファイルが見つかりません: {directory}', Qgis.Warning)
        return None
