# -*- coding: utf-8 -*-
"""Processing algorithm: Visualize Cadastral Survey Progress."""

from qgis.core import (
    QgsProcessingAlgorithm, QgsProcessingParameterVectorLayer,
    QgsProcessingParameterFile, QgsProcessingParameterEnum,
    QgsProcessingParameterString, QgsProcessingOutputVectorLayer,
    QgsProcessingContext, QgsProcessingFeedback, QgsProject,
    QgsProcessing,
)


class VisualizeProgressAlgorithm(QgsProcessingAlgorithm):

    ADMIN_LAYER = 'ADMIN_LAYER'
    CSV_FILE = 'CSV_FILE'
    DISPLAY_MODE = 'DISPLAY_MODE'
    PREF_FILTER = 'PREF_FILTER'
    OUTPUT = 'OUTPUT'

    def name(self):
        return 'visualizeprogress'

    def displayName(self):
        return '地籍調査進捗マップ'

    def group(self):
        return '可視化'

    def groupId(self):
        return 'visualization'

    def shortHelpString(self):
        return '行政区域レイヤと地籍調査進捗CSVを結合し、進捗マップを作成します。'

    def createInstance(self):
        return VisualizeProgressAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.ADMIN_LAYER, '行政区域レイヤ',
            [QgsProcessing.TypeVectorPolygon],
        ))
        self.addParameter(QgsProcessingParameterFile(
            self.CSV_FILE, '進捗データCSV (空欄で内蔵データ使用)',
            optional=True, extension='csv',
        ))
        self.addParameter(QgsProcessingParameterEnum(
            self.DISPLAY_MODE, '表示モード',
            options=['進捗率', '実施状況'],
            defaultValue=0,
        ))
        self.addParameter(QgsProcessingParameterString(
            self.PREF_FILTER, '都道府県コードフィルタ (空欄で全国)',
            defaultValue='', optional=True,
        ))
        self.addOutput(QgsProcessingOutputVectorLayer(
            self.OUTPUT, '出力レイヤ',
        ))

    def processAlgorithm(self, parameters, context: QgsProcessingContext,
                         feedback: QgsProcessingFeedback):
        admin_layer = self.parameterAsVectorLayer(parameters, self.ADMIN_LAYER, context)
        csv_file = self.parameterAsFile(parameters, self.CSV_FILE, context)
        mode = self.parameterAsEnum(parameters, self.DISPLAY_MODE, context)
        pref_filter = self.parameterAsString(parameters, self.PREF_FILTER, context)

        from ...core.chiseki_progress import ChisekiProgressManager
        manager = ChisekiProgressManager()

        csv_path = csv_file if csv_file else None
        records = manager.load_csv(csv_path)
        if pref_filter:
            records = manager.filter_records(records, pref_code=pref_filter)

        feedback.pushInfo(f'Loaded {len(records)} progress records')

        result_layer = manager.join_to_admin_layer(admin_layer, records)
        if not result_layer or not result_layer.isValid():
            feedback.reportError('Failed to create progress layer')
            return {}

        if mode == 0:
            manager.apply_progress_style(result_layer)
        else:
            manager.apply_status_style(result_layer)

        QgsProject.instance().addMapLayer(result_layer)
        feedback.pushInfo(f'Created progress layer with {result_layer.featureCount()} features')
        return {self.OUTPUT: result_layer.id()}
