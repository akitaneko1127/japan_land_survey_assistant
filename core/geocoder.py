# -*- coding: utf-8 -*-
"""HeartRails Geo API ジオコーダー."""

import json
from typing import List, Dict, Optional
from urllib.request import urlopen, Request
from urllib.parse import quote

from qgis.core import QgsMessageLog, Qgis, QgsPointXY

API_BASE = 'https://geoapi.heartrails.com/api/json'


class Geocoder:
    """Geocoding via HeartRails Geo API (free, no key required)."""

    @staticmethod
    def _log(msg, level=Qgis.Info):
        QgsMessageLog.logMessage(msg, 'JLSA-Geocoder', level)

    def geocode(self, address: str) -> List[Dict]:
        """Address → coordinates.

        Returns list of dicts with keys:
            prefecture, city, town, x (lon), y (lat), postal
        """
        url = f'{API_BASE}?method=suggest&matching=like&keyword={quote(address)}'
        return self._fetch(url)

    def reverse_geocode(self, lon: float, lat: float) -> List[Dict]:
        """Coordinates → address."""
        url = f'{API_BASE}?method=searchByGeoLocation&x={lon}&y={lat}'
        return self._fetch(url)

    def geocode_to_point(self, address: str) -> Optional[QgsPointXY]:
        """Return the first geocode result as a QgsPointXY."""
        results = self.geocode(address)
        if results:
            r = results[0]
            try:
                return QgsPointXY(float(r['x']), float(r['y']))
            except (KeyError, ValueError):
                pass
        return None

    # ------------------------------------------------------------------
    # GSI 逆ジオコーダー（市区町村コード取得用）
    # ------------------------------------------------------------------

    def resolve_city_code(self, lon: float, lat: float) -> Optional[str]:
        """GSI逆ジオコーダーで市区町村コード(5桁)を取得.

        最大3回リトライし、タイムアウト耐性を高めている。

        Returns:
            '13104' 等の市区町村コード文字列、または None
        """
        url = (
            'https://mreversegeocoder.gsi.go.jp/reverse-geocoder'
            f'/LonLatToAddress?lat={lat}&lon={lon}'
        )
        last_error = None
        for attempt in range(3):
            try:
                timeout = 8 if attempt == 0 else 15
                req = Request(url, headers={
                    'User-Agent': 'JLSA-QGISPlugin/1.0'})
                with urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                results = data.get('results', {})
                code = results.get('muniCd', '')
                if code:
                    self._log(f'GSI逆ジオコーダー: 市区町村コード={code}')
                    return code
                self._log(f'GSI逆ジオコーダー: コード未取得', Qgis.Warning)
                return None
            except Exception as e:
                last_error = e
                self._log(
                    f'GSI逆ジオコーダー リトライ {attempt + 1}/3: {e}',
                    Qgis.Warning)
        self._log(f'GSI逆ジオコーダー 全リトライ失敗: {last_error}', Qgis.Warning)
        return None

    # ------------------------------------------------------------------

    def _fetch(self, url: str) -> List[Dict]:
        try:
            req = Request(url, headers={'User-Agent': 'JLSA-QGISPlugin/1.0'})
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            locations = data.get('response', {}).get('location', [])
            if isinstance(locations, dict):
                locations = [locations]
            return locations
        except Exception as e:
            self._log(f'Geocoder error: {e}', Qgis.Warning)
            return []
