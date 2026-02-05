# -*- coding: utf-8 -*-
"""Main tabbed dialog for Japan Land Survey Assistant."""

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QLabel, QProgressBar, QWidget,
)
from qgis.PyQt.QtCore import Qt


class MainDialog(QDialog):
    """Main dialog with five tabs."""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle('Japan Land Survey Assistant')
        self.setMinimumSize(720, 560)
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowMinMaxButtonsHint
        )

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Tab widget
        self.tabs = QTabWidget()

        # Lazy-import panels to avoid circular imports
        from .data_loader_panel import DataLoaderPanel
        from .progress_viewer import ProgressViewerPanel
        from .parcel_search_panel import ParcelSearchPanel
        from .land_price_panel import LandPricePanel
        from .settings_dialog import SettingsPanel

        self.data_loader = DataLoaderPanel(self.iface, self)
        self.progress_viewer = ProgressViewerPanel(self.iface, self)
        self.parcel_search = ParcelSearchPanel(self.iface, self)
        self.land_price = LandPricePanel(self.iface, self)
        self.settings = SettingsPanel(self)

        self.tabs.addTab(self.data_loader, 'データ取得')
        self.tabs.addTab(self.progress_viewer, '進捗ビュー')
        self.tabs.addTab(self.parcel_search, '地番検索')
        self.tabs.addTab(self.land_price, '地価情報')
        self.tabs.addTab(self.settings, '設定')

        layout.addWidget(self.tabs)

        # Bottom status bar
        status_layout = QHBoxLayout()
        self.status_label = QLabel('準備完了')
        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        status_layout.addWidget(self.status_label, 1)
        status_layout.addWidget(self.progress_bar)
        layout.addLayout(status_layout)

        # --- Signal wiring ---
        # Tab change → parcel search auto-detect
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # Progress viewer prefecture detection → parcel search
        self.progress_viewer.prefecture_detected.connect(
            self.parcel_search.on_prefecture_detected
        )

        # Parcel search status → main status bar
        self.parcel_search.status_message.connect(self.set_status)

    def _on_tab_changed(self, index):
        """タブ切替ハンドラ."""
        widget = self.tabs.widget(index)
        if widget is self.parcel_search:
            self.parcel_search.on_tab_activated()

    def set_status(self, message: str):
        self.status_label.setText(message)

    def show_progress(self, value: int, maximum: int = 100):
        self.progress_bar.setMaximum(maximum)
        self.progress_bar.setValue(value)
        self.progress_bar.show()

    def hide_progress(self):
        self.progress_bar.hide()

    def closeEvent(self, event):
        # ダイアログを閉じずに非表示にする (再表示可能にする)
        event.ignore()
        self.hide()

    def cleanup(self):
        """プラグインアンロード時に呼ばれるクリーンアップ."""
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if hasattr(widget, 'cleanup'):
                widget.cleanup()
