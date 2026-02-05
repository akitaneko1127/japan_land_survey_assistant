# -*- coding: utf-8 -*-
"""Built-in MOJ XML parser — fallback when MOJXML Loader plugin is unavailable."""

import os
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional, Tuple

from qgis.core import QgsMessageLog, Qgis


class MojXmlParser:
    """Parse MOJ XML files and extract parcel geometry + attributes."""

    # JGD2011 plane-rectangular coordinate system EPSG codes (系1-19)
    JGD2011_EPSG = {str(i): 6668 + i for i in range(1, 20)}  # 6669-6687
    # JGD2000 (older data)
    JGD2000_EPSG = {str(i): 2442 + i for i in range(1, 20)}  # 2443-2461

    # Common namespace prefixes in MOJ XML
    NS = {
        'zmn': 'urn:jps:chizu:moj:2005',
        'gml': 'http://www.opengis.net/gml',
    }

    @staticmethod
    def _log(msg, level=Qgis.Info):
        QgsMessageLog.logMessage(msg, 'JLSA-MojParser', level)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, file_path: str,
              include_arbitrary: bool = False,
              include_outside: bool = False) -> Tuple[List[Dict], Optional[int]]:
        """Parse MOJ XML or ZIP and return (features, epsg_code).

        Each feature dict has keys:
            geometry_wkt, 地番, 大字コード, 大字名, 字コード, 字名,
            地目, 地積, 座標系, 精度区分
        """
        xml_paths = self._resolve_files(file_path)
        if not xml_paths:
            raise ValueError(f'No XML files found in {file_path}')

        all_features = []
        epsg = None

        for xp in xml_paths:
            features, file_epsg = self._parse_single(
                xp, include_arbitrary, include_outside
            )
            all_features.extend(features)
            if file_epsg and epsg is None:
                epsg = file_epsg

        self._log(f'Parsed {len(all_features)} features from {len(xml_paths)} file(s)')
        return all_features, epsg

    # ------------------------------------------------------------------
    # File handling
    # ------------------------------------------------------------------

    def _resolve_files(self, path: str) -> List[str]:
        """Return list of XML file paths (extracting ZIP if needed)."""
        if path.lower().endswith('.zip'):
            return self._extract_zip(path)
        elif path.lower().endswith('.xml'):
            return [path]
        elif os.path.isdir(path):
            return [
                os.path.join(path, f)
                for f in os.listdir(path)
                if f.lower().endswith('.xml')
            ]
        return []

    @staticmethod
    def _extract_zip(zip_path: str) -> List[str]:
        extract_dir = zip_path + '_extracted'
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(extract_dir)
        return [
            os.path.join(extract_dir, f)
            for f in os.listdir(extract_dir)
            if f.lower().endswith('.xml')
        ]

    # ------------------------------------------------------------------
    # XML Parsing
    # ------------------------------------------------------------------

    def _parse_single(self, xml_path: str,
                      include_arbitrary: bool,
                      include_outside: bool) -> Tuple[List[Dict], Optional[int]]:
        try:
            tree = ET.parse(xml_path)
        except ET.ParseError as e:
            self._log(f'XML parse error in {xml_path}: {e}', Qgis.Warning)
            return [], None

        root = tree.getroot()
        ns = self._detect_namespace(root)

        # Detect coordinate system
        coord_sys = self._detect_coordinate_system(root, ns)
        epsg = self._coord_sys_to_epsg(coord_sys)
        is_arbitrary = epsg is None

        if is_arbitrary and not include_arbitrary:
            self._log(f'Skipping arbitrary CRS file: {xml_path}')
            return [], None

        # Extract parcel features
        features = []
        for fude_elem in self._find_fude_elements(root, ns):
            feat = self._parse_fude(fude_elem, ns, coord_sys)
            if feat and feat.get('geometry_wkt'):
                if not include_outside and feat.get('_is_outside'):
                    continue
                features.append(feat)

        return features, epsg

    def _detect_namespace(self, root) -> dict:
        """Auto-detect XML namespaces."""
        tag = root.tag
        ns = dict(self.NS)
        # Extract default namespace from root tag
        m = re.match(r'\{(.+?)\}', tag)
        if m:
            ns['zmn'] = m.group(1)
        return ns

    def _detect_coordinate_system(self, root, ns: dict) -> str:
        """Detect the coordinate system identifier from the XML."""
        # Try common location patterns
        for path in [
            './/zmn:座標系',
            './/{%s}座標系' % ns.get('zmn', ''),
            './/座標系',
        ]:
            try:
                elem = root.find(path, ns)
                if elem is not None and elem.text:
                    return elem.text.strip()
            except Exception:
                continue

        # Try attribute-based detection
        for elem in root.iter():
            if '座標系' in (elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag):
                if elem.text:
                    return elem.text.strip()
        return ''

    def _coord_sys_to_epsg(self, coord_sys: str) -> Optional[int]:
        """Convert MOJ coordinate system string to EPSG code."""
        if not coord_sys:
            return None
        # Extract zone number (e.g., "公共座標9系" -> "9")
        m = re.search(r'(\d+)', coord_sys)
        if not m:
            return None
        zone = m.group(1)
        # Prefer JGD2011
        if zone in self.JGD2011_EPSG:
            return self.JGD2011_EPSG[zone]
        if zone in self.JGD2000_EPSG:
            return self.JGD2000_EPSG[zone]
        return None

    def _find_fude_elements(self, root, ns: dict):
        """Find all parcel (筆) elements in the XML tree."""
        # Try namespace-aware search first
        for path in [
            './/zmn:筆',
            './/{%s}筆' % ns.get('zmn', ''),
        ]:
            try:
                elems = root.findall(path, ns)
                if elems:
                    return elems
            except Exception:
                continue

        # Fallback: iterate and match tag suffix
        results = []
        for elem in root.iter():
            tag_local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if tag_local == '筆':
                results.append(elem)
        return results

    def _parse_fude(self, elem, ns: dict, coord_sys: str) -> Optional[Dict]:
        """Parse a single 筆 element into a feature dict."""
        feat = {
            '地番': self._get_child_text(elem, '地番', ns),
            '大字コード': self._get_child_text(elem, '大字コード', ns),
            '大字名': self._get_child_text(elem, '大字名', ns),
            '字コード': self._get_child_text(elem, '字コード', ns),
            '字名': self._get_child_text(elem, '字名', ns),
            '地目': self._get_child_text(elem, '地目', ns),
            '地積': self._try_float(self._get_child_text(elem, '地積', ns)),
            '座標系': coord_sys,
            '精度区分': self._get_child_text(elem, '精度区分', ns),
            '_is_outside': False,
        }

        # Build polygon geometry from coordinate list
        coords = self._extract_coordinates(elem, ns)
        if coords:
            wkt = self._coords_to_polygon_wkt(coords)
            feat['geometry_wkt'] = wkt
        else:
            feat['geometry_wkt'] = None

        return feat

    def _extract_coordinates(self, fude_elem, ns: dict) -> List[Tuple[float, float]]:
        """Extract coordinate pairs from geometry sub-elements."""
        coords = []
        # Look for gml:coordinates or posList patterns
        for elem in fude_elem.iter():
            tag_local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if tag_local in ('coordinates', 'posList', '座標'):
                if elem.text:
                    coords.extend(self._parse_coord_text(elem.text, tag_local))
            elif tag_local in ('X', 'x', 'Y', 'y'):
                pass  # handled at parent level

        if not coords:
            coords = self._extract_xy_pairs(fude_elem, ns)

        return coords

    @staticmethod
    def _parse_coord_text(text: str, tag_hint: str) -> List[Tuple[float, float]]:
        """Parse coordinate text into (x, y) pairs."""
        coords = []
        text = text.strip()
        if not text:
            return coords

        if tag_hint == 'posList':
            # Space-separated: y1 x1 y2 x2 ...
            nums = text.split()
            for i in range(0, len(nums) - 1, 2):
                try:
                    y, x = float(nums[i]), float(nums[i + 1])
                    coords.append((x, y))
                except (ValueError, IndexError):
                    continue
        else:
            # Comma-separated pairs: x1,y1 x2,y2 ...
            for pair in text.split():
                parts = pair.split(',')
                if len(parts) >= 2:
                    try:
                        coords.append((float(parts[0]), float(parts[1])))
                    except ValueError:
                        continue
        return coords

    def _extract_xy_pairs(self, parent, ns: dict) -> List[Tuple[float, float]]:
        """Extract X/Y child element pairs (MOJ-specific layout)."""
        coords = []
        points = []
        for elem in parent.iter():
            tag_local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if tag_local == '測点':
                points.append(elem)

        for pt in points:
            x_val = y_val = None
            for child in pt.iter():
                tag_local = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                if tag_local in ('X', 'x') and child.text:
                    x_val = self._try_float(child.text)
                elif tag_local in ('Y', 'y') and child.text:
                    y_val = self._try_float(child.text)
            if x_val is not None and y_val is not None:
                coords.append((y_val, x_val))  # MOJ: X=northing, Y=easting
        return coords

    @staticmethod
    def _coords_to_polygon_wkt(coords: List[Tuple[float, float]]) -> Optional[str]:
        if len(coords) < 3:
            return None
        # Close the ring if needed
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        coord_str = ', '.join(f'{x} {y}' for x, y in coords)
        return f'POLYGON(({coord_str}))'

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _get_child_text(self, elem, tag_name: str, ns: dict) -> str:
        """Get text content of a child element by local name."""
        for child in elem.iter():
            tag_local = child.tag.split('}')[-1] if '}' in child.tag else child.tag
            if tag_local == tag_name:
                return (child.text or '').strip()
        return ''

    @staticmethod
    def _try_float(val) -> Optional[float]:
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None
