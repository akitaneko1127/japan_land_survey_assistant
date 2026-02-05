# -*- coding: utf-8 -*-
"""
Japan Land Survey Assistant - Main plugin class.
"""

import os

from qgis.PyQt.QtCore import Qt, QSettings, QTranslator, QCoreApplication
from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsApplication


class JapanLandSurveyAssistant:
    """Main plugin class for Japan Land Survey Assistant."""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = '&Japan Land Survey Assistant'
        self.toolbar = self.iface.addToolBar('Japan Land Survey Assistant')
        self.toolbar.setObjectName('JapanLandSurveyAssistant')
        self.toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.main_dialog = None
        self.provider = None

        locale_setting = QSettings().value('locale/userLocale')
        if locale_setting:
            locale = locale_setting[0:2]
        else:
            locale = 'en'
        locale_path = os.path.join(self.plugin_dir, 'i18n', f'{locale}.qm')
        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            QCoreApplication.installTranslator(self.translator)

    def tr(self, message):
        return QCoreApplication.translate('JapanLandSurveyAssistant', message)

    def initGui(self):
        self.action_main = QAction(
            self.tr('地籍調査支援'),
            self.iface.mainWindow()
        )
        self.action_main.triggered.connect(self.run)
        self.action_main.setStatusTip(self.tr('日本地籍調査支援ツールを開く'))
        self.toolbar.addAction(self.action_main)
        self.iface.addPluginToMenu(self.menu, self.action_main)
        self.actions.append(self.action_main)

        # Register processing provider
        from .processing.provider import JLSAProvider
        self.provider = JLSAProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def unload(self):
        for action in self.actions:
            self.iface.removePluginMenu(self.menu, action)
            self.iface.removeToolBarIcon(action)

        del self.toolbar

        if self.main_dialog:
            self.main_dialog.cleanup()
            self.main_dialog.close()
            self.main_dialog = None

        if self.provider:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None

    def run(self):
        from .ui.main_dialog import MainDialog
        if self.main_dialog is None:
            self.main_dialog = MainDialog(self.iface, self.iface.mainWindow())
        self.main_dialog.show()
        self.main_dialog.raise_()
        self.main_dialog.activateWindow()
