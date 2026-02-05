# -*- coding: utf-8 -*-
"""データ取得タブ — MOJ XML / 国土数値情報 / 登記所備付地図自動取得 / PMTiles."""

import os

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QRadioButton,
    QLabel, QLineEdit, QPushButton, QComboBox, QCheckBox,
    QFileDialog, QMessageBox, QProgressBar, QListWidget,
    QAbstractItemView, QApplication,
)
from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal
from qgis.PyQt.QtGui import QCursor
from qgis.core import (
    QgsProject, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsVectorLayer, QgsVectorSimplifyMethod, QgsMessageLog, Qgis,
)

from ..services.data_loader_service import DataLoaderService
from ..services.plugin_bridge import PluginBridge
from ..core.kokudo_api_client import KOKUDO_DATASETS
from ..core.config import Config
from ..core.crs_utils import canvas_center_to_4326


# Prefecture master (code → name)
PREFECTURES = {
    '01': '北海道', '02': '青森県', '03': '岩手県', '04': '宮城県',
    '05': '秋田県', '06': '山形県', '07': '福島県', '08': '茨城県',
    '09': '栃木県', '10': '群馬県', '11': '埼玉県', '12': '千葉県',
    '13': '東京都', '14': '神奈川県', '15': '新潟県', '16': '富山県',
    '17': '石川県', '18': '福井県', '19': '山梨県', '20': '長野県',
    '21': '岐阜県', '22': '静岡県', '23': '愛知県', '24': '三重県',
    '25': '滋賀県', '26': '京都府', '27': '大阪府', '28': '兵庫県',
    '29': '奈良県', '30': '和歌山県', '31': '鳥取県', '32': '島根県',
    '33': '岡山県', '34': '広島県', '35': '山口県', '36': '徳島県',
    '37': '香川県', '38': '愛媛県', '39': '高知県', '40': '福岡県',
    '41': '佐賀県', '42': '長崎県', '43': '熊本県', '44': '大分県',
    '45': '宮崎県', '46': '鹿児島県', '47': '沖縄県',
}


class _KokudoDownloadThread(QThread):
    """Background thread for Kokudo data download.

    QgsVectorLayer はスレッドアフィニティがあるため、
    ファイルパス情報のみを返し、メインスレッドでレイヤを作成する。
    """
    progress = pyqtSignal(int, int)
    finished_ok = pyqtSignal(list)  # list of (extract_dir, dataset_id, pref)
    error = pyqtSignal(str)

    def __init__(self, service, dataset_id, pref_codes, fiscal_year):
        super().__init__()
        self.service = service
        self.dataset_id = dataset_id
        self.pref_codes = pref_codes
        self.fiscal_year = fiscal_year

    def run(self):
        try:
            results = self.service.load_kokudo_data_paths(
                self.dataset_id, self.pref_codes, self.fiscal_year,
                progress_callback=lambda c, t: self.progress.emit(c, t),
            )
            self.finished_ok.emit(results or [])
        except Exception as e:
            self.error.emit(str(e))


class _MojAutoDownloadThread(QThread):
    """Background thread for MOJ GeoJSON auto-download.

    QgsVectorLayer は QObject でスレッドアフィニティがあるため、
    ファイルパスとレイヤ名だけを返し、メインスレッドでレイヤを再作成する。
    """
    finished_ok = pyqtSignal(str, str)  # source_path, layer_name
    error = pyqtSignal(str)

    def __init__(self, service, lat, lon, preferred_year):
        super().__init__()
        self.service = service
        self.lat = lat
        self.lon = lon
        self.preferred_year = preferred_year

    def run(self):
        try:
            layer = self.service.load_moj_from_extent(
                self.lat, self.lon,
                preferred_year=self.preferred_year,
            )
            if layer and layer.isValid():
                self.finished_ok.emit(layer.source(), layer.name())
            else:
                self.error.emit('レイヤの読込に失敗しました。')
        except Exception as e:
            self.error.emit(str(e))


