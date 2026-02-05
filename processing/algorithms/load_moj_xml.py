# -*- coding: utf-8 -*-
"""Processing algorithm: Load MOJ XML."""

from qgis.core import (
    QgsProcessingAlgorithm, QgsProcessingParameterFile,
    QgsProcessingParameterBoolean, QgsProcessingOutputVectorLayer,
    QgsProcessingContext, QgsProcessingFeedback, QgsProject,
)


class LoadMojXmlAlgorithm(QgsProcessingAlgorithm):

    INPUT = 'INPUT'
    INCLUDE_ARBITRARY = 'INCLUDE_ARBITRARY'
    INCLUDE_OUTSIDE = 'INCLUDE_OUTSIDE'
    AUTO_STYLE = 'AUTO_STYLE'
    OUTPUT = 'OUTPUT'

    def name(self):
        return 'loadmojxml'

    def displayName(self):
        return 'MOJ XML読込'

    def group(self):
        return 'データ読込'

    def groupId(self):
        return 'dataload'

    def shortHelpString(self):
        return '法務省地図XMLファイルを読み込み、筆ポリゴンレイヤを作成します。'

    def createInstance(self):
        return LoadMojXmlAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(
            self.INPUT, 'MOJ XMLファイル',
            extension='xml',
        ))
        self.addParameter(QgsProcessingParameterBoolean(
            self.INCLUDE_ARBITRARY, '任意座標系データを含む', defaultValue=False,
        ))
        self.addParameter(QgsProcessingParameterBoolean(
            self.INCLUDE_OUTSIDE, '図郭外・別図を含む', defaultValue=False,
        ))
        self.addParameter(QgsProcessingParameterBoolean(
            self.AUTO_STYLE, '自動スタイル適用', defaultValue=True,
        ))
        self.addOutput(QgsProcessingOutputVectorLayer(
            self.OUTPUT, '出力レイヤ',
        ))

    def processAlgorithm(self, parameters, context: QgsProcessingContext,
                         feedback: QgsProcessingFeedback):
        file_path = self.parameterAsFile(parameters, self.INPUT, context)
        include_arb = self.parameterAsBool(parameters, self.INCLUDE_ARBITRARY, context)
        include_out = self.parameterAsBool(parameters, self.INCLUDE_OUTSIDE, context)
        auto_style = self.parameterAsBool(parameters, self.AUTO_STYLE, context)

        from ...services.data_loader_service import DataLoaderService
        service = DataLoaderService()

        feedback.pushInfo(f'Loading: {file_path}')
        layer = service.load_moj_xml(
            file_path,
            include_arbitrary=include_arb,
            include_outside=include_out,
            auto_style=auto_style,
        )

        if layer and layer.isValid():
            QgsProject.instance().addMapLayer(layer)
            feedback.pushInfo(f'Loaded {layer.featureCount()} features')
            return {self.OUTPUT: layer.id()}

        feedback.reportError('Failed to load MOJ XML')
        return {}
