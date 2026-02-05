# -*- coding: utf-8 -*-
"""地番検索タブ."""

import csv

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QComboBox, QLineEdit, QPushButton, QMessageBox,
    QFileDialog, QApplication, QProgressBar, QCheckBox,
)
from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsPointXY, QgsWkbTypes,
    QgsCoordinateTransform, QgsCoordinateReferenceSystem,
    QgsGeometry, QgsRectangle, QgsVectorSimplifyMethod,
)
from qgis.gui import QgsMapToolEmitPoint, QgsRubberBand, QgsVertexMarker
from qgis.PyQt.QtGui import QColor

from ..core.parcel_searcher import ParcelSearcher
from ..core.crs_utils import (
    canvas_center_to_4326, layer_extent_to_canvas, zoom_to_feature_extent,
)
from .widgets.parcel_info_card import ParcelInfoCard


class _ParcelAutoLoadThread(QThread):
    """MOJデータの非同期ダウンロード.

    QgsVectorLayer は QObject でスレッドアフィニティがあるため、
    ワーカースレッドで作成したレイヤをメインスレッドで使うとデータが空になる。
    そのためファイルパスとレイヤ名だけを返し、メインスレッドでレイヤを再作成する。
    """

    finished_ok = pyqtSignal(str, str)  # source_path, layer_name
    error = pyqtSignal(str)

    def __init__(self, lat, lon):
        super().__init__()
        self.lat = lat
        self.lon = lon

    def run(self):
        try:
            from ..services.data_loader_service import DataLoaderService
            service = DataLoaderService()
            layer = service.load_moj_from_extent(self.lat, self.lon)
            if layer and layer.isValid():
                self.finished_ok.emit(layer.source(), layer.name())
            else:
                self.error.emit('MOJデータの取得に失敗しました。')
        except Exception as e:
            self.error.emit(str(e))