class DataLoaderPanel(QWidget):
    """Data retrieval tab."""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.service = DataLoaderService()
        self.config = Config()
        self._download_thread = None
        self._setup_ui()
        self._update_plugin_status()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Data source selection
        src_group = QGroupBox('データソース')
        src_layout = QVBoxLayout(src_group)
        self.radio_moj = QRadioButton('MOJ XML（法務省地図XML）')
        self.radio_kokudo = QRadioButton('国土数値情報')
        self.radio_moj_auto = QRadioButton('登記所備付地図（現在地から自動取得）')
        self.radio_fude = QRadioButton('筆ポリゴン（オンライン表示）')
        self.radio_moj.setChecked(True)
        self.radio_moj.toggled.connect(self._on_source_changed)
        self.radio_kokudo.toggled.connect(self._on_source_changed)
        self.radio_moj_auto.toggled.connect(self._on_source_changed)
        self.radio_fude.toggled.connect(self._on_source_changed)
        src_layout.addWidget(self.radio_moj)
        src_layout.addWidget(self.radio_kokudo)
        src_layout.addWidget(self.radio_moj_auto)
        src_layout.addWidget(self.radio_fude)
        layout.addWidget(src_group)

        # Plugin status
        self.lbl_plugin_status = QLabel()
        layout.addWidget(self.lbl_plugin_status)

        # --- MOJ XML panel ---
        self.moj_group = QGroupBox('MOJ XMLファイル')
        moj_layout = QVBoxLayout(self.moj_group)

        file_row = QHBoxLayout()
        self.edit_file = QLineEdit()
        self.edit_file.setPlaceholderText('XMLまたはZIPファイルを選択...')
        file_row.addWidget(self.edit_file)
        self.btn_browse = QPushButton('参照...')
        self.btn_browse.clicked.connect(self._browse_file)
        file_row.addWidget(self.btn_browse)
        moj_layout.addLayout(file_row)

        self.chk_arbitrary = QCheckBox('任意座標系データを含む')
        self.chk_outside = QCheckBox('図郭外・別図を含む')
        self.chk_auto_style = QCheckBox('読込後に自動スタイル適用')
        self.chk_auto_style.setChecked(True)
        moj_layout.addWidget(self.chk_arbitrary)
        moj_layout.addWidget(self.chk_outside)
        moj_layout.addWidget(self.chk_auto_style)

        layout.addWidget(self.moj_group)

        # --- Kokudo panel ---
        self.kokudo_group = QGroupBox('国土数値情報')
        kokudo_layout = QVBoxLayout(self.kokudo_group)

        kokudo_layout.addWidget(QLabel('データセット:'))
        self.combo_dataset = QComboBox()
        for code, info in KOKUDO_DATASETS.items():
            self.combo_dataset.addItem(
                f"[{info['category']}] {info['name']} ({code})", code
            )
        kokudo_layout.addWidget(self.combo_dataset)

        pref_header = QHBoxLayout()
        pref_header.addWidget(QLabel('都道府県（複数選択可）:'))
        self.btn_detect_pref = QPushButton('現在地から設定')
        self.btn_detect_pref.clicked.connect(self._detect_pref_from_map)
        pref_header.addWidget(self.btn_detect_pref)
        pref_header.addStretch()
        kokudo_layout.addLayout(pref_header)
        self.list_pref = QListWidget()
        self.list_pref.setSelectionMode(QAbstractItemView.MultiSelection)
        for code, name in PREFECTURES.items():
            self.list_pref.addItem(f'{name} ({code})')
        self.list_pref.setMaximumHeight(150)
        kokudo_layout.addWidget(self.list_pref)

        yr_row = QHBoxLayout()
        yr_row.addWidget(QLabel('年度:'))
        self.edit_year = QLineEdit()
        self.edit_year.setPlaceholderText('空欄で最新')
        self.edit_year.setMaximumWidth(100)
        yr_row.addWidget(self.edit_year)
        yr_row.addStretch()
        kokudo_layout.addLayout(yr_row)

        # ステータス表示
        self.lbl_kokudo_status = QLabel()
        self.lbl_kokudo_status.setStyleSheet('color: #666; font-size: 11px;')
        kokudo_layout.addWidget(self.lbl_kokudo_status)

        self.kokudo_group.hide()
        layout.addWidget(self.kokudo_group)

        # --- MOJ Auto (GeoJSON) panel ---
        self.moj_auto_group = QGroupBox('登記所備付地図（自動取得）')
        moj_auto_layout = QVBoxLayout(self.moj_auto_group)

        moj_auto_layout.addWidget(
            QLabel('マップ中心座標の市区町村から登記所備付地図を自動取得します。')
        )

        year_row = QHBoxLayout()
        year_row.addWidget(QLabel('年度:'))
        self.combo_moj_year = QComboBox()
        self.combo_moj_year.addItem('自動（最新）', '')
        self.combo_moj_year.addItem('2025', '2025')
        self.combo_moj_year.addItem('2024', '2024')
        self.combo_moj_year.addItem('2023', '2023')
        self.combo_moj_year.addItem('2022', '2022')
        year_row.addWidget(self.combo_moj_year)
        year_row.addStretch()
        moj_auto_layout.addLayout(year_row)

        self.moj_auto_group.hide()
        layout.addWidget(self.moj_auto_group)

        # --- 筆ポリゴン（オンライン表示）panel ---
        self.fude_group = QGroupBox('筆ポリゴン（オンライン表示）')
        fude_layout = QVBoxLayout(self.fude_group)

        fude_layout.addWidget(
            QLabel('農研機構 筆ポリゴン（FlatGeobuf）を\n'
                   'ダウンロードせずにオンラインで表示します。')
        )
        fude_layout.addWidget(
            QLabel('マップ中心座標から都道府県を自動判定し、\n'
                   '該当する筆ポリゴンデータを読み込みます。')
        )

        self.fude_group.hide()
        layout.addWidget(self.fude_group)

        # Progress
        self.progress = QProgressBar()
        self.progress.hide()
        layout.addWidget(self.progress)

        # Buttons
        btn_row = QHBoxLayout()
        self.btn_load = QPushButton('読込')
        self.btn_load.clicked.connect(self._on_load)
        btn_row.addWidget(self.btn_load)
        self.btn_cancel = QPushButton('中止')
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._on_cancel)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        layout.addStretch()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_source_changed(self):
        self.moj_group.setVisible(self.radio_moj.isChecked())
        self.kokudo_group.setVisible(self.radio_kokudo.isChecked())
        self.moj_auto_group.setVisible(self.radio_moj_auto.isChecked())
        self.fude_group.setVisible(self.radio_fude.isChecked())

        # Update button label
        if self.radio_fude.isChecked():
            self.btn_load.setText('レイヤ追加')
        elif self.radio_moj_auto.isChecked():
            self.btn_load.setText('取得')
        else:
            self.btn_load.setText('読込')

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'MOJ XMLファイルを選択',
            '', 'MOJ XML Files (*.xml *.zip);;All Files (*)',
        )
        if path:
            self.edit_file.setText(path)

    def _on_load(self):
        if self.radio_moj.isChecked():
            self._load_moj_xml()
        elif self.radio_kokudo.isChecked():
            self._load_kokudo()
        elif self.radio_moj_auto.isChecked():
            self._load_moj_auto()
        elif self.radio_fude.isChecked():
            self._load_fude_polygon()

    def _load_moj_xml(self):
        path = self.edit_file.text().strip()
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, 'エラー', 'ファイルを選択してください。')
            return

        self._set_busy(True)
        try:
            layer = self.service.load_moj_xml(
                path,
                include_arbitrary=self.chk_arbitrary.isChecked(),
                include_outside=self.chk_outside.isChecked(),
                auto_style=self.chk_auto_style.isChecked(),
            )
            if layer and layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                QMessageBox.information(
                    self, '完了',
                    f'{layer.featureCount()} 筆を読み込みました。'
                )
            else:
                QMessageBox.warning(self, 'エラー', '読込に失敗しました。')
        except Exception as e:
            QMessageBox.critical(self, 'エラー', str(e))
        finally:
            self._set_busy(False)

    def _load_kokudo(self):
        dataset_id = self.combo_dataset.currentData()
        selected = self.list_pref.selectedItems()
        if not selected:
            QMessageBox.warning(self, 'エラー', '都道府県を選択してください。')
            return

        pref_codes = []
        for item in selected:
            code = item.text().split('(')[-1].rstrip(')')
            pref_codes.append(code)

        fiscal_year = self.edit_year.text().strip()

        ds_name = self.combo_dataset.currentText()
        self.lbl_kokudo_status.setText(
            f'ダウンロード中... ({ds_name})')
        self._set_busy(True)
        self.progress.setMaximum(0)  # インデターミネート（不確定）表示
        self._download_thread = _KokudoDownloadThread(
            self.service, dataset_id, pref_codes, fiscal_year
        )
        self._download_thread.progress.connect(self._on_progress)
        self._download_thread.finished_ok.connect(self._on_kokudo_done)
        self._download_thread.error.connect(self._on_kokudo_error)
        self._download_thread.start()

    def _load_moj_auto(self):
        """マップ中心座標から登記所備付地図を自動取得."""
        # マップ中心座標を取得し EPSG:4326 に変換
        center = canvas_center_to_4326(self.iface)
        lat = center.y()
        lon = center.x()
        preferred_year = self.combo_moj_year.currentData() or ''

        self._set_busy(True)
        self.progress.setMaximum(0)  # indeterminate

        self._download_thread = _MojAutoDownloadThread(
            self.service, lat, lon, preferred_year
        )
        self._download_thread.finished_ok.connect(self._on_moj_auto_done)
        self._download_thread.error.connect(self._on_moj_auto_error)
        self._download_thread.start()

    def _load_fude_polygon(self):
        """筆ポリゴン FlatGeobuf をオンラインで読込."""
        # マップ中心座標から都道府県を判定
        try:
            center = canvas_center_to_4326(self.iface)
            lat = center.y()
            lon = center.x()
        except Exception as e:
            QMessageBox.critical(self, 'エラー', f'座標取得に失敗しました:\n{e}')
            return

        if not (20 <= lat <= 46 and 122 <= lon <= 154):
            QMessageBox.warning(
                self, 'エラー',
                f'現在の表示位置が日本国外です。\n'
                f'座標: 緯度={lat:.4f}, 経度={lon:.4f}\n'
                f'日本国内にマップを移動してください。'
            )
            return

        self._set_busy(True)
        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        QApplication.processEvents()

        try:
            pref_code = self._resolve_pref_code(lat, lon)
            if not pref_code:
                QMessageBox.warning(
                    self, 'エラー',
                    '都道府県を判定できませんでした。\n'
                    '地図上で陸地部分を表示してからお試しください。'
                )
                return

            pref_name = PREFECTURES.get(pref_code, pref_code)

            # 同名レイヤが既にあれば重複追加しない
            layer_name = f'筆ポリゴン_{pref_code}'
            for _lid, existing in QgsProject.instance().mapLayers().items():
                if existing.name() == layer_name:
                    QMessageBox.information(
                        self, '完了',
                        f'同じレイヤが既に読込済みです: {layer_name}'
                    )
                    return

            layer = self.service.load_fude_polygon_layer(pref_code)
            if layer and layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                QMessageBox.information(
                    self, '完了',
                    f'筆ポリゴンを追加しました: {pref_name}\n'
                    f'({layer.featureCount()} features)'
                )
            else:
                QMessageBox.warning(
                    self, 'エラー',
                    f'筆ポリゴンの読込に失敗しました。\n'
                    f'都道府県: {pref_name} ({pref_code})\n'
                    f'ログパネル(JLSA-Loader)を確認してください。'
                )
        except Exception as e:
            QMessageBox.critical(self, 'エラー', str(e))
        finally:
            QApplication.restoreOverrideCursor()
            self._set_busy(False)

    def _on_progress(self, current, total):
        if total > 0:
            self.progress.setMaximum(total)
            self.progress.setValue(current)
            self.lbl_kokudo_status.setText(
                f'ダウンロード中... ({current}/{total})')

    def _on_kokudo_done(self, results):
        """国土数値情報ダウンロード完了 — メインスレッドでレイヤ作成."""
        self._set_busy(False)
        if not results:
            self.lbl_kokudo_status.setText('データが見つかりませんでした。')
            QMessageBox.warning(self, '結果', 'データが見つかりませんでした。')
            return

        from ..core.kokudo_api_client import KokudoApiClient
        added = 0
        self.lbl_kokudo_status.setText('レイヤを読込中...')
        QApplication.processEvents()
        for extract_dir, dataset_id, pref_code in results:
            layer = KokudoApiClient._load_shapefile_dir(
                extract_dir, dataset_id, pref_code)
            if layer and layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                added += 1

        if added:
            self.lbl_kokudo_status.setText(f'完了: {added} レイヤを追加しました。')
            QMessageBox.information(
                self, '完了',
                f'{added} レイヤを追加しました。'
            )
        else:
            self.lbl_kokudo_status.setText('レイヤの読込に失敗しました。')
            QMessageBox.warning(self, '結果', 'レイヤの読込に失敗しました。')

    def _on_kokudo_error(self, msg):
        self._set_busy(False)
        self.lbl_kokudo_status.setText(f'エラー: {msg}')
        QMessageBox.critical(self, 'エラー', msg)

    def _on_moj_auto_done(self, source_path, layer_name):
        """MOJ自動取得成功時 — メインスレッドでレイヤを再作成."""
        self._set_busy(False)

        # 同名レイヤが既にあれば重複追加しない
        for _lid, existing in QgsProject.instance().mapLayers().items():
            if existing.name() == layer_name:
                QMessageBox.information(
                    self, '完了',
                    f'同じレイヤが既に読込済みです: {layer_name}'
                )
                return

        # メインスレッドでレイヤを作成（スレッドアフィニティ対策）
        layer = QgsVectorLayer(source_path, layer_name, 'ogr')
        if not layer or not layer.isValid():
            QMessageBox.warning(self, 'エラー', '読込に失敗しました。')
            return

        # パフォーマンス設定
        dp = layer.dataProvider()
        if dp.capabilities() & dp.CreateSpatialIndex:
            dp.createSpatialIndex()
        layer.setScaleBasedVisibility(True)
        layer.setMinimumScale(25000)
        layer.setMaximumScale(0)
        simplify = QgsVectorSimplifyMethod()
        simplify.setSimplifyHints(
            QgsVectorSimplifyMethod.GeometrySimplification
        )
        simplify.setThreshold(1.0)
        simplify.setForceLocalOptimization(True)
        layer.setSimplifyMethod(simplify)

        QgsProject.instance().addMapLayer(layer)
        QMessageBox.information(
            self, '完了',
            f'登記所備付地図を追加しました: {layer_name}\n'
            f'({layer.featureCount()} features)'
        )

    def _on_moj_auto_error(self, msg):
        """MOJ自動取得エラー時."""
        self._set_busy(False)
        QMessageBox.critical(self, 'エラー', f'登記所備付地図の取得に失敗しました:\n{msg}')

    def _on_cancel(self):
        if self._download_thread and self._download_thread.isRunning():
            self._download_thread.terminate()
        self._set_busy(False)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_busy(self, busy: bool):
        self.btn_load.setEnabled(not busy)
        self.btn_cancel.setEnabled(busy)
        if busy:
            self.progress.setValue(0)
            self.progress.show()
        else:
            self.progress.hide()

    def _update_plugin_status(self):
        bridge = PluginBridge()
        status = bridge.get_status_all()
        parts = []
        for pid, info in status.items():
            mark = '✓' if info['available'] else '✗'
            parts.append(f"{info['name']}: {mark}")
        self.lbl_plugin_status.setText(
            'プラグイン検出: ' + ' | '.join(parts)
        )

    def _detect_pref_from_map(self):
        """マップ中心座標から都道府県を判定し、リストで自動選択."""
        self.lbl_kokudo_status.setText('位置を検出中...')
        self.btn_detect_pref.setEnabled(False)
        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        QApplication.processEvents()

        try:
            center = canvas_center_to_4326(self.iface)
            lat = center.y()
            lon = center.x()
            QgsMessageLog.logMessage(
                f'現在地検出: lat={lat:.6f}, lon={lon:.6f}',
                'JLSA-Loader', Qgis.Info)

            # 日本国内チェック
            if not (20 <= lat <= 46 and 122 <= lon <= 154):
                self.lbl_kokudo_status.setText(
                    f'検出失敗 (座標: {lat:.4f}, {lon:.4f} — 日本国外)')
                QMessageBox.warning(
                    self, 'エラー',
                    f'現在の表示位置が日本国外です。\n'
                    f'座標: 緯度={lat:.4f}, 経度={lon:.4f}\n'
                    f'日本国内にマップを移動してください。'
                )
                return

            self.lbl_kokudo_status.setText(
                f'逆ジオコーダーに問い合わせ中... ({lat:.4f}, {lon:.4f})')
            QApplication.processEvents()

            pref_code = self._resolve_pref_code(lat, lon)

            if not pref_code:
                self.lbl_kokudo_status.setText('検出失敗')
                QMessageBox.warning(
                    self, 'エラー',
                    f'都道府県を判定できませんでした。\n'
                    f'座標: 緯度={lat:.4f}, 経度={lon:.4f}\n'
                    f'地図上で陸地部分を表示してからお試しください。'
                )
                return

            pref_name = PREFECTURES.get(pref_code, '')

            # リストの該当都道府県を選択
            self.list_pref.clearSelection()
            for i in range(self.list_pref.count()):
                item = self.list_pref.item(i)
                if f'({pref_code})' in item.text():
                    item.setSelected(True)
                    self.list_pref.scrollToItem(item)
                    break

            self.lbl_kokudo_status.setText(f'検出済み: {pref_name}')

        except Exception as e:
            QgsMessageLog.logMessage(
                f'現在地検出エラー: {e}', 'JLSA-Loader', Qgis.Warning)
            self.lbl_kokudo_status.setText(f'検出エラー: {e}')
            QMessageBox.critical(
                self, 'エラー', f'現在地の検出中にエラーが発生しました:\n{e}')
        finally:
            QApplication.restoreOverrideCursor()
            self.btn_detect_pref.setEnabled(True)

    def _resolve_pref_code(self, lat: float, lon: float):
        """複数の逆ジオコーダーで都道府県コードを取得（フォールバック付き）."""
        # 1. GSI 逆ジオコーダー
        try:
            from ..core.moj_geojson_downloader import MojGeoJsonDownloader
            downloader = MojGeoJsonDownloader()
            city_code = downloader.resolve_city_code(lat, lon)
            if city_code and len(city_code) >= 2:
                return city_code[:2]
        except Exception as e:
            QgsMessageLog.logMessage(
                f'GSI逆ジオコーダー失敗: {e}', 'JLSA-Loader', Qgis.Warning)

        self.lbl_kokudo_status.setText('GSI API 応答なし、別のAPIで再試行...')
        QApplication.processEvents()

        # 2. HeartRails Geo API (フォールバック)
        try:
            from ..core.geocoder import Geocoder
            geo = Geocoder()
            results = geo.reverse_geocode(lon, lat)
            if results:
                pref_name = results[0].get('prefecture', '')
                if pref_name:
                    # 都道府県名 → コード逆引き
                    for code, name in PREFECTURES.items():
                        if name == pref_name:
                            QgsMessageLog.logMessage(
                                f'HeartRails検出: {pref_name} ({code})',
                                'JLSA-Loader', Qgis.Info)
                            return code
        except Exception as e:
            QgsMessageLog.logMessage(
                f'HeartRails逆ジオコーダー失敗: {e}',
                'JLSA-Loader', Qgis.Warning)

        return None

    def cleanup(self):
        if self._download_thread and self._download_thread.isRunning():
            self._download_thread.terminate()
            self._download_thread.wait()
