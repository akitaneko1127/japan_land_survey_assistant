# -*- coding: utf-8 -*-
"""地番情報カードウィジェット."""

from typing import Dict

from qgis.PyQt.QtWidgets import (
    QGroupBox, QFormLayout, QLabel,
)


# Fields to display (label, key)
_DISPLAY_FIELDS = [
    ('地番', '地番'),
    ('大字名', '大字名'),
    ('字名', '字名'),
    ('地目', '地目'),
    ('地積 (m²)', '地積'),
    ('座標系', '座標系'),
    ('精度区分', '精度区分'),
]


class ParcelInfoCard(QGroupBox):
    """Card-style widget showing parcel attribute information."""

    def __init__(self, parent=None):
        super().__init__('検索結果', parent)
        self._labels: Dict[str, QLabel] = {}
        self._setup_ui()

    def _setup_ui(self):
        form = QFormLayout(self)
        for label_text, key in _DISPLAY_FIELDS:
            val_label = QLabel('-')
            val_label.setWordWrap(True)
            form.addRow(f'{label_text}:', val_label)
            self._labels[key] = val_label

    def show_info(self, info: Dict):
        for label_text, key in _DISPLAY_FIELDS:
            val = info.get(key, '-')
            if val is None:
                val = '-'
            self._labels[key].setText(str(val))

    def clear_info(self):
        for lbl in self._labels.values():
            lbl.setText('-')
