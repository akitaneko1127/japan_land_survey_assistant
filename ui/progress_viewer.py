# -*- coding: utf-8 -*-
"""地籍調査進捗ビューアタブ."""

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QRadioButton,
    QLabel, QComboBox, QCheckBox, QPushButton, QFileDialog,
    QMessageBox, QListWidget, QAbstractItemView, QProgressBar,
)
from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.core import QgsProject, QgsVectorLayer, QgsWkbTypes
from qgis.gui import QgsVertexMarker

from ..core.chiseki_progress import ChisekiProgressManager
from ..core.crs_utils import canvas_center_to_4326
from ..services.data_loader_service import DataLoaderService
from .widgets.progress_chart import ProgressChartWidget


# Prefecture list for filter dropdown
_PREFS = [
    ('', '全国'),
    ('01', '北海道'), ('02', '青森県'), ('03', '岩手県'), ('04', '宮城県'),
    ('05', '秋田県'), ('06', '山形県'), ('07', '福島県'), ('08', '茨城県'),
    ('09', '栃木県'), ('10', '群馬県'), ('11', '埼玉県'), ('12', '千葉県'),
    ('13', '東京都'), ('14', '神奈川県'), ('15', '新潟県'), ('16', '富山県'),
    ('17', '石川県'), ('18', '福井県'), ('19', '山梨県'), ('20', '長野県'),
    ('21', '岐阜県'), ('22', '静岡県'), ('23', '愛知県'), ('24', '三重県'),
    ('25', '滋賀県'), ('26', '京都府'), ('27', '大阪府'), ('28', '兵庫県'),
    ('29', '奈良県'), ('30', '和歌山県'), ('31', '鳥取県'), ('32', '島根県'),
    ('33', '岡山県'), ('34', '広島県'), ('35', '山口県'), ('36', '徳島県'),
    ('37', '香川県'), ('38', '愛媛県'), ('39', '高知県'), ('40', '福岡県'),
    ('41', '佐賀県'), ('42', '長崎県'), ('43', '熊本県'), ('44', '大分県'),
    ('45', '宮崎県'), ('46', '鹿児島県'), ('47', '沖縄県'),
]


class _AdminDownloadThread(QThread):
    """行政区域データのバックグラウンドダウンロード.

    スレッドアフィニティ対策: QgsVectorLayer は作成せず
    shp ファイルパスとレイヤ名を返す。
    """
    finished_ok = pyqtSignal(str, str)  # shp_path, layer_name
    error = pyqtSignal(str)

    def __init__(self, service, pref_code):
        super().__init__()
        self.service = service
        self.pref_code = pref_code

    def run(self):
        try:
            shp_path, layer_name = self.service.download_admin_boundary_path(
                self.pref_code
            )
            if shp_path:
                self.finished_ok.emit(shp_path, layer_name)
            else:
                self.error.emit('行政区域データが見つかりませんでした。')
        except Exception as e:
            self.error.emit(str(e))


