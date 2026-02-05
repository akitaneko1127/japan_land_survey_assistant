# -*- coding: utf-8 -*-
"""地籍調査進捗データ管理."""

import csv
import os
from typing import List, Dict, Optional

from qgis.core import (
    QgsVectorLayer, QgsField, QgsFeature, QgsProject,
    QgsMessageLog, Qgis, QgsWkbTypes, QgsGraduatedSymbolRenderer,
    QgsRendererRange, QgsFillSymbol, QgsSimpleFillSymbolLayer,
    QgsCategorizedSymbolRenderer, QgsRendererCategory,
)
from qgis.PyQt.QtCore import QVariant, QMetaType
from qgis.PyQt.QtGui import QColor


# Graduated colour scheme for progress rate
PROGRESS_COLORS = [
    (80, 100, '#1a9641', '80%以上'),
    (60, 80, '#a6d96a', '60-80%'),
    (40, 60, '#ffffbf', '40-60%'),
    (20, 40, '#fdae61', '20-40%'),
    (0, 20, '#d7191c', '20%未満'),
]

STATUS_COLORS = {
    '完了': '#1a9641',
    '実施中': '#a6d96a',
    '休止中': '#fdae61',
    '未着手': '#999999',
}


class ChisekiProgressManager:
    """Manages cadastral survey progress data."""

    @staticmethod
    def _log(msg, level=Qgis.Info):
        QgsMessageLog.logMessage(msg, 'JLSA-Chiseki', level)

    @staticmethod
    def _csv_path() -> str:
        return os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'resources', 'data', 'chiseki_progress.csv'
        )

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def load_csv(self, csv_path: Optional[str] = None) -> List[Dict]:
        """Load progress CSV into a list of dicts."""
        path = csv_path or self._csv_path()
        if not os.path.exists(path):
            self._log(f'CSV not found: {path}', Qgis.Warning)
            return []

        records = []
        with open(path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                row['progress_rate'] = self._to_float(row.get('progress_rate'))
                row['target_area'] = self._to_float(row.get('target_area'))
                row['surveyed_area'] = self._to_float(row.get('surveyed_area'))
                records.append(row)

        self._log(f'Loaded {len(records)} progress records')
        return records

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    @staticmethod
    def filter_records(records: List[Dict],
                       pref_code: str = '',
                       statuses: Optional[List[str]] = None) -> List[Dict]:
        result = records
        if pref_code:
            result = [r for r in result if r.get('pref_code') == pref_code]
        if statuses:
            result = [r for r in result if r.get('status') in statuses]
        return result

    # ------------------------------------------------------------------
    # Layer creation
    # ------------------------------------------------------------------

    def join_to_admin_layer(self, admin_layer: QgsVectorLayer,
                            records: List[Dict],
                            join_field: str = 'N03_007') -> QgsVectorLayer:
        """Join progress data to an administrative boundary layer.

        Creates a new memory layer with progress attributes added.
        """
        # Build lookup by city code
        # 政令指定都市の場合、CSV は市コード (例: 14100) だが
        # 行政区域レイヤは区コード (例: 14101) を持つ。
        # 市コード末尾 '00' の場合は prefix (例: '141') でも照合する。
        lookup = {}
        prefix_lookup = {}
        for r in records:
            code = str(r.get('city_code', ''))
            if code:
                lookup[code] = r
                # 政令指定都市: 末尾2桁が '00' → prefix照合用
                if len(code) == 5 and code.endswith('00'):
                    prefix_lookup[code[:3]] = r

        # Clone geometry + add progress fields
        crs = admin_layer.crs().authid()
        gt = admin_layer.geometryType()
        if gt == QgsWkbTypes.PointGeometry:
            geom_type = 'Point'
        elif gt == QgsWkbTypes.LineGeometry:
            geom_type = 'LineString'
        else:
            geom_type = 'Polygon'
        uri = f'{geom_type}?crs={crs}'
        out = QgsVectorLayer(uri, '地籍調査進捗', 'memory')
        prov = out.dataProvider()

        # Copy existing fields
        prov.addAttributes(admin_layer.fields().toList())
        # Add progress fields
        extra_fields = [
            QgsField('progress_rate', QMetaType.Type.Double),
            QgsField('target_area', QMetaType.Type.Double),
            QgsField('surveyed_area', QMetaType.Type.Double),
            QgsField('status', QMetaType.Type.QString),
            QgsField('is_priority', QMetaType.Type.Bool),
        ]
        prov.addAttributes(extra_fields)
        out.updateFields()

        new_features = []
        matched = 0
        for feat in admin_layer.getFeatures():
            code = str(feat.attribute(join_field) or '')
            rec = lookup.get(code)
            if rec is None and len(code) >= 3:
                rec = prefix_lookup.get(code[:3])
            # 進捗データが一致するフィーチャのみ追加
            if rec is None:
                continue
            matched += 1
            nf = QgsFeature(out.fields())
            nf.setGeometry(feat.geometry())
            # Copy original attrs
            for i in range(admin_layer.fields().count()):
                nf.setAttribute(i, feat.attribute(i))
            # Set progress attrs
            offset = admin_layer.fields().count()
            nf.setAttribute(offset, rec.get('progress_rate'))
            nf.setAttribute(offset + 1, rec.get('target_area'))
            nf.setAttribute(offset + 2, rec.get('surveyed_area'))
            nf.setAttribute(offset + 3, rec.get('status'))
            nf.setAttribute(offset + 4, rec.get('is_priority'))
            new_features.append(nf)
        self._log(f'Join結果: {matched} features matched')

        prov.addFeatures(new_features)
        out.updateExtents()
        return out

    # ------------------------------------------------------------------
    # 行政区域レイヤ直接操作
    # ------------------------------------------------------------------

    def _build_lookups(self, records: List[Dict]):
        """進捗データから照合用辞書を構築.

        city_code があればコードベース照合、
        なければ市区町村名ベース照合を使う。
        """
        code_lookup = {}
        prefix_lookup = {}
        name_lookup = {}  # (pref_name, city_name) -> record
        for r in records:
            code = str(r.get('city_code', '')).strip()
            if code:
                code_lookup[code] = r
                if len(code) == 5 and code.endswith('00'):
                    prefix_lookup[code[:3]] = r
            # 名前ベース照合用
            city_name = str(r.get('city_name', '')).strip()
            if city_name:
                name_lookup[city_name] = r
        return code_lookup, prefix_lookup, name_lookup

    def _match_feature(self, feat, code_lookup, prefix_lookup, name_lookup,
                       join_field='N03_007'):
        """フィーチャを進捗データと照合."""
        # 1. コードベース照合
        if code_lookup:
            code = str(feat.attribute(join_field) or '')
            rec = code_lookup.get(code)
            if rec is None and len(code) >= 3:
                rec = prefix_lookup.get(code[:3])
            if rec is not None:
                return rec

        # 2. 市区町村名ベース照合 (N03_003=市区名, N03_004=町村名)
        if name_lookup:
            # 政令指定都市: N03_003 に「横浜市」等が入る
            city_name = str(feat.attribute('N03_003') or '').strip()
            if city_name and city_name in name_lookup:
                return name_lookup[city_name]
            # 一般市区町村: N03_004 に市区町村名が入る
            city_name = str(feat.attribute('N03_004') or '').strip()
            if city_name and city_name in name_lookup:
                return name_lookup[city_name]
        return None

    def find_matching_codes(self, admin_layer: QgsVectorLayer,
                            records: List[Dict],
                            join_field: str = 'N03_007') -> set:
        """行政区域レイヤのフィーチャと進捗データが一致する市区町村コードを返す."""
        code_lookup, prefix_lookup, name_lookup = self._build_lookups(records)
        matching = set()
        for feat in admin_layer.getFeatures():
            rec = self._match_feature(feat, code_lookup, prefix_lookup,
                                      name_lookup, join_field)
            if rec is not None:
                code = str(feat.attribute(join_field) or '')
                if code:
                    matching.add(code)
        self._log(f'一致コード数: {len(matching)}')
        return matching

    def apply_direct_style(self, admin_layer: QgsVectorLayer,
                           records: List[Dict],
                           join_field: str = 'N03_007',
                           use_progress: bool = True):
        """行政区域レイヤに進捗率ベースの色分けスタイルを直接適用."""
        from qgis.core import QgsRuleBasedRenderer

        code_lookup, prefix_lookup, name_lookup = self._build_lookups(records)

        # コード → 進捗率/ステータス のマッピングを構築
        code_to_data = {}
        for feat in admin_layer.getFeatures():
            rec = self._match_feature(feat, code_lookup, prefix_lookup,
                                      name_lookup, join_field)
            if rec is not None:
                code = str(feat.attribute(join_field) or '')
                if code:
                    code_to_data[code] = rec

        # ルールベースレンダラーを構築
        root_rule = QgsRuleBasedRenderer.Rule(None)

        if use_progress:
            for lo, hi, hex_color, label in PROGRESS_COLORS:
                codes = [c for c, r in code_to_data.items()
                         if r.get('progress_rate') is not None
                         and lo <= r['progress_rate'] <= hi]
                if not codes:
                    continue
                symbol = QgsFillSymbol()
                sl = symbol.symbolLayer(0)
                if isinstance(sl, QgsSimpleFillSymbolLayer):
                    c = QColor(hex_color)
                    c.setAlpha(200)
                    sl.setFillColor(c)
                    sl.setStrokeColor(QColor('#333333'))
                    sl.setStrokeWidth(0.26)
                codes_str = ','.join(f"'{c}'" for c in codes)
                expr = f'"{join_field}" IN ({codes_str})'
                rule = QgsRuleBasedRenderer.Rule(symbol, label=label,
                                                  filterExp=expr)
                root_rule.appendChild(rule)
        else:
            for status_val, hex_color in STATUS_COLORS.items():
                codes = [c for c, r in code_to_data.items()
                         if r.get('status') == status_val]
                if not codes:
                    continue
                symbol = QgsFillSymbol()
                sl = symbol.symbolLayer(0)
                if isinstance(sl, QgsSimpleFillSymbolLayer):
                    c = QColor(hex_color)
                    c.setAlpha(200)
                    sl.setFillColor(c)
                    sl.setStrokeColor(QColor('#333333'))
                    sl.setStrokeWidth(0.26)
                codes_str = ','.join(f"'{c}'" for c in codes)
                expr = f'"{join_field}" IN ({codes_str})'
                rule = QgsRuleBasedRenderer.Rule(symbol, label=status_val,
                                                  filterExp=expr)
                root_rule.appendChild(rule)

        renderer = QgsRuleBasedRenderer(root_rule)
        admin_layer.setRenderer(renderer)
        admin_layer.triggerRepaint()

    # ------------------------------------------------------------------
    # Styling (memory layer用 - 後方互換)
    # ------------------------------------------------------------------

    @staticmethod
    def apply_progress_style(layer: QgsVectorLayer):
        """Apply graduated style by progress_rate."""
        ranges = []
        for lo, hi, hex_color, label in PROGRESS_COLORS:
            symbol = QgsFillSymbol()
            sl = symbol.symbolLayer(0)
            if isinstance(sl, QgsSimpleFillSymbolLayer):
                c = QColor(hex_color)
                c.setAlpha(200)
                sl.setFillColor(c)
                sl.setStrokeColor(QColor('#333333'))
                sl.setStrokeWidth(0.26)
            ranges.append(QgsRendererRange(lo, hi, symbol, label))

        renderer = QgsGraduatedSymbolRenderer('progress_rate', ranges)
        layer.setRenderer(renderer)
        layer.triggerRepaint()

    @staticmethod
    def apply_status_style(layer: QgsVectorLayer):
        """Apply categorised style by status field."""
        categories = []
        for status_val, hex_color in STATUS_COLORS.items():
            symbol = QgsFillSymbol()
            sl = symbol.symbolLayer(0)
            if isinstance(sl, QgsSimpleFillSymbolLayer):
                c = QColor(hex_color)
                c.setAlpha(200)
                sl.setFillColor(c)
                sl.setStrokeColor(QColor('#333333'))
                sl.setStrokeWidth(0.26)
            categories.append(QgsRendererCategory(status_val, symbol, status_val))

        renderer = QgsCategorizedSymbolRenderer('status', categories)
        layer.setRenderer(renderer)
        layer.triggerRepaint()

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    @staticmethod
    def export_csv(records: List[Dict], output_path: str):
        if not records:
            return
        fieldnames = list(records[0].keys())
        with open(output_path, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(records)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _to_float(val) -> Optional[float]:
        if val is None or val == '':
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None
