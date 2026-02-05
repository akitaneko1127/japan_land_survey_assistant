# -*- coding: utf-8 -*-
"""Settings management via QSettings."""

import base64
from qgis.PyQt.QtCore import QSettings


class Config:
    """Manages plugin settings via QSettings."""

    PREFIX = 'japan_land_survey_assistant'

    DEFAULTS = {
        'reinfolib_api_key': '',
        'cache_enabled': True,
        'auto_style': True,
        'timeout': 60,
        'include_arbitrary_crs': False,
        'include_outside_area': False,
        'preferred_moj_year': '',  # 空文字=最新自動選択
    }

    def __init__(self):
        self.settings = QSettings()

    def _key(self, name: str) -> str:
        return f'{self.PREFIX}/{name}'

    # --- API Key (base64 encoded) ---

    def get_api_key(self) -> str:
        encoded = self.settings.value(self._key('reinfolib_api_key'), '')
        if not encoded:
            return ''
        try:
            return base64.b64decode(encoded.encode()).decode()
        except Exception:
            return ''

    def set_api_key(self, api_key: str) -> None:
        if api_key:
            encoded = base64.b64encode(api_key.encode()).decode()
            self.settings.setValue(self._key('reinfolib_api_key'), encoded)
        else:
            self.settings.remove(self._key('reinfolib_api_key'))

    def has_api_key(self) -> bool:
        return bool(self.get_api_key())

    # --- Generic accessors ---

    def get_value(self, name: str, default=None):
        if default is None:
            default = self.DEFAULTS.get(name)
        return self.settings.value(self._key(name), default)

    def set_value(self, name: str, value) -> None:
        self.settings.setValue(self._key(name), value)

    def get_bool(self, name: str, default=None) -> bool:
        val = self.get_value(name, default)
        return val in (True, 'true', '1', 1)

    def get_int(self, name: str, default=None) -> int:
        return int(self.get_value(name, default or 0))

    # --- Convenience ---

    def is_cache_enabled(self) -> bool:
        return self.get_bool('cache_enabled', True)

    def is_auto_style(self) -> bool:
        return self.get_bool('auto_style', True)

    def get_timeout(self) -> int:
        return self.get_int('timeout', 60)

    def include_arbitrary_crs(self) -> bool:
        return self.get_bool('include_arbitrary_crs', False)

    def include_outside_area(self) -> bool:
        return self.get_bool('include_outside_area', False)

    def get_preferred_moj_year(self) -> str:
        return str(self.get_value('preferred_moj_year', '') or '')
