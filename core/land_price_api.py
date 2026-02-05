# -*- coding: utf-8 -*-
"""不動産情報ライブラリ API client."""

import json
import math
from typing import List, Optional, Dict
from urllib.request import urlopen, Request

from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsField,
    QgsPointXY, QgsMessageLog, Qgis,
    QgsMarkerSymbol,
)
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtCore import QMetaType

API_BASE = 'https://www.reinfolib.mlit.go.jp/ex-api/external'


class LandPriceApiClient:
    """Client for the Real Estate Information Library API."""

    @staticmethod
    def _log(msg, level=Qgis.Info):
        QgsMessageLog.logMessage(msg, 'JLSA-LandPrice', level)

    def __init__(self, api_key: str = ''):
        self.api_key = api_key

    # ------------------------------------------------------------------
    # Tile-based retrieval
    # ------------------------------------------------------------------

    def fetch_land_prices(self, z: int, x: int, y: int,
                          year: int = 2024,
                          price_classification: Optional[int] = None,
                          ) -> Optional[dict]:
        """Fetch land price GeoJSON for a map tile.

        price_classification: 0=地価公示, 1=都道府県地価調査, None=両方
        """
        url = (f'{API_BASE}/XPT002?response_format=geojson'
               f'&z={z}&x={x}&y={y}&year={year}')
        if price_classification is not None:
            url += f'&priceClassification={price_classification}'
        self._log(f'API URL: {url}')
        return self._fetch_json(url)

    def fetch_prices_for_extent(self, xmin: float, ymin: float,
                                xmax: float, ymax: float,
                                zoom: int = 13,
                                year: int = 2024,
                                price_classification: Optional[int] = None,
                                ) -> List[dict]:
        """Fetch land prices covering a bounding box (EPSG:4326 coords).

        price_classification: 0=地価公示, 1=都道府県地価調査, None=両方
        """
        self._log(f'fetch_prices_for_extent: extent=({xmin:.6f}, {ymin:.6f}, '
                  f'{xmax:.6f}, {ymax:.6f}), zoom={zoom}, year={year}, '
                  f'priceClassification={price_classification}')

        tiles = self._extent_to_tiles(xmin, ymin, xmax, ymax, zoom)
        self._log(f'タイル数: {len(tiles)}')
        if len(tiles) > 100:
            self._log(f'タイル数が多すぎます ({len(tiles)})。zoom を下げてください。', Qgis.Warning)
            tiles = tiles[:100]

        all_features = []
        seen_ids = set()

        for i, (tx, ty) in enumerate(tiles):
            self._log(f'タイル取得中 [{i+1}/{len(tiles)}]: z={zoom}, x={tx}, y={ty}')
            data = self.fetch_land_prices(zoom, tx, ty, year, price_classification)
            if data and 'features' in data:
                count = len(data['features'])
                self._log(f'  → {count} features取得')
                for feat in data['features']:
                    fid = feat.get('properties', {}).get('id', id(feat))
                    if fid not in seen_ids:
                        seen_ids.add(fid)
                        all_features.append(feat)
            elif data:
                self._log(f'  → featuresキーなし。レスポンスキー: {list(data.keys())}')
            else:
                self._log('  → レスポンスなし (None)')

        self._log(f'合計: {len(all_features)} features (重複除外済)')
        return all_features

    # ------------------------------------------------------------------
    # Layer creation
    # ------------------------------------------------------------------

    def create_point_layer(self, geojson_features: List[dict],
                           layer_name: str = '地価情報') -> Optional[QgsVectorLayer]:
        """Convert GeoJSON features to a QGIS point layer."""
        if not geojson_features:
            return None

        layer = QgsVectorLayer('Point?crs=EPSG:4326', layer_name, 'memory')
        prov = layer.dataProvider()

        # Detect fields from first feature
        sample_props = geojson_features[0].get('properties', {})
        fields = []
        for key, val in sample_props.items():
            if isinstance(val, (int, float)):
                fields.append(QgsField(key, QMetaType.Type.Double))
            else:
                fields.append(QgsField(key, QMetaType.Type.QString))
        prov.addAttributes(fields)
        layer.updateFields()

        # Add features
        qgs_feats = []
        for gf in geojson_features:
            geom_data = gf.get('geometry', {})
            coords = geom_data.get('coordinates', [])
            if len(coords) >= 2:
                feat = QgsFeature(layer.fields())
                feat.setGeometry(QgsGeometry.fromPointXY(
                    QgsPointXY(float(coords[0]), float(coords[1]))
                ))
                props = gf.get('properties', {})
                for f in layer.fields():
                    feat.setAttribute(f.name(), props.get(f.name()))
                qgs_feats.append(feat)

        prov.addFeatures(qgs_feats)
        layer.updateExtents()

        # マーカースタイル: 大きめの丸で視認性向上
        symbol = QgsMarkerSymbol.createSimple({
            'name': 'circle',
            'size': '8',
            'color': '#e74c3c',
            'outline_color': '#ffffff',
            'outline_width': '0.8',
        })
        layer.renderer().setSymbol(symbol)

        self._log(f'Created land price layer with {len(qgs_feats)} points')
        return layer

    # ------------------------------------------------------------------
    # Tile math
    # ------------------------------------------------------------------

    def _extent_to_tiles(self, xmin, ymin, xmax, ymax, zoom):
        """Convert geographic extent (EPSG:4326) to tile coordinates."""

        # Clamp latitude to valid Mercator range
        ymin = max(-85.0511, min(85.0511, ymin))
        ymax = max(-85.0511, min(85.0511, ymax))
        # Clamp longitude
        xmin = max(-180.0, min(180.0, xmin))
        xmax = max(-180.0, min(180.0, xmax))

        self._log(f'_extent_to_tiles: clamped extent=({xmin:.6f}, {ymin:.6f}, '
                  f'{xmax:.6f}, {ymax:.6f}), zoom={zoom}')

        def lon_to_tile_x(lon, z):
            return int((lon + 180.0) / 360.0 * (1 << z))

        def lat_to_tile_y(lat, z):
            lat_rad = math.radians(lat)
            n = 1 << z
            return int((1.0 - math.log(
                math.tan(lat_rad) + 1.0 / math.cos(lat_rad)
            ) / math.pi) / 2.0 * n)

        tx_min = lon_to_tile_x(xmin, zoom)
        tx_max = lon_to_tile_x(xmax, zoom)
        ty_min = lat_to_tile_y(ymax, zoom)  # y is inverted
        ty_max = lat_to_tile_y(ymin, zoom)

        self._log(f'タイル範囲: tx=[{tx_min}..{tx_max}], ty=[{ty_min}..{ty_max}]')

        tiles = []
        for tx in range(tx_min, tx_max + 1):
            for ty in range(ty_min, ty_max + 1):
                tiles.append((tx, ty))
        return tiles

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def _fetch_json(self, url: str) -> Optional[dict]:
        try:
            headers = {'User-Agent': 'JLSA-QGISPlugin/1.0'}
            if self.api_key:
                headers['Ocp-Apim-Subscription-Key'] = self.api_key
            req = Request(url, headers=headers)
            with urlopen(req, timeout=30) as resp:
                status = resp.getcode()
                body = resp.read().decode('utf-8')
                self._log(f'HTTP {status}, body length={len(body)}')
                data = json.loads(body)
                return data
        except Exception as e:
            self._log(f'API error [{type(e).__name__}]: {e}', Qgis.Warning)
            self._log(f'  URL: {url}', Qgis.Warning)
            return None
