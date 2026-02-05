# -*- coding: utf-8 -*-
"""Cache manager for downloaded data."""

import os
import json
import shutil
from typing import Optional, Dict


class CacheManager:
    """Manages a local file cache for downloaded datasets."""

    CACHE_DIR_NAME = 'jlsa_cache'
    CACHE_INDEX_FILE = 'cache_index.json'

    def __init__(self, base_dir: Optional[str] = None):
        if base_dir:
            self.base_dir = base_dir
        else:
            try:
                from qgis.core import QgsApplication
                qgis_dir = QgsApplication.qgisSettingsDirPath()
                self.base_dir = os.path.join(qgis_dir, 'cache', self.CACHE_DIR_NAME)
            except Exception:
                from pathlib import Path
                self.base_dir = os.path.join(str(Path.home()), '.cache', self.CACHE_DIR_NAME)

        self._index: Dict = {}
        self._load_index()

    def _load_index(self):
        path = os.path.join(self.base_dir, self.CACHE_INDEX_FILE)
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    self._index = json.load(f)
            except Exception:
                self._index = {}

    def _save_index(self):
        os.makedirs(self.base_dir, exist_ok=True)
        path = os.path.join(self.base_dir, self.CACHE_INDEX_FILE)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self._index, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    @staticmethod
    def make_key(*args) -> str:
        return '_'.join(str(a) for a in args)

    def get_cached_file(self, key: str) -> Optional[str]:
        entry = self._index.get(key)
        if entry:
            path = entry.get('path')
            if path and os.path.exists(path):
                return path
        return None

    def register(self, key: str, file_path: str, **metadata):
        self._index[key] = {**metadata, 'path': file_path}
        self._save_index()

    def clear_all(self):
        try:
            if os.path.exists(self.base_dir):
                shutil.rmtree(self.base_dir)
        except Exception:
            pass
        self._index = {}

    def get_cache_size_bytes(self) -> int:
        total = 0
        for entry in self._index.values():
            path = entry.get('path')
            if path and os.path.exists(path):
                total += os.path.getsize(path)
        return total

    def get_download_dir(self) -> str:
        d = os.path.join(self.base_dir, 'downloads')
        os.makedirs(d, exist_ok=True)
        return d
