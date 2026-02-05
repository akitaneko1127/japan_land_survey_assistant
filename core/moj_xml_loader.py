# -*- coding: utf-8 -*-
"""MOJ XML loader — wraps parser and creates QGIS vector layers."""

from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsField, QgsFields,
    QgsCoordinateReferenceSystem, QgsMessageLog, Qgis,
)
from qgis.PyQt.QtCore import QVariant

from .moj_xml_parser import MojXmlParser

# Land category styling colours
LAND_CATEGORY_COLORS = {
    '田': '#a0d8a0', '畑': '#d8d8a0', '宅地': '#ffd8d8',
    '学校用地': '#d8a0d8', '鉄道用地': '#a0a0a0', '塩田': '#a0d8d8',
    '鉱泉地': '#d8a0a0', '池沼': '#a0a0d8', '山林': '#00a000',
    '牧場': '#a0ffa0', '原野': '#d8ffd8', '墓地': '#808080',
    '境内地': '#d8a080', '運河用地': '#80a0d8', '水道用地': '#80d8d8',
    '用悪水路': '#80d8a0', 'ため池': '#a0d8ff', '堤': '#d8d8d8',
    '井溝': '#a0a0ff', '保安林': '#008000', '公衆用道路': '#c0c0c0',
    '公園': '#80ff80', '雑種地': '#e0e0e0',
}

FIELD_DEFS = [
    ('地番', QVariant.String),
    ('大字コード', QVariant.String),
    ('大字名', QVariant.String),
    ('字コード', QVariant.String),
    ('字名', QVariant.String),
    ('地目', QVariant.String),
    ('地積', QVariant.Double),
    ('座標系', QVariant.String),
    ('精度区分', QVariant.String),
]


class MojXmlLoader:
    """Load MOJ XML into a QGIS memory layer (built-in fallback)."""

    @staticmethod
    def _log(msg, level=Qgis.Info):
        QgsMessageLog.logMessage(msg, 'JLSA-MojLoader', level)

    def load(self, file_path: str,
             include_arbitrary: bool = False,
             include_outside: bool = False,
             auto_style: bool = True) -> QgsVectorLayer:
        parser = MojXmlParser()
        features_data, epsg = parser.parse(
            file_path, include_arbitrary, include_outside
        )

        if not features_data:
            self._log('No features parsed', Qgis.Warning)
            return None

        # Create memory layer
        crs_str = f'EPSG:{epsg}' if epsg else 'EPSG:6668'
        uri = f'Polygon?crs={crs_str}'
        layer = QgsVectorLayer(uri, 'MOJ筆', 'memory')
        if not layer.isValid():
            self._log('Failed to create memory layer', Qgis.Critical)
            return None

        # Define fields
        fields = QgsFields()
        for name, vtype in FIELD_DEFS:
            fields.append(QgsField(name, vtype))
        layer.dataProvider().addAttributes(fields)
        layer.updateFields()

        # Add features
        qgs_features = []
        for fd in features_data:
            wkt = fd.get('geometry_wkt')
            if not wkt:
                continue
            feat = QgsFeature(layer.fields())
            geom = QgsGeometry.fromWkt(wkt)
            if geom.isNull():
                continue
            feat.setGeometry(geom)
            for name, _ in FIELD_DEFS:
                val = fd.get(name)
                if val is not None:
                    feat.setAttribute(name, val)
            qgs_features.append(feat)

        layer.dataProvider().addFeatures(qgs_features)
        layer.updateExtents()
        self._log(f'Created layer with {len(qgs_features)} features')

        if auto_style:
            self._apply_style(layer)

        return layer

    # ------------------------------------------------------------------
    # Styling
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_style(layer: QgsVectorLayer):
        """Apply categorised style by 地目."""
        from qgis.core import (
            QgsCategorizedSymbolRenderer, QgsRendererCategory,
            QgsFillSymbol, QgsSimpleFillSymbolLayer,
        )
        from qgis.PyQt.QtGui import QColor

        categories = []
        for cat_name, hex_color in LAND_CATEGORY_COLORS.items():
            symbol = QgsFillSymbol()
            sl = symbol.symbolLayer(0)
            if isinstance(sl, QgsSimpleFillSymbolLayer):
                fill = QColor(hex_color)
                fill.setAlpha(180)
                sl.setFillColor(fill)
                sl.setStrokeColor(QColor('#666666'))
                sl.setStrokeWidth(0.26)
            categories.append(QgsRendererCategory(cat_name, symbol, cat_name))

        renderer = QgsCategorizedSymbolRenderer('地目', categories)
        layer.setRenderer(renderer)
        layer.triggerRepaint()
