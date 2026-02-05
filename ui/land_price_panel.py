# -*- coding: utf-8 -*-
"""地価情報タブ."""

import math
from datetime import date

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QComboBox, QPushButton, QMessageBox, QProgressBar,
    QSpinBox,
)
from qgis.PyQt.QtCore import QThread, pyqtSignal
from qgis.core import (
    QgsProject, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsMessageLog, Qgis,
)

from ..core.land_price_api import LandPriceApiClient
from ..core.config import Config


class _FetchThread(QThread):
    """地価データ取得ワーカースレッド.

    指定年で結果が0件の場合、1年前を自動リトライする。
    """
    finished_ok = pyqtSignal(list, int)  # features, actual_year
    error = pyqtSignal(str)

    def __init__(self, client, extent, zoom, year, price_classification):
        super().__init__()
        self.client = client
        self.extent = extent
        self.zoom = zoom
        self.year = year
        self.price_classification = price_classification

    def run(self):
        try:
            # 指定年で取得
            feats = self.client.fetch_prices_for_extent(
                *self.extent, zoom=self.zoom, year=self.year,
                price_classification=self.price_classification,
            )
            if feats:
                self.finished_ok.emit(feats, self.year)
                return

            # 0件 → 1年前でリトライ
            fallback_year = self.year - 1
            self.client._log(
                f'year={self.year} で0件。year={fallback_year} でリトライ',
                Qgis.Info,
            )
            feats = self.client.fetch_prices_for_extent(
                *self.extent, zoom=self.zoom, year=fallback_year,
                price_classification=self.price_classification,
            )
            self.finished_ok.emit(feats, fallback_year)
        except Exception as e:
            self.error.emit(str(e))

    @staticmethod
    def calc_zoom_for_extent(xmin, ymin, xmax, ymax):
        """マップ範囲から適切なzoomレベルを自動算出 (13-15)."""
        width = abs(xmax - xmin)
        height = abs(ymax - ymin)
        span = max(width, height)
        if span <= 0:
            return 14
        z = math.log2(1440.0 / span) if span > 0 else 14
        z = int(round(z))
        return max(13, min(15, z))


