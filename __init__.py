# -*- coding: utf-8 -*-
"""
Japan Land Survey Assistant - 日本地籍調査支援ツール

An integrated QGIS plugin for cadastral survey operations.
"""


def classFactory(iface):
    """Load JapanLandSurveyAssistant class.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    from .plugin import JapanLandSurveyAssistant
    return JapanLandSurveyAssistant(iface)
