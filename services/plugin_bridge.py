# -*- coding: utf-8 -*-
"""Plugin bridge for detecting and calling existing QGIS plugins."""

from qgis.core import QgsMessageLog, Qgis


class PluginBridge:
    """Detects and integrates with existing QGIS plugins."""

    SUPPORTED_PLUGINS = {
        'mojxml_plugin': {
            'name': 'MOJXML Loader',
            'provider_id': 'mojxml',
            'algorithm': 'mojxml:loadmojxml',
        },
        'jpdata': {
            'name': 'jpdata',
            'class': 'jpdata.jpdata.jpdata',
        },
        'QuickDEM4JP': {
            'name': 'QuickDEM4JP',
            'provider_id': 'quickdem4jp',
        },
    }

    def __init__(self):
        self._status_cache = {}

    @staticmethod
    def _log(message: str, level=Qgis.Info):
        QgsMessageLog.logMessage(message, 'JLSA-Bridge', level)

    def is_plugin_available(self, plugin_id: str) -> bool:
        if plugin_id in self._status_cache:
            return self._status_cache[plugin_id]
        try:
            from qgis.utils import plugins
            available = plugin_id in plugins
        except Exception:
            available = False
        self._status_cache[plugin_id] = available
        return available

    def refresh(self):
        self._status_cache.clear()

    def get_status_all(self) -> dict:
        self.refresh()
        result = {}
        for pid, info in self.SUPPORTED_PLUGINS.items():
            result[pid] = {
                'name': info['name'],
                'available': self.is_plugin_available(pid),
            }
        return result

    def is_mojxml_loader_available(self) -> bool:
        return self.is_plugin_available('mojxml_plugin')

    def is_jpdata_available(self) -> bool:
        return self.is_plugin_available('jpdata')

    def is_quickdem_available(self) -> bool:
        return self.is_plugin_available('QuickDEM4JP')

    def load_moj_xml_via_plugin(self, file_path: str,
                                include_arbitrary: bool = False,
                                include_outside: bool = False):
        """Load MOJ XML via MOJXML Loader processing algorithm."""
        if not self.is_mojxml_loader_available():
            raise RuntimeError('MOJXML Loader plugin is not available')

        import processing
        params = {
            'INPUT': file_path,
            'INCLUDE_ARBITRARY': include_arbitrary,
            'INCLUDE_OUTSIDE': include_outside,
            'OUTPUT': 'memory:',
        }
        self._log(f'Running mojxml:loadmojxml with {file_path}')
        result = processing.run('mojxml:loadmojxml', params)
        return result.get('OUTPUT')
