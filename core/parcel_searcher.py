# -*- coding: utf-8 -*-
"""地番検索エンジン."""

from typing import List, Optional, Dict

from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsFeatureRequest,
    QgsRectangle, QgsPointXY, QgsExpression, QgsGeometry,
    QgsMessageLog, Qgis,
)


class ParcelSearcher:
    """Search parcels on a loaded vector layer."""

    @staticmethod
    def _log(msg, level=Qgis.Info):
        QgsMessageLog.logMessage(msg, 'JLSA-Search', level)

    # ------------------------------------------------------------------
    # Attribute search
    # ------------------------------------------------------------------

    def search_by_parcel_number(self, layer: QgsVectorLayer,
                                parcel_number: str,
                                oaza: str = '',
                                aza: str = '') -> List[QgsFeature]:
        """Search features by parcel number and optional oaza/aza."""
        if not layer or not layer.isValid():
            return []

        expr_parts = []
        # Match parcel number (地番)
        expr_parts.append(f'"地番" = \'{self._escape(parcel_number)}\'')
        if oaza:
            expr_parts.append(f'"大字名" = \'{self._escape(oaza)}\'')
        if aza:
            expr_parts.append(f'"字名" = \'{self._escape(aza)}\'')

        expression = ' AND '.join(expr_parts)
        request = QgsFeatureRequest(QgsExpression(expression))
        return list(layer.getFeatures(request))

    def search_like(self, layer: QgsVectorLayer,
                    keyword: str) -> List[QgsFeature]:
        """Fuzzy search by keyword on 地番, 大字名, 字名."""
        if not layer or not layer.isValid() or not keyword:
            return []

        kw = self._escape(keyword)
        expr = (
            f'"地番" LIKE \'%{kw}%\' OR '
            f'"大字名" LIKE \'%{kw}%\' OR '
            f'"字名" LIKE \'%{kw}%\''
        )
        request = QgsFeatureRequest(QgsExpression(expr))
        request.setLimit(100)
        return list(layer.getFeatures(request))

    # ------------------------------------------------------------------
    # Spatial search (map click)
    # ------------------------------------------------------------------

    def search_by_point(self, layer: QgsVectorLayer,
                        point: QgsPointXY,
                        buffer: float = 0.0) -> Optional[QgsFeature]:
        """Find the parcel containing the given point.

        buffer が 0 の場合、レイヤの CRS に応じて自動設定:
        地理座標系 (度) → 0.0005° ≒ 約55m
        投影座標系 (m)  → 50m
        """
        if not layer or not layer.isValid():
            return None

        if buffer <= 0.0:
            buffer = 0.0005 if layer.crs().isGeographic() else 50.0

        rect = QgsRectangle(
            point.x() - buffer, point.y() - buffer,
            point.x() + buffer, point.y() + buffer,
        )
        request = QgsFeatureRequest().setFilterRect(rect)

        # 1st pass: exact contain check
        for feature in layer.getFeatures(request):
            if feature.geometry().contains(point):
                return feature

        # 2nd pass: nearest feature by distance
        pt_geom = QgsGeometry.fromPointXY(point)
        nearest = None
        nearest_dist = float('inf')
        for feature in layer.getFeatures(request):
            dist = feature.geometry().distance(pt_geom)
            if dist < nearest_dist:
                nearest_dist = dist
                nearest = feature

        return nearest

    # ------------------------------------------------------------------
    # Layer introspection
    # ------------------------------------------------------------------

    @staticmethod
    def get_unique_oaza(layer: QgsVectorLayer) -> List[str]:
        """Get unique 大字名 values from a layer."""
        if not layer or not layer.isValid():
            return []
        idx = layer.fields().indexOf('大字名')
        if idx < 0:
            return []
        return sorted(set(
            str(v) for v in layer.uniqueValues(idx) if v
        ))

    @staticmethod
    def get_unique_aza(layer: QgsVectorLayer,
                       oaza: str = '') -> List[str]:
        """Get unique 字名 values, optionally filtered by 大字名."""
        if not layer or not layer.isValid():
            return []
        idx = layer.fields().indexOf('字名')
        if idx < 0:
            return []

        if oaza:
            expr = QgsExpression(f'"大字名" = \'{oaza}\'')
            request = QgsFeatureRequest(expr)
            values = set()
            for feat in layer.getFeatures(request):
                v = feat.attribute('字名')
                if v:
                    values.add(str(v))
            return sorted(values)

        return sorted(set(
            str(v) for v in layer.uniqueValues(idx) if v
        ))

    # ------------------------------------------------------------------
    # Feature info extraction
    # ------------------------------------------------------------------

    @staticmethod
    def feature_to_dict(feature: QgsFeature) -> Dict:
        """Extract attribute dict from a feature."""
        info = {}
        for field in feature.fields():
            info[field.name()] = feature.attribute(field.name())
        return info

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _escape(val: str) -> str:
        return val.replace("'", "''")
