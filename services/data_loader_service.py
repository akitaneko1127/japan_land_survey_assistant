# -*- coding: utf-8 -*-
"""Integrated data loader service — delegates to plugins or built-in fallbacks."""

from qgis.core import QgsMessageLog, Qgis

from .plugin_bridge import PluginBridge
from .cache_manager import CacheManager


class DataLoaderService:
    """Unified interface for loading various data sources."""

    def __init__(self):
        self.bridge = PluginBridge()
        self.cache = CacheManager()

    @staticmethod
    def _log(msg, level=Qgis.Info):
        QgsMessageLog.logMessage(msg, 'JLSA-Loader', level)

    # ------------------------------------------------------------------
    # MOJ XML
    # ------------------------------------------------------------------

    def load_moj_xml(self, file_path: str,
                     include_arbitrary: bool = False,
                     include_outside: bool = False,
                     auto_style: bool = True):
        """Load MOJ XML file, preferring MOJXML Loader plugin if available."""
        if self.bridge.is_mojxml_loader_available():
            self._log('Loading MOJ XML via MOJXML Loader plugin')
            return self.bridge.load_moj_xml_via_plugin(
                file_path, include_arbitrary, include_outside
            )
        else:
            self._log('Loading MOJ XML via built-in parser')
            from ..core.moj_xml_loader import MojXmlLoader
            loader = MojXmlLoader()
            return loader.load(
                file_path,
                include_arbitrary=include_arbitrary,
                include_outside=include_outside,
                auto_style=auto_style,
            )

    # ------------------------------------------------------------------
    # 国土数値情報
    # ------------------------------------------------------------------

    def load_kokudo_data_paths(self, dataset_id: str, pref_codes: list,
                               fiscal_year: str = '',
                               progress_callback=None):
        """Download Kokudo data and return (dir, dataset_id, pref) tuples.

        Thread-safe: does not create QgsVectorLayer objects.
        """
        from ..core.kokudo_api_client import KokudoApiClient
        client = KokudoApiClient()
        return client.download_dataset_paths(
            dataset_id, pref_codes, fiscal_year,
            cache_manager=self.cache,
            progress_callback=progress_callback,
        )

    def load_kokudo_data(self, dataset_id: str, pref_codes: list,
                         fiscal_year: str = '',
                         progress_callback=None):
        """Download Kokudo data and return QgsVectorLayer list.

        Main thread only — creates QgsVectorLayer objects.
        """
        from ..core.kokudo_api_client import KokudoApiClient
        client = KokudoApiClient()
        results = client.download_dataset_paths(
            dataset_id, pref_codes, fiscal_year,
            cache_manager=self.cache,
            progress_callback=progress_callback,
        )
        layers = []
        for extract_dir, ds_id, pref in (results or []):
            layer = KokudoApiClient._load_shapefile_dir(
                extract_dir, ds_id, pref)
            if layer and layer.isValid():
                layers.append(layer)
        return layers

    # ------------------------------------------------------------------
    # 登記所備付地図（自動取得）
    # ------------------------------------------------------------------

    def load_moj_from_extent(self, lat: float, lon: float,
                             preferred_year: str = ''):
        """マップ中心座標から登記所備付地図GeoJSONを自動取得.

        Args:
            lat: 緯度 (EPSG:4326)
            lon: 経度 (EPSG:4326)
            preferred_year: 希望年度 (空文字で最新)

        Returns:
            QgsVectorLayer or None
        """
        from ..core.moj_geojson_downloader import MojGeoJsonDownloader
        self._log(f'登記所備付地図 自動取得: lat={lat}, lon={lon}, year={preferred_year}')
        downloader = MojGeoJsonDownloader()
        return downloader.fetch_and_load(
            lat, lon,
            preferred_year=preferred_year,
            cache_manager=self.cache,
        )

    # ------------------------------------------------------------------
    # 筆ポリゴン（オンライン表示 / FlatGeobuf）
    # ------------------------------------------------------------------

    FUDE_FGB_BASE = (
        'https://habs.rad.naro.go.jp/spatial_data/fudepoly47'
    )

    def load_fude_polygon_layer(self, pref_code: str):
        """農研機構 筆ポリゴン FlatGeobuf をオンラインで読込.

        /vsicurl/ 経由で HTTP Range Request を利用し、
        ファイル全体をダウンロードせずに必要な範囲のみ取得する。

        Args:
            pref_code: 都道府県コード (01-47)

        Returns:
            QgsVectorLayer or None
        """
        from qgis.core import QgsVectorLayer

        url = f'{self.FUDE_FGB_BASE}/fude_2022_{pref_code}.fgb'
        vsicurl_uri = f'/vsicurl/{url}'

        self._log(f'筆ポリゴン FlatGeobuf 読込: {vsicurl_uri}')
        layer = QgsVectorLayer(
            vsicurl_uri, f'筆ポリゴン_{pref_code}', 'ogr'
        )
        if not layer or not layer.isValid():
            self._log(
                f'筆ポリゴン FlatGeobuf 読込失敗: {vsicurl_uri}',
                Qgis.Warning,
            )
            return None

        self._log(
            f'筆ポリゴン読込成功: {layer.featureCount()} features'
        )
        return layer

    # ------------------------------------------------------------------
    # 行政区域データ直接ダウンロード（API廃止対応）
    # ------------------------------------------------------------------

    def download_admin_boundary(self, pref_code: str):
        """国土数値情報 行政区域(N03) を直接ダウンロードして読込.

        国土数値情報 Web API は廃止済みのため、
        直接ダウンロード URL を構築して取得する。

        Returns:
            QgsVectorLayer or None
        """
        import os
        import zipfile
        from urllib.request import urlopen, Request
        from qgis.core import QgsVectorLayer

        # キャッシュ確認
        cache_key = f'admin_N03_{pref_code}'
        cached = self.cache.get_cached_file(cache_key)
        if cached:
            self._log(f'行政区域キャッシュ使用: {cached}')
            return self._load_shp_from_dir(cached, f'行政区域_{pref_code}')

        # 直接ダウンロード URL（最新年度から順に試行）
        years = ['2025', '2024', '2023', '2022']
        dl_url = None
        for year in years:
            url = (
                f'https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03-{year}/'
                f'N03-{year}0101_{pref_code}_GML.zip'
            )
            self._log(f'行政区域 URL 試行: {url}')
            try:
                req = Request(url, method='HEAD',
                              headers={'User-Agent': 'JLSA-QGISPlugin/1.0'})
                with urlopen(req, timeout=15) as resp:
                    if resp.status == 200:
                        dl_url = url
                        self._log(f'行政区域 URL 発見: {url}')
                        break
            except Exception:
                continue

        if not dl_url:
            self._log('行政区域 ダウンロード URL が見つかりません', Qgis.Warning)
            return None

        # ダウンロード
        download_dir = self.cache.get_download_dir()
        zip_path = os.path.join(download_dir, f'N03_{pref_code}.zip')
        self._log(f'行政区域 ダウンロード開始: {dl_url}')
        req = Request(dl_url, headers={'User-Agent': 'JLSA-QGISPlugin/1.0'})
        with urlopen(req, timeout=120) as resp:
            with open(zip_path, 'wb') as f:
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
        self._log(f'行政区域 ダウンロード完了: {zip_path}')

        # 展開
        extract_dir = os.path.join(download_dir, f'N03_{pref_code}')
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(extract_dir)

        # キャッシュ登録
        self.cache.register(cache_key, extract_dir,
                            dataset='N03', pref=pref_code)

        return self._load_shp_from_dir(extract_dir, f'行政区域_{pref_code}')

    @staticmethod
    def _load_shp_from_dir(directory, name):
        """ディレクトリ内の最初の .shp を読込."""
        import os
        from qgis.core import QgsVectorLayer
        for root, _dirs, files in os.walk(directory):
            for fn in files:
                if fn.lower().endswith('.shp'):
                    shp_path = os.path.join(root, fn)
                    layer = QgsVectorLayer(shp_path, name, 'ogr')
                    if layer.isValid():
                        return layer
        return None

    @staticmethod
    def _find_shp_in_dir(directory):
        """ディレクトリ内の最初の .shp パスを返す (レイヤ作成なし)."""
        import os
        for root, _dirs, files in os.walk(directory):
            for fn in files:
                if fn.lower().endswith('.shp'):
                    return os.path.join(root, fn)
        return None

    def download_admin_boundary_path(self, pref_code: str):
        """行政区域データをダウンロードし、shpパスとレイヤ名を返す.

        ワーカースレッドから安全に呼べる (QgsVectorLayerを作成しない)。

        Returns:
            (shp_path, layer_name) or (None, None)
        """
        import os
        import zipfile
        from urllib.request import urlopen, Request

        layer_name = f'行政区域_{pref_code}'

        # キャッシュ確認
        cache_key = f'admin_N03_{pref_code}'
        cached = self.cache.get_cached_file(cache_key)
        if cached:
            self._log(f'行政区域キャッシュ使用: {cached}')
            shp = self._find_shp_in_dir(cached)
            return (shp, layer_name) if shp else (None, None)

        # 直接ダウンロード URL（最新年度から順に試行）
        years = ['2025', '2024', '2023', '2022']
        dl_url = None
        for year in years:
            url = (
                f'https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03-{year}/'
                f'N03-{year}0101_{pref_code}_GML.zip'
            )
            self._log(f'行政区域 URL 試行: {url}')
            try:
                req = Request(url, method='HEAD',
                              headers={'User-Agent': 'JLSA-QGISPlugin/1.0'})
                with urlopen(req, timeout=15) as resp:
                    if resp.status == 200:
                        dl_url = url
                        self._log(f'行政区域 URL 発見: {url}')
                        break
            except Exception:
                continue

        if not dl_url:
            self._log('行政区域 ダウンロード URL が見つかりません', Qgis.Warning)
            return None, None

        # ダウンロード
        download_dir = self.cache.get_download_dir()
        zip_path = os.path.join(download_dir, f'N03_{pref_code}.zip')
        self._log(f'行政区域 ダウンロード開始: {dl_url}')
        req = Request(dl_url, headers={'User-Agent': 'JLSA-QGISPlugin/1.0'})
        with urlopen(req, timeout=120) as resp:
            with open(zip_path, 'wb') as f:
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
        self._log(f'行政区域 ダウンロード完了: {zip_path}')

        # 展開
        extract_dir = os.path.join(download_dir, f'N03_{pref_code}')
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(extract_dir)

        # キャッシュ登録
        self.cache.register(cache_key, extract_dir,
                            dataset='N03', pref=pref_code)

        shp = self._find_shp_in_dir(extract_dir)
        return (shp, layer_name) if shp else (None, None)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def get_plugin_status(self) -> dict:
        return self.bridge.get_status_all()
