# -*- coding: utf-8 -*-
"""進捗チャートウィジェット — simple bar chart drawn with QPainter."""

from typing import List, Dict

from qgis.PyQt.QtWidgets import QWidget
from qgis.PyQt.QtCore import Qt, QRectF
from qgis.PyQt.QtGui import QPainter, QColor, QFont, QPen


STATUS_COLORS = {
    '完了': QColor('#1a9641'),
    '実施中': QColor('#a6d96a'),
    '休止中': QColor('#fdae61'),
    '未着手': QColor('#999999'),
}


class ProgressChartWidget(QWidget):
    """Draws a horizontal stacked bar showing status distribution."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._counts: Dict[str, int] = {}
        self._total: int = 0
        self.setMinimumHeight(80)

    def update_data(self, records: List[Dict]):
        counts = {}
        for r in records:
            s = r.get('status', '未着手')
            counts[s] = counts.get(s, 0) + 1
        self._counts = counts
        self._total = sum(counts.values())
        self.update()

    def paintEvent(self, event):
        if self._total == 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width() - 20
        h = self.height()
        bar_h = 30
        bar_y = 10
        x = 10

        # Draw stacked bar
        for status in ['完了', '実施中', '休止中', '未着手']:
            count = self._counts.get(status, 0)
            if count == 0:
                continue
            seg_w = max(1, int(w * count / self._total))
            color = STATUS_COLORS.get(status, QColor('#cccccc'))
            painter.setBrush(color)
            painter.setPen(QPen(QColor('#333333'), 1))
            painter.drawRect(QRectF(x, bar_y, seg_w, bar_h))
            x += seg_w

        # Draw legend
        legend_y = bar_y + bar_h + 10
        lx = 10
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)

        for status in ['完了', '実施中', '休止中', '未着手']:
            count = self._counts.get(status, 0)
            color = STATUS_COLORS.get(status, QColor('#cccccc'))
            painter.setBrush(color)
            painter.setPen(QPen(QColor('#333333'), 1))
            painter.drawRect(QRectF(lx, legend_y, 12, 12))
            painter.setPen(QColor('#000000'))
            painter.drawText(
                int(lx + 16), int(legend_y + 11),
                f'{status}: {count}'
            )
            lx += 100

        # Total label
        painter.drawText(int(lx + 10), int(legend_y + 11), f'計: {self._total}')

        painter.end()