class ProgressViewerPanel(QWidget):
    """Cadastral survey progress viewer tab."""

    prefecture_detected = pyqtSignal(str, str)  # pref_code, pref_name

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.manager = ChisekiProgressManager()
        self.service = DataLoaderService()
        self._records = []
        self._download_thread = None
        self._marker = None
        self._detected_center = None  # QgsPointXY in map CRS
        self._detected_pref_code = None
        self._detected_pref_name = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Display mode
        mode_group = QGroupBox('表示モード')
        mode_layout = QVBoxLayout(mode_group)
        self.radio_progress = QRadioButton('進捗率マップ')
        self.radio_status = QRadioButton('実施状況マップ')
        self.radio_progress.setChecked(True)
        mode_layout.addWidget(self.radio_progress)
        mode_layout.addWidget(self.radio_status)
        layout.addWidget(mode_group)

        # Filters
        filter_group = QGroupBox('フィルタ')
        filter_layout = QVBoxLayout(filter_group)

        pref_row = QHBoxLayout()
        pref_row.addWidget(QLabel('都道府県:'))
        self.combo_pref = QComboBox()
        for code, name in _PREFS:
            self.combo_pref.addItem(name, code)
        pref_row.addWidget(self.combo_pref)
        self.btn_detect_pref = QPushButton('現在地から設定')
        self.btn_detect_pref.clicked.connect(self._detect_pref_from_map)
        pref_row.addWidget(self.btn_detect_pref)
        filter_layout.addLayout(pref_row)

        filter_layout.addWidget(QLabel('ステータス:'))
        self.chk_done = QCheckBox('完了')
        self.chk_done.setChecked(True)
        self.chk_inprog = QCheckBox('実施中')
        self.chk_inprog.setChecked(True)
        self.chk_suspended = QCheckBox('休止中')
        self.chk_suspended.setChecked(True)
        self.chk_not_started = QCheckBox('未着手')
        self.chk_not_started.setChecked(True)
        status_row = QHBoxLayout()
        status_row.addWidget(self.chk_done)
        status_row.addWidget(self.chk_inprog)
        status_row.addWidget(self.chk_suspended)
        status_row.addWidget(self.chk_not_started)
        filter_layout.addLayout(status_row)

        layout.addWidget(filter_group)

        # Chart widget
        self.chart = ProgressChartWidget(self)
        self.chart.setMinimumHeight(120)
        layout.addWidget(self.chart)

        # Admin layer selection
        layer_row = QHBoxLayout()
        layer_row.addWidget(QLabel('行政区域レイヤ:'))
        self.combo_admin_layer = QComboBox()
        self.btn_refresh_layers = QPushButton('更新')
        self.btn_refresh_layers.clicked.connect(self._refresh_layers)
        layer_row.addWidget(self.combo_admin_layer, 1)
        layer_row.addWidget(self.btn_refresh_layers)
        layout.addLayout(layer_row)

        # Action buttons
        btn_row = QHBoxLayout()
        self.btn_create = QPushButton('レイヤ作成')
        self.btn_create.clicked.connect(self._create_layer)
        btn_row.addWidget(self.btn_create)

        self.btn_export = QPushButton('CSV出力')
        self.btn_export.clicked.connect(self._export_csv)
        btn_row.addWidget(self.btn_export)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        layout.addStretch()

        # Initial load
        self._load_data()
        self._refresh_layers()

    # ------------------------------------------------------------------
    # 現在地から都道府県を自動判定 + 行政区域自動取得
    # ------------------------------------------------------------------

    def _detect_pref_from_map(self):
        """マップ中心座標から都道府県を自動判定.

        1回目: マーカーを表示し都道府県をコンボに設定（プレビュー）
        2回目: 行政区域レイヤ取得・進捗レイヤ作成を実行
        """
        canvas = self.iface.mapCanvas()
        map_center = canvas.center()  # map CRS

        center_4326 = canvas_center_to_4326(self.iface)
        lat = center_4326.y()
        lon = center_4326.x()

        # 2回目クリック: 既にマーカー表示済みなら確定処理へ
        if self._detected_pref_code is not None:
            self._confirm_pref_setting()
            return

        # 1回目: 逆ジオコーダーで都道府県判定 + マーカー表示
        from ..core.moj_geojson_downloader import MojGeoJsonDownloader
        downloader = MojGeoJsonDownloader()
        city_code = downloader.resolve_city_code(lat, lon)

        if not city_code or len(city_code) < 2:
            QMessageBox.warning(
                self, 'エラー',
                '現在の表示位置から都道府県を判定できませんでした。\n'
                '日本国内にマップを移動してください。'
            )
            return

        pref_code = city_code[:2]

        # コンボボックスで該当都道府県を選択
        pref_name = ''
        for i in range(self.combo_pref.count()):
            if self.combo_pref.itemData(i) == pref_code:
                self.combo_pref.setCurrentIndex(i)
                pref_name = self.combo_pref.itemText(i)
                break

        self._update_chart()

        # マーカーを表示
        self._show_marker(map_center)

        # 状態を保存
        self._detected_center = map_center
        self._detected_pref_code = pref_code
        self._detected_pref_name = pref_name

        # 地番検索パネルに都道府県検出を通知
        self.prefecture_detected.emit(pref_code, pref_name)

        # ボタンラベル変更
        self.btn_detect_pref.setText(f'{pref_name} で確定')

    def _confirm_pref_setting(self):
        """2回目クリック: 行政区域取得・進捗レイヤ作成を実行."""
        pref_code = self._detected_pref_code
        pref_name = self._detected_pref_name

        # マーカー・状態リセット
        self._clear_marker()
        self._detected_pref_code = None
        self._detected_pref_name = None
        self._detected_center = None
        self.btn_detect_pref.setText('現在地から設定')

        # 行政区域ポリゴンレイヤがプロジェクトにあるか確認
        self._refresh_layers()
        if self.combo_admin_layer.count() > 0:
            QMessageBox.information(
                self, '検出',
                f'{pref_name} を設定しました。\n'
                '行政区域レイヤは既に読込済みです。'
            )
            return

        # 行政区域レイヤがないので自動ダウンロード
        reply = QMessageBox.question(
            self, '行政区域レイヤ',
            f'{pref_name} の行政区域レイヤがありません。\n'
            '国土数値情報から自動ダウンロードしますか？',
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._pending_pref_code = pref_code
        self._set_busy(True)

        self._download_thread = _AdminDownloadThread(self.service, pref_code)
        self._download_thread.finished_ok.connect(self._on_admin_download_done)
        self._download_thread.error.connect(self._on_admin_download_error)
        self._download_thread.start()

    def _show_marker(self, point):
        """マップ上にマーカーを表示."""
        self._clear_marker()
        canvas = self.iface.mapCanvas()
        self._marker = QgsVertexMarker(canvas)
        self._marker.setCenter(point)
        self._marker.setColor(QColor(255, 0, 0))
        self._marker.setFillColor(QColor(255, 0, 0, 128))
        self._marker.setIconSize(15)
        self._marker.setIconType(QgsVertexMarker.ICON_CROSS)
        self._marker.setPenWidth(3)

    def _clear_marker(self):
        """マーカーを消去."""
        if self._marker:
            canvas = self.iface.mapCanvas()
            canvas.scene().removeItem(self._marker)
            self._marker = None

    def _on_admin_download_done(self, shp_path, layer_name):
        """行政区域ダウンロード完了 → メインスレッドでレイヤ作成."""
        self._set_busy(False)

        # メインスレッドで QgsVectorLayer を作成
        layer = QgsVectorLayer(shp_path, layer_name, 'ogr')
        if not layer or not layer.isValid():
            QMessageBox.warning(self, 'エラー', '行政区域レイヤの読込に失敗しました。')
            return

        QgsProject.instance().addMapLayer(layer)

        self._refresh_layers()

        if self.combo_admin_layer.count() == 0:
            QMessageBox.warning(self, 'エラー', '行政区域レイヤが見つかりません。')
            return

        # 自動で進捗レイヤを作成
        self._create_layer()

    def _on_admin_download_error(self, msg):
        self._set_busy(False)
        QMessageBox.critical(self, 'エラー', f'行政区域データの取得に失敗しました:\n{msg}')

    def _set_busy(self, busy: bool):
        self.btn_detect_pref.setEnabled(not busy)
        self.btn_create.setEnabled(not busy)
        if busy:
            self.btn_detect_pref.setText('取得中...')
        else:
            self.btn_detect_pref.setText('現在地から設定')

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def _load_data(self):
        self._records = self.manager.load_csv()
        self._update_chart()

    def _get_selected_statuses(self):
        statuses = []
        if self.chk_done.isChecked():
            statuses.append('完了')
        if self.chk_inprog.isChecked():
            statuses.append('実施中')
        if self.chk_suspended.isChecked():
            statuses.append('休止中')
        if self.chk_not_started.isChecked():
            statuses.append('未着手')
        return statuses

    def _get_filtered_records(self):
        return self.manager.filter_records(
            self._records,
            pref_code=self.combo_pref.currentData() or '',
            statuses=self._get_selected_statuses(),
        )

    def _update_chart(self):
        filtered = self._get_filtered_records()
        self.chart.update_data(filtered)

    # ------------------------------------------------------------------
    # Layer operations
    # ------------------------------------------------------------------

    def _refresh_layers(self):
        self.combo_admin_layer.clear()
        for layer_id, layer in QgsProject.instance().mapLayers().items():
            if (isinstance(layer, QgsVectorLayer)
                    and layer.geometryType() == QgsWkbTypes.PolygonGeometry
                    and layer.fields().indexOf('N03_007') >= 0):
                self.combo_admin_layer.addItem(layer.name(), layer_id)

    def _create_layer(self):
        """行政区域レイヤに直接フィルタとスタイルを適用."""
        layer_id = self.combo_admin_layer.currentData()
        if not layer_id:
            QMessageBox.warning(self, 'エラー', '行政区域レイヤを選択してください。')
            return

        admin_layer = QgsProject.instance().mapLayer(layer_id)
        if not admin_layer:
            return

        filtered = self._get_filtered_records()
        if not filtered:
            QMessageBox.warning(self, 'エラー', 'データがありません。')
            return

        # N03_007 フィールドの存在確認
        join_field = 'N03_007'
        if admin_layer.fields().indexOf(join_field) < 0:
            QMessageBox.warning(
                self, 'エラー',
                f'行政区域レイヤに {join_field} フィールドがありません。'
            )
            return

        # 進捗データから一致する市区町村コードを収集
        matching_codes = self.manager.find_matching_codes(
            admin_layer, filtered, join_field
        )

        if not matching_codes:
            QMessageBox.warning(
                self, 'エラー',
                '行政区域レイヤと進捗データの市区町村コードが一致しませんでした。'
            )
            return

        # 行政区域レイヤにフィルタ適用
        codes_str = ','.join(f"'{c}'" for c in sorted(matching_codes))
        admin_layer.setSubsetString(f"{join_field} IN ({codes_str})")

        # スタイル適用
        self.manager.apply_direct_style(
            admin_layer, filtered, join_field,
            use_progress=self.radio_progress.isChecked()
        )

        # レイヤ名を変更して識別しやすくする
        admin_layer.setName(f'{admin_layer.name()} - 地籍調査進捗')

        admin_layer.triggerRepaint()
        self.iface.layerTreeView().refreshLayerSymbology(admin_layer.id())

        # フィルタ後の範囲にズーム (QGIS内蔵のズーム機能を使用)
        self.iface.setActiveLayer(admin_layer)
        self.iface.zoomToActiveLayer()

        QMessageBox.information(
            self, '完了',
            f'進捗スタイルを適用しました。（{len(matching_codes)} 件一致）'
        )

    def _export_csv(self):
        filtered = self._get_filtered_records()
        if not filtered:
            QMessageBox.warning(self, 'エラー', 'データがありません。')
            return

        path, _ = QFileDialog.getSaveFileName(
            self, 'CSV出力先', '', 'CSV Files (*.csv)',
        )
        if path:
            self.manager.export_csv(filtered, path)
            QMessageBox.information(self, '完了', f'{path} に出力しました。')

    def cleanup(self):
        self._clear_marker()
        if self._download_thread and self._download_thread.isRunning():
            self._download_thread.terminate()
            self._download_thread.wait()
