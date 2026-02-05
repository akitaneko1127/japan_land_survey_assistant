# -*- coding: utf-8 -*-
"""Processing algorithm: Load Kokudo Suuchi Info."""

from qgis.core import (
    QgsProcessingAlgorithm, QgsProcessingParameterEnum,
    QgsProcessingParameterString, QgsProcessingOutputMultipleLayers,
    QgsProcessingContext, QgsProcessingFeedback, QgsProject,
)

from ...core.kokudo_api_client import KOKUDO_DATASETS


class LoadKokudoAlgorithm(QgsProcessingAlgorithm):

    DATASET = 'DATASET'
    PREFECTURE = 'PREFECTURE'
    FISCAL_YEAR = 'FISCAL_YEAR'
    OUTPUT = 'OUTPUT'

    def name(self):
        return 'loadkokudo'

    def displayName(self):
        return '国土数値情報ダウンロード'

    def group(self):
        return 'データ読込'

    def groupId(self):
        return 'dataload'

    def shortHelpString(self):
        return '国土数値情報APIからデータをダウンロードし、レイヤとして追加します。'

    def createInstance(self):
        return LoadKokudoAlgorithm()

    def initAlgorithm(self, config=None):
        ds_names = [f"{v['name']} ({k})" for k, v in KOKUDO_DATASETS.items()]
        self.addParameter(QgsProcessingParameterEnum(
            self.DATASET, 'データセット',
            options=ds_names,
            defaultValue=0,
        ))
        self.addParameter(QgsProcessingParameterString(
            self.PREFECTURE, '都道府県コード (カンマ区切り)',
            defaultValue='13',
        ))
        self.addParameter(QgsProcessingParameterString(
            self.FISCAL_YEAR, '年度 (空欄で最新)',
            defaultValue='', optional=True,
        ))
        self.addOutput(QgsProcessingOutputMultipleLayers(
            self.OUTPUT, '出力レイヤ',
        ))

    def processAlgorithm(self, parameters, context: QgsProcessingContext,
                         feedback: QgsProcessingFeedback):
        ds_idx = self.parameterAsEnum(parameters, self.DATASET, context)
        ds_codes = list(KOKUDO_DATASETS.keys())
        dataset_id = ds_codes[ds_idx] if ds_idx < len(ds_codes) else 'N03'

        pref_str = self.parameterAsString(parameters, self.PREFECTURE, context)
        pref_codes = [p.strip() for p in pref_str.split(',') if p.strip()]

        fiscal_year = self.parameterAsString(parameters, self.FISCAL_YEAR, context)

        from ...services.data_loader_service import DataLoaderService
        service = DataLoaderService()

        feedback.pushInfo(f'Downloading {dataset_id} for {pref_codes}')

        def progress_cb(current, total):
            if total > 0:
                feedback.setProgress(int(current / total * 100))

        layers = service.load_kokudo_data(
            dataset_id, pref_codes, fiscal_year,
            progress_callback=progress_cb,
        )

        layer_ids = []
        for layer in (layers or []):
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                layer_ids.append(layer.id())
                feedback.pushInfo(f'Added layer: {layer.name()}')

        return {self.OUTPUT: layer_ids}
