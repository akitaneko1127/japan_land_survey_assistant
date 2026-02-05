# -*- coding: utf-8 -*-
"""G空間情報センター CKAN API 経由で登記所備付地図（GeoJSON）を取得."""

import json
import os
import re
from typing import List, Dict, Optional, Tuple
from urllib.request import urlopen, Request

from qgis.core import (
    QgsVectorLayer, QgsMessageLog, Qgis,
    QgsVectorFileWriter, QgsCoordinateTransformContext,
    QgsVectorSimplifyMethod,
)


CKAN_API = 'https://www.geospatial.jp/ckan/api/3/action/package_show'
GSI_REVERSE_GEOCODER = (
    'https://mreversegeocoder.gsi.go.jp/reverse-geocoder/LonLatToAddress'
)


class MojGeoJsonDownloader:
    """登記所備付地図 GeoJSON のダウンロード・読込."""

    @staticmethod
    def _log(msg, level=Qgis.Info):
        QgsMessageLog.logMessage(msg, 'JLSA-MojGeoJson', level)

    # ------------------------------------------------------------------
    # GSI 逆ジオコーダー → 市区町村コード
    # ------------------------------------------------------------------

    def resolve_city_code(self, lat: float, lon: float) -> Optional[str]:
        """GSI逆ジオコーダーで市区町村コード(5桁)を取得.

        最大3回リトライし、タイムアウト耐性を高めている。

        Returns:
            '13104' 等の市区町村コード文字列、または None
        """
        url = f'{GSI_REVERSE_GEOCODER}?lat={lat}&lon={lon}'
        last_error = None
        for attempt in range(3):
            try:
                timeout = 8 if attempt == 0 else 15
                req = Request(url, headers={
                    'User-Agent': 'JLSA-QGISPlugin/1.0'})
                with urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                results = data.get('results', {})
                muniCd = results.get('muniCd', '')
                if muniCd:
                    self._log(f'市区町村コード: {muniCd} (lat={lat}, lon={lon})')
                    return muniCd
                self._log(
                    f'逆ジオコーダー: コード未取得 response={data}',
                    Qgis.Warning)
                return None
            except Exception as e:
                last_error = e
                self._log(
                    f'逆ジオコーダー リトライ {attempt + 1}/3: {e}',
                    Qgis.Warning)
        self._log(f'逆ジオコーダー 全リトライ失敗: {last_error}', Qgis.Warning)
        return None

    # ------------------------------------------------------------------
    # CKAN API → GeoJSON リソース一覧
    # ------------------------------------------------------------------

    def get_geojson_resources(self, city_code: str) -> List[Dict]:
        """CKAN API から市区町村コードに対応するGeoJSONリソース一覧を取得.

        Returns:
            [{'url': '...', 'name': '...', 'format': '...', ...}, ...]
        """
        package_id = f'aigid-moj-{city_code}'
        url = f'{CKAN_API}?id={package_id}'
        self._log(f'CKAN API 呼出: {url}')
        try:
            req = Request(url, headers={'User-Agent': 'JLSA-QGISPlugin/1.0'})
            with urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            if not data.get('success'):
                self._log(f'CKAN API 失敗: {data}', Qgis.Warning)
                return []
            resources = data.get('result', {}).get('resources', [])
            # GeoJSON のみフィルタ
            geojson_resources = [
                r for r in resources
                if r.get('format', '').upper() == 'GEOJSON'
                or r.get('url', '').lower().endswith('.geojson')
            ]
            self._log(f'GeoJSONリソース {len(geojson_resources)} 件取得')
            return geojson_resources
        except Exception as e:
            self._log(f'CKAN API エラー: {e}', Qgis.Warning)
            return []

    # ------------------------------------------------------------------
    # 最新年度の GeoJSON を選択
    # ------------------------------------------------------------------

    def select_latest_geojson(
        self, resources: List[Dict], preferred_year: str = ''
    ) -> Optional[Tuple[str, str]]:
        """リソース一覧から最新（または指定年度）のGeoJSON URLを選択.

        Returns:
            (url, year) タプル、または None
        """
        if not resources:
            return None

        # 年度を抽出してソート
        year_pattern = re.compile(r'(\d{4})')
        candidates = []
        for r in resources:
            url = r.get('url', '')
            name = r.get('name', '') or url
            match = year_pattern.search(name)
            year = match.group(1) if match else '0000'
            candidates.append((year, url, name))

        if not candidates:
            return None

        # 指定年度があればフィルタ
        if preferred_year:
            filtered = [(y, u, n) for y, u, n in candidates if y == preferred_year]
            if filtered:
                candidates = filtered

        # 最新年度を選択
        candidates.sort(key=lambda x: x[0], reverse=True)
        year, url, name = candidates[0]
        self._log(f'選択: {name} (年度={year})')
        return (url, year)

    # ------------------------------------------------------------------
    # ダウンロード
    # ------------------------------------------------------------------

    def download_geojson(self, url: str, dest_path: str) -> str:
        """GeoJSON をダウンロードしてローカルに保存.

        Returns:
            保存先パス
        """
        self._log(f'ダウンロード開始: {url}')
        req = Request(url, headers={'User-Agent': 'JLSA-QGISPlugin/1.0'})
        with urlopen(req, timeout=120) as resp:
            with open(dest_path, 'wb') as f:
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
        self._log(f'ダウンロード完了: {dest_path}')
        return dest_path

    # ------------------------------------------------------------------
    # GeoJSON → GeoPackage 変換（空間インデックス付き）
    # ------------------------------------------------------------------

    def convert_to_gpkg(self, geojson_path: str) -> Optional[str]:
        """GeoJSON を GeoPackage に変換して空間インデックスを作成.

        GeoJSON はR-tree空間インデックスを持たないため描画が遅い。
        GeoPackage(SQLite) に変換することでR-tree内蔵となり
        パン・ズーム時の描画が大幅に高速化する。

        Returns:
            変換後の .gpkg パス、または失敗時 None
        """
        gpkg_path = os.path.splitext(geojson_path)[0] + '.gpkg'
        if os.path.exists(gpkg_path):
            self._log(f'GPKG 既存: {gpkg_path}')
            return gpkg_path

        # 一旦 GeoJSON を OGR レイヤとして開く
        tmp_layer = QgsVectorLayer(geojson_path, 'tmp', 'ogr')
        if not tmp_layer.isValid():
            self._log(f'GeoJSON 読込失敗（変換元）: {geojson_path}', Qgis.Warning)
            return None

        # GeoPackage として書き出し
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = 'GPKG'
        opts.fileEncoding = 'UTF-8'

        err, msg, _, _ = QgsVectorFileWriter.writeAsVectorFormatV3(
            tmp_layer, gpkg_path,
            QgsCoordinateTransformContext(), opts,
        )
        if err != QgsVectorFileWriter.NoError:
            self._log(f'GPKG 変換失敗: {msg}', Qgis.Warning)
            return None

        self._log(f'GPKG 変換完了: {gpkg_path}')
        return gpkg_path

    # ------------------------------------------------------------------
    # レイヤ化
    # ------------------------------------------------------------------

    def load_as_layer(
        self, geojson_path: str, layer_name: str = ''
    ) -> Optional[QgsVectorLayer]:
        """GeoJSON を GeoPackage に変換してから QgsVectorLayer として読込.

        GeoPackage 変換により空間インデックスが利用可能になり
        描画パフォーマンスが大幅に向上する。

        Returns:
            有効なレイヤ、または None
        """
        if not layer_name:
            layer_name = os.path.splitext(os.path.basename(geojson_path))[0]

        # GeoPackage に変換（空間インデックス付き）
        gpkg_path = self.convert_to_gpkg(geojson_path)
        load_path = gpkg_path if gpkg_path else geojson_path

        layer = QgsVectorLayer(load_path, layer_name, 'ogr')
        if not layer.isValid():
            self._log(f'レイヤ読込失敗: {load_path}', Qgis.Warning)
            return None

        # 空間インデックスを明示的に作成（GPKG は通常自動だが念のため）
        dp = layer.dataProvider()
        if dp.capabilities() & dp.CreateSpatialIndex:
            dp.createSpatialIndex()

        # 縮尺依存描画: 1:25000 より広域ではポリゴンを描画しない
        layer.setScaleBasedVisibility(True)
        layer.setMinimumScale(25000)
        layer.setMaximumScale(0)

        # レンダリング時のジオメトリ簡略化を有効化
        simplify = QgsVectorSimplifyMethod()
        simplify.setSimplifyHints(
            QgsVectorSimplifyMethod.GeometrySimplification
        )
        simplify.setThreshold(1.0)  # ピクセル単位
        simplify.setForceLocalOptimization(True)
        layer.setSimplifyMethod(simplify)

        self._log(
            f'レイヤ読込成功: {layer_name} ({layer.featureCount()} features)'
            f' [GPKG={"○" if gpkg_path else "×"}, 縮尺制限=1:25000]'
        )
        return layer

    # ------------------------------------------------------------------
    # 一括処理: 座標 → DL → レイヤ化
    # ------------------------------------------------------------------

    def fetch_and_load(
        self,
        lat: float,
        lon: float,
        preferred_year: str = '',
        cache_manager=None,
    ) -> Optional[QgsVectorLayer]:
        """マップ中心座標から登記所備付地図を自動取得してレイヤ化.

        Args:
            lat: 緯度 (EPSG:4326)
            lon: 経度 (EPSG:4326)
            preferred_year: 希望年度 (空文字で最新)
            cache_manager: CacheManager インスタンス

        Returns:
            QgsVectorLayer or None
        """
        # 1. 市区町村コード取得
        city_code = self.resolve_city_code(lat, lon)
        if not city_code:
            raise ValueError('市区町村コードを取得できませんでした。')

        # 2. キャッシュ確認（GPKG 優先）
        cache_key_gpkg = f'moj_gpkg_{city_code}_{preferred_year or "latest"}'
        cache_key_json = f'moj_geojson_{city_code}_{preferred_year or "latest"}'
        if cache_manager:
            cached_gpkg = cache_manager.get_cached_file(cache_key_gpkg)
            if cached_gpkg:
                self._log(f'キャッシュ使用(GPKG): {cached_gpkg}')
                return self.load_as_layer(cached_gpkg, f'登記所備付地図_{city_code}')
            cached_json = cache_manager.get_cached_file(cache_key_json)
            if cached_json:
                self._log(f'キャッシュ使用(GeoJSON): {cached_json}')
                return self.load_as_layer(cached_json, f'登記所備付地図_{city_code}')

        # 3. CKAN API でリソース一覧取得
        resources = self.get_geojson_resources(city_code)
        if not resources:
            raise ValueError(
                f'市区町村コード {city_code} のGeoJSONデータが見つかりません。'
            )

        # 4. 最新年度選択
        result = self.select_latest_geojson(resources, preferred_year)
        if not result:
            raise ValueError('適切なGeoJSONリソースが見つかりません。')
        url, year = result

        # 5. ダウンロード
        if cache_manager:
            download_dir = cache_manager.get_download_dir()
        else:
            download_dir = os.path.join(os.path.expanduser('~'), '.jlsa_tmp')
            os.makedirs(download_dir, exist_ok=True)

        dest = os.path.join(download_dir, f'moj_{city_code}_{year}.geojson')
        self.download_geojson(url, dest)

        # 6. キャッシュ登録（GeoJSON）
        if cache_manager:
            cache_manager.register(
                cache_key_json, dest,
                city_code=city_code, year=year, source='ckan'
            )

        # 7. レイヤ化（内部で GPKG 変換される）
        layer = self.load_as_layer(dest, f'登記所備付地図_{city_code}_{year}')

        # 8. GPKG もキャッシュ登録
        gpkg_path = os.path.splitext(dest)[0] + '.gpkg'
        if cache_manager and os.path.exists(gpkg_path):
            cache_manager.register(
                cache_key_gpkg, gpkg_path,
                city_code=city_code, year=year, source='ckan_gpkg'
            )

        return layer
