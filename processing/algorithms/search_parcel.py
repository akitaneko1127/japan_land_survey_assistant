# -*- coding: utf-8 -*-
"""Processing algorithm: Search Parcel."""

from qgis.core import (
    QgsProcessingAlgorithm, QgsProcessingParameterVectorLayer,
    QgsProcessingParameterString, QgsProcessingOutputVectorLayer,
    QgsProcessingContext, QgsProcessingFeedback, QgsProject,
    QgsProcessing, QgsVectorLayer, QgsFeature,
)


class SearchParcelAlgorithm(QgsProcessingAlgorithm):

    INPUT = 'INPUT'
    PARCEL_NUMBER = 'PARCEL_NUMBER'
    OAZA = 'OAZA'
    AZA = 'AZA'
    OUTPUT = 'OUTPUT'

    def name(self):
        return 'searchparcel'

    def displayName(self):
        return '地番検索'

    def group(self):
        return '検索'

    def groupId(self):
        return 'search'

    def shortHelpString(self):
        return '筆レイヤから指定した地番の筆を検索し、結果をレイヤとして出力します。'

    def createInstance(self):
        return SearchParcelAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT, '対象レイヤ',
            [QgsProcessing.TypeVectorPolygon],
        ))
        self.addParameter(QgsProcessingParameterString(
            self.PARCEL_NUMBER, '地番',
        ))
        self.addParameter(QgsProcessingParameterString(
            self.OAZA, '大字名', defaultValue='', optional=True,
        ))
        self.addParameter(QgsProcessingParameterString(
            self.AZA, '字名', defaultValue='', optional=True,
        ))
        self.addOutput(QgsProcessingOutputVectorLayer(
            self.OUTPUT, '検索結果',
        ))

    def processAlgorithm(self, parameters, context: QgsProcessingContext,
                         feedback: QgsProcessingFeedback):
        layer = self.parameterAsVectorLayer(parameters, self.INPUT, context)
        parcel_num = self.parameterAsString(parameters, self.PARCEL_NUMBER, context)
        oaza = self.parameterAsString(parameters, self.OAZA, context)
        aza = self.parameterAsString(parameters, self.AZA, context)

        from ...core.parcel_searcher import ParcelSearcher
        searcher = ParcelSearcher()

        features = searcher.search_by_parcel_number(layer, parcel_num, oaza, aza)
        if not features:
            features = searcher.search_like(layer, parcel_num)

        feedback.pushInfo(f'Found {len(features)} matching features')

        if not features:
            feedback.reportError('No matching parcels found')
            return {}

        # Create output layer
        crs = layer.crs().authid()
        out = QgsVectorLayer(f'Polygon?crs={crs}', f'検索結果_{parcel_num}', 'memory')
        prov = out.dataProvider()
        prov.addAttributes(layer.fields().toList())
        out.updateFields()

        out_feats = []
        for f in features:
            nf = QgsFeature(out.fields())
            nf.setGeometry(f.geometry())
            for i in range(layer.fields().count()):
                nf.setAttribute(i, f.attribute(i))
            out_feats.append(nf)

        prov.addFeatures(out_feats)
        out.updateExtents()
        QgsProject.instance().addMapLayer(out)

        return {self.OUTPUT: out.id()}