class LandPricePanel(QWidget):
    """Land price information tab."""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.config = Config()
        self._thread = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Dataset
        ds_group = QGroupBox('データ種別')
        ds_layout = QVBoxLayout(ds_group)
        ds_layout.addWidget(QLabel('種別:'))
        self.combo_dataset = QComboBox()
        self.combo_dataset.addItem('地価公示 (毎年1月1日)', 0)
        self.combo_dataset.addItem('都道府県地価調査 (毎年7月1日)', 1)
        ds_layout.addWidget(self.combo_dataset)
        layout.addWidget(ds_group)

        # Year
        year_row = QHBoxLayout()
        year_row.addWidget(QLabel('対象年:'))
        self.spin_year = QSpinBox()
        self.spin_year.setRange(2000, date.today().year)
        self.spin_year.setValue(date.today().year - 1)
        year_row.addWidget(self.spin_year)
        year_row.addWidget(QLabel('(データなしの場合は前年を自動リトライ)'))
        year_row.addStretch()
        layout.addLayout(year_row)

        # Info
        info_label = QLabel(
            '現在のマップ範囲の地価情報を取得します。\n'
            'ズームレベルはマップ範囲から自動計算されます。\n'
            '※ 不動産情報ライブラリAPIキーが必要です（設定タブで入力）。'
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # Progress
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate
        self.progress.hide()
        layout.addWidget(self.progress)

        # Status label
        self.lbl_status = QLabel('')
        layout.addWidget(self.lbl_status)

        # Buttons
        btn_row = QHBoxLayout()
        self.btn_fetch = QPushButton('取得')
        self.btn_fetch.clicked.connect(self._on_fetch)
        btn_row.addWidget(self.btn_fetch)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        layout.addStretch()

    @staticmethod
    def _log(msg, level=Qgis.Info):
        QgsMessageLog.logMessage(msg, 'JLSA-LandPricePanel', level)

    def _on_fetch(self):
        api_key = self.config.get_api_key()
        if not api_key:
            QMessageBox.warning(
                self, 'エラー',
                'APIキーが設定されていません。\n設定タブでAPIキーを入力してください。'
            )
            return

        canvas = self.iface.mapCanvas()
        extent = canvas.extent()
        map_crs = canvas.mapSettings().destinationCrs()

        self._log(f'マップCRS: {map_crs.authid()}')
        self._log(f'マップ範囲 (元CRS): xmin={extent.xMinimum():.6f}, '
                   f'ymin={extent.yMinimum():.6f}, '
                   f'xmax={extent.xMaximum():.6f}, '
                   f'ymax={extent.yMaximum():.6f}')

        # CRS変換: マップCRS → EPSG:4326
        wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
        if map_crs != wgs84:
            transform = QgsCoordinateTransform(
                map_crs, wgs84, QgsProject.instance()
            )
            extent = transform.transformBoundingBox(extent)
            self._log(f'EPSG:4326に変換後: xmin={extent.xMinimum():.6f}, '
                       f'ymin={extent.yMinimum():.6f}, '
                       f'xmax={extent.xMaximum():.6f}, '
                       f'ymax={extent.yMaximum():.6f}')

        xmin, ymin = extent.xMinimum(), extent.yMinimum()
        xmax, ymax = extent.xMaximum(), extent.yMaximum()

        # 緯度の範囲チェック (タイル座標計算で必要)
        if ymin < -85.05 or ymax > 85.05:
            self._log(f'緯度が範囲外: ymin={ymin}, ymax={ymax}', Qgis.Warning)
            QMessageBox.warning(self, 'エラー',
                                f'緯度が有効範囲外です (ymin={ymin:.4f}, ymax={ymax:.4f})。\n'
                                'マップを日本付近に移動してください。')
            return

        if xmin == xmax or ymin == ymax:
            QMessageBox.warning(self, 'エラー', 'マップ範囲が不正です。')
            return

        zoom = _FetchThread.calc_zoom_for_extent(xmin, ymin, xmax, ymax)
        price_classification = self.combo_dataset.currentData()
        year = self.spin_year.value()

        self._log(f'取得開始: priceClassification={price_classification}, '
                   f'zoom={zoom}, year={year}, '
                   f'extent=({xmin:.6f}, {ymin:.6f}, {xmax:.6f}, {ymax:.6f})')

        self.lbl_status.setText(f'取得中... (zoom={zoom}, year={year})')

        client = LandPriceApiClient(api_key)
        self._set_busy(True)

        self._thread = _FetchThread(
            client, (xmin, ymin, xmax, ymax), zoom, year, price_classification,
        )
        self._thread.finished_ok.connect(self._on_done)
        self._thread.error.connect(self._on_error)
        self._thread.start()

    def _on_done(self, features, actual_year):
        self._set_busy(False)
        self._log(f'取得完了: {len(features)} features (year={actual_year})')
        if not features:
            self.lbl_status.setText('データなし')
            QMessageBox.information(self, '結果', 'データが見つかりませんでした。')
            return

        api_key = self.config.get_api_key()
        client = LandPriceApiClient(api_key)
        layer = client.create_point_layer(
            features, layer_name=f'地価情報_{actual_year}'
        )
        if layer and layer.isValid():
            QgsProject.instance().addMapLayer(layer)
            self.lbl_status.setText(
                f'{layer.featureCount()} 件取得 ({actual_year}年)'
            )
            self._log(f'レイヤ追加: {layer.name()} ({layer.featureCount()} features)')
            QMessageBox.information(
                self, '完了',
                f'{layer.featureCount()} 件の地価データを取得しました。'
                f'\n(対象年: {actual_year})'
            )
        else:
            self.lbl_status.setText('レイヤ作成失敗')
            self._log('レイヤ作成失敗', Qgis.Warning)
            QMessageBox.warning(self, 'エラー', 'レイヤ作成に失敗しました。')

    def _on_error(self, msg):
        self._set_busy(False)
        self.lbl_status.setText(f'エラー: {msg}')
        self._log(f'エラー: {msg}', Qgis.Critical)
        QMessageBox.critical(self, 'エラー', msg)

    def _set_busy(self, busy):
        self.btn_fetch.setEnabled(not busy)
        if busy:
            self.progress.show()
        else:
            self.progress.hide()

    def cleanup(self):
        if self._thread and self._thread.isRunning():
            self._thread.terminate()
            self._thread.wait()
