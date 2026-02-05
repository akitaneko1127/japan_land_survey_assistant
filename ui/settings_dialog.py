# -*- coding: utf-8 -*-
"""設定タブ."""

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QLineEdit, QPushButton, QCheckBox, QSpinBox,
    QMessageBox,
)
from qgis.PyQt.QtCore import Qt

from ..core.config import Config
from ..services.cache_manager import CacheManager


class SettingsPanel(QWidget):
    """Settings tab for plugin configuration."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = Config()
        self.cache = CacheManager()
        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # API key
        api_group = QGroupBox('不動産情報ライブラリ API')
        api_layout = QVBoxLayout(api_group)
        api_layout.addWidget(QLabel('APIキー:'))
        self.edit_api_key = QLineEdit()
        self.edit_api_key.setEchoMode(QLineEdit.Password)
        self.edit_api_key.setPlaceholderText('Ocp-Apim-Subscription-Key')
        api_layout.addWidget(self.edit_api_key)
        layout.addWidget(api_group)

        # General settings
        gen_group = QGroupBox('一般設定')
        gen_layout = QVBoxLayout(gen_group)

        self.chk_cache = QCheckBox('キャッシュを有効にする')
        gen_layout.addWidget(self.chk_cache)

        self.chk_auto_style = QCheckBox('読込後に自動スタイル適用')
        gen_layout.addWidget(self.chk_auto_style)

        timeout_row = QHBoxLayout()
        timeout_row.addWidget(QLabel('タイムアウト (秒):'))
        self.spin_timeout = QSpinBox()
        self.spin_timeout.setRange(10, 300)
        self.spin_timeout.setSingleStep(10)
        timeout_row.addWidget(self.spin_timeout)
        timeout_row.addStretch()
        gen_layout.addLayout(timeout_row)

        layout.addWidget(gen_group)

        # MOJ XML defaults
        moj_group = QGroupBox('MOJ XML デフォルト')
        moj_layout = QVBoxLayout(moj_group)
        self.chk_arbitrary = QCheckBox('任意座標系データを含む')
        self.chk_outside = QCheckBox('図郭外・別図を含む')
        moj_layout.addWidget(self.chk_arbitrary)
        moj_layout.addWidget(self.chk_outside)
        layout.addWidget(moj_group)

        # Cache management
        cache_group = QGroupBox('キャッシュ管理')
        cache_layout = QVBoxLayout(cache_group)
        self.lbl_cache_size = QLabel()
        cache_layout.addWidget(self.lbl_cache_size)
        self.btn_clear_cache = QPushButton('キャッシュをクリア')
        self.btn_clear_cache.clicked.connect(self._clear_cache)
        cache_layout.addWidget(self.btn_clear_cache)
        layout.addWidget(cache_group)

        # Save button
        btn_row = QHBoxLayout()
        self.btn_save = QPushButton('保存')
        self.btn_save.clicked.connect(self._save_settings)
        btn_row.addWidget(self.btn_save)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        layout.addStretch()

    def _load_settings(self):
        self.edit_api_key.setText(self.config.get_api_key())
        self.chk_cache.setChecked(self.config.is_cache_enabled())
        self.chk_auto_style.setChecked(self.config.is_auto_style())
        self.spin_timeout.setValue(self.config.get_timeout())
        self.chk_arbitrary.setChecked(self.config.include_arbitrary_crs())
        self.chk_outside.setChecked(self.config.include_outside_area())
        self._update_cache_label()

    def _save_settings(self):
        self.config.set_api_key(self.edit_api_key.text().strip())
        self.config.set_value('cache_enabled', self.chk_cache.isChecked())
        self.config.set_value('auto_style', self.chk_auto_style.isChecked())
        self.config.set_value('timeout', self.spin_timeout.value())
        self.config.set_value('include_arbitrary_crs', self.chk_arbitrary.isChecked())
        self.config.set_value('include_outside_area', self.chk_outside.isChecked())
        QMessageBox.information(self, '設定', '設定を保存しました。')

    def _clear_cache(self):
        reply = QMessageBox.question(
            self, '確認', 'キャッシュを全て削除しますか？',
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.cache.clear_all()
            self._update_cache_label()
            QMessageBox.information(self, 'キャッシュ', 'キャッシュを削除しました。')

    def _update_cache_label(self):
        size_bytes = self.cache.get_cache_size_bytes()
        if size_bytes < 1024:
            size_str = f'{size_bytes} B'
        elif size_bytes < 1024 * 1024:
            size_str = f'{size_bytes / 1024:.1f} KB'
        else:
            size_str = f'{size_bytes / 1024 / 1024:.1f} MB'
        self.lbl_cache_size.setText(f'キャッシュサイズ: {size_str}')