class ParcelSearchPanel(QWidget):
    """Parcel search tab with attribute search and map click."""

    status_message = pyqtSignal(str)
    auto_load_started = pyqtSignal()
    auto_load_finished = pyqtSignal()

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.searcher = ParcelSearcher()
        self._map_tool = None
        self._prev_map_tool = None
        self._rubber_band = None
        self._search_area_band = None
        self._current_feature = None
        self._auto_load_thread = None
        # 2段階検出用の状態
        self._detect_marker = None
        self._detected_lat = None
        self._detected_lon = None
        self._detected_map_center = None
        self._setup_ui()
        self._refresh_layers()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # --- 位置検出エリア ---
        detect_group = QGroupBox('位置検出')
        detect_layout = QVBoxLayout(detect_group)

        detect_row = QHBoxLayout()
        self.btn_detect = QPushButton('現在地から検出')
        self.btn_detect.clicked.connect(self._on_detect_clicked)
        detect_row.addWidget(self.btn_detect)
        detect_row.addStretch()
        detect_layout.addLayout(detect_row)

        self.lbl_auto_status = QLabel('')
        self.lbl_auto_status.setStyleSheet('color: #555;')
        detect_layout.addWidget(self.lbl_auto_status)

        self.auto_progress = QProgressBar()
        self.auto_progress.setFixedHeight(8)
        self.auto_progress.setRange(0, 0)  # indeterminate
        self.auto_progress.hide()
        detect_layout.addWidget(self.auto_progress)

        layout.addWidget(detect_group)

        # Target layer
        layer_row = QHBoxLayout()
        layer_row.addWidget(QLabel('対象レイヤ:'))
        self.combo_layer = QComboBox()
        self.combo_layer.currentIndexChanged.connect(self._on_layer_changed)
        layer_row.addWidget(self.combo_layer, 1)
        btn_refresh = QPushButton('更新')
        btn_refresh.clicked.connect(self._refresh_layers)
        layer_row.addWidget(btn_refresh)
        layout.addLayout(layer_row)

        # 枠線のみ表示
        self.chk_outline_only = QCheckBox('枠線のみ表示（塗りつぶしなし）')
        self.chk_outline_only.setChecked(True)
        self.chk_outline_only.toggled.connect(self._on_outline_only_changed)
        layout.addWidget(self.chk_outline_only)

        # Search by attribute
        search_group = QGroupBox('属性検索')
        search_layout = QVBoxLayout(search_group)

        oaza_row = QHBoxLayout()
        oaza_row.addWidget(QLabel('大字:'))
        self.combo_oaza = QComboBox()
        self.combo_oaza.addItem('（全て）', '')
        self.combo_oaza.currentIndexChanged.connect(self._on_oaza_changed)
        oaza_row.addWidget(self.combo_oaza, 1)
        search_layout.addLayout(oaza_row)

        aza_row = QHBoxLayout()
        aza_row.addWidget(QLabel('字:'))
        self.combo_aza = QComboBox()
        self.combo_aza.addItem('（全て）', '')
        aza_row.addWidget(self.combo_aza, 1)
        search_layout.addLayout(aza_row)

        chiban_row = QHBoxLayout()
        chiban_row.addWidget(QLabel('地番:'))
        self.edit_chiban = QLineEdit()
        self.edit_chiban.setPlaceholderText('例: 1-2')
        self.edit_chiban.returnPressed.connect(self._on_search)
        chiban_row.addWidget(self.edit_chiban, 1)
        search_layout.addLayout(chiban_row)

        btn_search_row = QHBoxLayout()
        self.btn_search = QPushButton('検索')
        self.btn_search.clicked.connect(self._on_search)
        btn_search_row.addWidget(self.btn_search)
        self.btn_map_click = QPushButton('地図クリック検索')
        self.btn_map_click.setCheckable(True)
        self.btn_map_click.clicked.connect(self._toggle_map_click)
        btn_search_row.addWidget(self.btn_map_click)
        btn_search_row.addStretch()
        search_layout.addLayout(btn_search_row)

        layout.addWidget(search_group)

        # Result card
        self.info_card = ParcelInfoCard(self)
        layout.addWidget(self.info_card)

        # Action buttons
        action_row = QHBoxLayout()
        self.btn_zoom = QPushButton('ズーム')
        self.btn_zoom.clicked.connect(self._zoom_to_feature)
        self.btn_zoom.setEnabled(False)
        action_row.addWidget(self.btn_zoom)

        self.btn_select = QPushButton('選択')
        self.btn_select.clicked.connect(self._select_feature)
        self.btn_select.setEnabled(False)
        action_row.addWidget(self.btn_select)

        self.btn_copy = QPushButton('属性コピー')
        self.btn_copy.clicked.connect(self._copy_attrs)
        self.btn_copy.setEnabled(False)
        action_row.addWidget(self.btn_copy)

        self.btn_csv_export = QPushButton('CSV出力')
        self.btn_csv_export.clicked.connect(self._export_csv)
        self.btn_csv_export.setEnabled(False)
        action_row.addWidget(self.btn_csv_export)

        action_row.addStretch()
        layout.addLayout(action_row)

        layout.addStretch()

    # ------------------------------------------------------------------
    # 2段階検出: 1回目=マーカー表示 / 2回目=確定→データ取得
    # ------------------------------------------------------------------

    def _on_detect_clicked(self):
        """検出ボタンのクリックハンドラ（2段階）."""
        # 2回目: 確定 → データ取得
        if self._detected_lat is not None:
            self._confirm_and_load()
            return

        # 1回目: 現在位置を判定してマーカー表示
        self._detect_position()

    def _detect_position(self):
        """1回目: マップ中心から位置を判定しマーカー表示."""
        center_4326 = canvas_center_to_4326(self.iface)
        lat = center_4326.y()
        lon = center_4326.x()

        # 日本国内チェック
        if not (20 <= lat <= 46 and 122 <= lon <= 154):
            self.lbl_auto_status.setText(
                '日本国外のため検出できません。日本国内にマップを移動してください。'
            )
            return

        # 逆ジオコーダーで地名を取得（UIブロック短いので同期で可）
        from ..core.moj_geojson_downloader import MojGeoJsonDownloader
        downloader = MojGeoJsonDownloader()
        city_code = downloader.resolve_city_code(lat, lon)
        if not city_code:
            self.lbl_auto_status.setText(
                '市区町村を判定できませんでした。マップを移動して再度お試しください。'
            )
            return

        # 既存レイヤがあるかチェック
        existing = self._find_moj_layer_for_position(lat, lon)
        if existing:
            self._select_layer_in_combo(existing)
            self._show_search_area_boundary(existing)
            self.lbl_auto_status.setText(f'既存レイヤを選択: {existing.name()}')
            self.status_message.emit(f'MOJレイヤ検出: {existing.name()}')
            return

        # マーカー表示
        canvas = self.iface.mapCanvas()
        map_center = canvas.center()
        self._show_detect_marker(map_center)

        # 状態を保存
        self._detected_lat = lat
        self._detected_lon = lon
        self._detected_map_center = map_center

        # ボタンラベルを「確定」に変更
        self.lbl_auto_status.setText(
            f'市区町村コード: {city_code} を検出しました。'
        )
        self.btn_detect.setText(f'この位置で取得')
        self.status_message.emit(f'位置検出: {city_code}  — 「この位置で取得」で確定')

    def _confirm_and_load(self):
        """2回目: 確定してMOJデータをダウンロード."""
        lat = self._detected_lat
        lon = self._detected_lon

        # マーカー・状態リセット
        self._clear_detect_marker()
        self._detected_lat = None
        self._detected_lon = None
        self._detected_map_center = None
        self.btn_detect.setText('現在地から検出')

        # ダウンロード開始
        self._start_download(lat, lon)

    def _reset_detect_state(self):
        """検出状態をリセット."""
        self._clear_detect_marker()
        self._detected_lat = None
        self._detected_lon = None
        self._detected_map_center = None
        self.btn_detect.setText('現在地から検出')

    # ------------------------------------------------------------------
    # Detect marker
    # ------------------------------------------------------------------

    def _show_detect_marker(self, point):
        """マップ上に検出位置マーカーを表示."""
        self._clear_detect_marker()
        canvas = self.iface.mapCanvas()
        self._detect_marker = QgsVertexMarker(canvas)
        self._detect_marker.setCenter(point)
        self._detect_marker.setColor(QColor(0, 100, 255))
        self._detect_marker.setFillColor(QColor(0, 100, 255, 128))
        self._detect_marker.setIconSize(15)
        self._detect_marker.setIconType(QgsVertexMarker.ICON_CROSS)
        self._detect_marker.setPenWidth(3)

    def _clear_detect_marker(self):
        """マーカーを消去."""
        if self._detect_marker:
            canvas = self.iface.mapCanvas()
            canvas.scene().removeItem(self._detect_marker)
            self._detect_marker = None

    # ------------------------------------------------------------------
    # Auto-detect on tab activated
    # ------------------------------------------------------------------

    def on_tab_activated(self):
        """タブ表示時: レイヤ一覧更新 + 既存MOJレイヤがあれば自動選択."""
        self._refresh_layers()

        layer = self._find_moj_layer_for_current_position()
        if layer:
            self._select_layer_in_combo(layer)
            self._show_search_area_boundary(layer)
            self.lbl_auto_status.setText(f'検出済み: {layer.name()}')
            self.status_message.emit(f'MOJレイヤ検出: {layer.name()}')

    def _find_moj_layer_for_current_position(self):
        """プロジェクト内の「登記所備付地図_*」レイヤから現在位置を含むものを検索."""
        center_4326 = canvas_center_to_4326(self.iface)
        return self._find_moj_layer_for_position(center_4326.y(), center_4326.x())

    def _find_moj_layer_for_position(self, lat, lon):
        """指定座標を含む「登記所備付地図_*」レイヤを検索."""
        crs_4326 = QgsCoordinateReferenceSystem('EPSG:4326')
        pt_4326 = QgsPointXY(lon, lat)

        for _lid, layer in QgsProject.instance().mapLayers().items():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if not layer.name().startswith('登記所備付地図'):
                continue
            if layer.geometryType() != QgsWkbTypes.PolygonGeometry:
                continue

            layer_crs = layer.crs()
            center_pt = QgsPointXY(pt_4326)
            if layer_crs != crs_4326:
                xform = QgsCoordinateTransform(
                    crs_4326, layer_crs, QgsProject.instance()
                )
                center_pt = xform.transform(center_pt)

            if layer.extent().contains(center_pt):
                return layer

        return None

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def _start_download(self, lat, lon):
        """MOJデータの非同期ダウンロードを開始."""
        if self._auto_load_thread and self._auto_load_thread.isRunning():
            return

        self.lbl_auto_status.setText('MOJデータを取得中...')
        self.auto_progress.show()
        self.btn_detect.setEnabled(False)
        self.auto_load_started.emit()
        self.status_message.emit('MOJデータを取得中...')

        self._auto_load_thread = _ParcelAutoLoadThread(lat, lon)
        self._auto_load_thread.finished_ok.connect(self._on_auto_load_done)
        self._auto_load_thread.error.connect(self._on_auto_load_error)
        self._auto_load_thread.start()

    def _on_auto_load_done(self, source_path, layer_name):
        """自動ダウンロード完了 — メインスレッドでレイヤを再作成."""
        self.auto_progress.hide()
        self.btn_detect.setEnabled(True)
        self.auto_load_finished.emit()

        # 同名レイヤが既にあれば重複追加しない
        for _lid, existing in QgsProject.instance().mapLayers().items():
            if existing.name() == layer_name:
                self._refresh_layers()
                self._select_layer_in_combo(existing)
                self._show_search_area_boundary(existing)
                self.lbl_auto_status.setText(f'既存レイヤを使用: {layer_name}')
                self.status_message.emit(f'既存レイヤを使用: {layer_name}')
                return

        # メインスレッドでレイヤを作成（スレッドアフィニティ対策）
        layer = QgsVectorLayer(source_path, layer_name, 'ogr')
        if not layer or not layer.isValid():
            self.lbl_auto_status.setText('MOJデータの読込に失敗しました')
            self.status_message.emit('MOJデータ読込失敗')
            return

        # パフォーマンス設定（MojGeoJsonDownloader.load_as_layer と同等）
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

        # プロジェクトに追加
        QgsProject.instance().addMapLayer(layer)

        # コンボ更新・選択
        self._refresh_layers()
        self._select_layer_in_combo(layer)

        # 検索エリア枠表示
        self._show_search_area_boundary(layer)

        self.lbl_auto_status.setText(f'取得完了: {layer.name()}')
        self.status_message.emit(f'MOJデータ取得完了: {layer.name()}')

    def _on_auto_load_error(self, msg):
        """自動ダウンロードエラー."""
        self.auto_progress.hide()
        self.btn_detect.setEnabled(True)
        self.auto_load_finished.emit()
        self.lbl_auto_status.setText(f'取得エラー: {msg}')
        self.status_message.emit(f'MOJデータ取得エラー: {msg}')

    # ------------------------------------------------------------------
    # Search area boundary (blue frame)
    # ------------------------------------------------------------------

    def _show_search_area_boundary(self, layer):
        """青い境界枠の表示."""
        self._clear_search_area_boundary()
        canvas = self.iface.mapCanvas()
        self._search_area_band = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
        self._search_area_band.setColor(QColor(0, 100, 255, 180))
        self._search_area_band.setFillColor(QColor(0, 100, 255, 20))
        self._search_area_band.setWidth(2)

        extent = layer_extent_to_canvas(layer, self.iface)
        rect_geom = QgsGeometry.fromRect(extent)
        self._search_area_band.setToGeometry(rect_geom)

    def _clear_search_area_boundary(self):
        """枠の消去."""
        if self._search_area_band:
            self._search_area_band.reset()
            self._search_area_band = None

    # ------------------------------------------------------------------
    # Layer combo helpers
    # ------------------------------------------------------------------

    def _select_layer_in_combo(self, layer):
        """コンボボックスでレイヤを自動選択."""
        target_id = layer.id()
        for i in range(self.combo_layer.count()):
            if self.combo_layer.itemData(i) == target_id:
                self.combo_layer.setCurrentIndex(i)
                return

    # ------------------------------------------------------------------
    # Prefecture detection from progress viewer
    # ------------------------------------------------------------------

    def on_prefecture_detected(self, pref_code, pref_name):
        """進捗ビューからの都道府県検出連動."""
        self.lbl_auto_status.setText(
            f'{pref_name} が検出されました。'
            '「現在地から検出」でMOJデータを取得できます。'
        )

    # ------------------------------------------------------------------
    # Layer management
    # ------------------------------------------------------------------

    def _refresh_layers(self):
        self.combo_layer.clear()
        for lid, layer in QgsProject.instance().mapLayers().items():
            if isinstance(layer, QgsVectorLayer) and layer.geometryType() == QgsWkbTypes.PolygonGeometry:
                self.combo_layer.addItem(layer.name(), lid)

    def _get_target_layer(self) -> QgsVectorLayer:
        lid = self.combo_layer.currentData()
        if lid:
            return QgsProject.instance().mapLayer(lid)
        return None

    def _on_layer_changed(self):
        self.combo_oaza.clear()
        self.combo_oaza.addItem('（全て）', '')
        self.combo_aza.clear()
        self.combo_aza.addItem('（全て）', '')

        layer = self._get_target_layer()
        if not layer:
            self._clear_search_area_boundary()
            return

        for val in self.searcher.get_unique_oaza(layer):
            self.combo_oaza.addItem(val, val)

        # MOJレイヤ選択時に検索エリア枠を表示
        if layer.name().startswith('登記所備付地図'):
            self._show_search_area_boundary(layer)
        else:
            self._clear_search_area_boundary()

        # 枠線のみ表示の状態を適用
        if self.chk_outline_only.isChecked():
            self._apply_outline_style(layer)

    def _on_outline_only_changed(self, checked):
        """枠線のみ表示の切替."""
        layer = self._get_target_layer()
        if not layer:
            return
        if checked:
            self._apply_outline_style(layer)
        else:
            self._apply_filled_style(layer)

    def _apply_outline_style(self, layer):
        """レイヤを枠線のみスタイルに変更."""
        from qgis.core import (
            QgsSimpleFillSymbolLayer, QgsFillSymbol, QgsSingleSymbolRenderer,
        )
        symbol = QgsFillSymbol()
        sl = symbol.symbolLayer(0)
        if isinstance(sl, QgsSimpleFillSymbolLayer):
            sl.setFillColor(QColor(0, 0, 0, 0))  # 塗りつぶしなし
            sl.setStrokeColor(QColor(50, 50, 50, 255))
            sl.setStrokeWidth(0.3)
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        layer.triggerRepaint()

    def _apply_filled_style(self, layer):
        """レイヤを塗りつぶしスタイルに戻す."""
        from qgis.core import QgsSimpleFillSymbolLayer, QgsFillSymbol, QgsSingleSymbolRenderer
        symbol = QgsFillSymbol()
        sl = symbol.symbolLayer(0)
        if isinstance(sl, QgsSimpleFillSymbolLayer):
            sl.setFillColor(QColor(180, 210, 240, 120))
            sl.setStrokeColor(QColor(50, 50, 50, 255))
            sl.setStrokeWidth(0.3)
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        layer.triggerRepaint()

    def _on_oaza_changed(self):
        self.combo_aza.clear()
        self.combo_aza.addItem('（全て）', '')
        oaza = self.combo_oaza.currentData() or ''
        layer = self._get_target_layer()
        if not layer or not oaza:
            return
        for val in self.searcher.get_unique_aza(layer, oaza):
            self.combo_aza.addItem(val, val)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def _on_search(self):
        layer = self._get_target_layer()
        if not layer:
            QMessageBox.warning(self, 'エラー', '対象レイヤを選択してください。')
            return

        chiban = self.edit_chiban.text().strip()
        if not chiban:
            QMessageBox.warning(self, 'エラー', '地番を入力してください。')
            return

        oaza = self.combo_oaza.currentData() or ''
        aza = self.combo_aza.currentData() or ''

        features = self.searcher.search_by_parcel_number(
            layer, chiban, oaza, aza
        )

        if not features:
            # Try fuzzy
            features = self.searcher.search_like(layer, chiban)

        if not features:
            QMessageBox.information(self, '結果', '該当する筆が見つかりません。')
            self._clear_result()
            return

        self._show_result(features[0])
        # 検索結果の位置にズーム
        self._zoom_to_feature()

    # ------------------------------------------------------------------
    # Map click
    # ------------------------------------------------------------------

    def _toggle_map_click(self, checked):
        canvas = self.iface.mapCanvas()
        if checked:
            self._prev_map_tool = canvas.mapTool()
            self._map_tool = QgsMapToolEmitPoint(canvas)
            self._map_tool.canvasClicked.connect(self._on_map_clicked)
            canvas.setMapTool(self._map_tool)
            # ツールが外部から切り替えられた場合にボタン状態を同期
            canvas.mapToolSet.connect(self._on_map_tool_changed)
        else:
            try:
                canvas.mapToolSet.disconnect(self._on_map_tool_changed)
            except TypeError:
                pass
            if self._prev_map_tool:
                canvas.setMapTool(self._prev_map_tool)
            self._map_tool = None

    def _on_map_tool_changed(self, new_tool):
        """マップツールが外部から変更されたらボタンをOFFにする."""
        if new_tool is not self._map_tool:
            self.btn_map_click.setChecked(False)
            self._map_tool = None
            try:
                canvas = self.iface.mapCanvas()
                canvas.mapToolSet.disconnect(self._on_map_tool_changed)
            except TypeError:
                pass

    def _on_map_clicked(self, point, button):
        layer = self._get_target_layer()
        if not layer:
            return

        # キャンバスCRS → レイヤCRS に変換
        canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        layer_crs = layer.crs()
        if canvas_crs != layer_crs:
            xform = QgsCoordinateTransform(
                canvas_crs, layer_crs, QgsProject.instance()
            )
            point = xform.transform(point)

        feature = self.searcher.search_by_point(layer, point)
        if feature:
            self._show_result(feature)
        else:
            self._clear_result()

    # ------------------------------------------------------------------
    # Result display
    # ------------------------------------------------------------------

    def _show_result(self, feature):
        self._current_feature = feature
        info = self.searcher.feature_to_dict(feature)
        self.info_card.show_info(info)
        self._highlight_feature(feature)

        self.btn_zoom.setEnabled(True)
        self.btn_select.setEnabled(True)
        self.btn_copy.setEnabled(True)
        self.btn_csv_export.setEnabled(True)

    def _clear_result(self):
        self._current_feature = None
        self.info_card.clear_info()
        self._clear_highlight()
        self.btn_zoom.setEnabled(False)
        self.btn_select.setEnabled(False)
        self.btn_copy.setEnabled(False)
        self.btn_csv_export.setEnabled(False)

    def _highlight_feature(self, feature):
        self._clear_highlight()
        canvas = self.iface.mapCanvas()
        self._rubber_band = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
        self._rubber_band.setColor(QColor(255, 0, 0, 128))
        self._rubber_band.setWidth(2)
        self._rubber_band.setToGeometry(feature.geometry(),
                                        self._get_target_layer())

    def _clear_highlight(self):
        if self._rubber_band:
            self._rubber_band.reset()
            self._rubber_band = None

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _zoom_to_feature(self):
        if not self._current_feature:
            return
        layer = self._get_target_layer()
        if not layer:
            return
        zoom_to_feature_extent(self._current_feature, layer, self.iface)

    def _select_feature(self):
        layer = self._get_target_layer()
        if layer and self._current_feature:
            layer.selectByIds([self._current_feature.id()])

    def _copy_attrs(self):
        if not self._current_feature:
            return
        info = self.searcher.feature_to_dict(self._current_feature)
        text = '\n'.join(f'{k}: {v}' for k, v in info.items())
        QApplication.clipboard().setText(text)

    def _export_csv(self):
        if not self._current_feature:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, 'CSV出力先', '', 'CSV Files (*.csv)',
        )
        if not path:
            return
        info = self.searcher.feature_to_dict(self._current_feature)
        with open(path, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=info.keys())
            writer.writeheader()
            writer.writerow(info)
        QMessageBox.information(self, '完了', f'{path} に出力しました。')

    def cleanup(self):
        self._clear_highlight()
        self._clear_search_area_boundary()
        self._clear_detect_marker()
        if self._auto_load_thread and self._auto_load_thread.isRunning():
            self._auto_load_thread.terminate()
            self._auto_load_thread.wait()
        if self._map_tool:
            canvas = self.iface.mapCanvas()
            try:
                canvas.mapToolSet.disconnect(self._on_map_tool_changed)
            except TypeError:
                pass
            if self._prev_map_tool:
                canvas.setMapTool(self._prev_map_tool)
