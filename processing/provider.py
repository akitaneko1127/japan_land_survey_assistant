# -*- coding: utf-8 -*-
"""Processing provider for Japan Land Survey Assistant."""

from qgis.core import QgsProcessingProvider

from .algorithms.load_moj_xml import LoadMojXmlAlgorithm
from .algorithms.load_kokudo import LoadKokudoAlgorithm
from .algorithms.visualize_progress import VisualizeProgressAlgorithm
from .algorithms.search_parcel import SearchParcelAlgorithm


class JLSAProvider(QgsProcessingProvider):
    """Processing provider for JLSA algorithms."""

    def id(self):
        return 'jlsa'

    def name(self):
        return 'Japan Land Survey Assistant'

    def longName(self):
        return 'Japan Land Survey Assistant (日本地籍調査支援ツール)'

    def icon(self):
        return QgsProcessingProvider.icon(self)

    def loadAlgorithms(self):
        self.addAlgorithm(LoadMojXmlAlgorithm())
        self.addAlgorithm(LoadKokudoAlgorithm())
        self.addAlgorithm(VisualizeProgressAlgorithm())
        self.addAlgorithm(SearchParcelAlgorithm())
