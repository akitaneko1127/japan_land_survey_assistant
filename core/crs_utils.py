# -*- coding: utf-8 -*-
"""CRS変換ユーティリティ."""

from qgis.core import (
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsProject, QgsPointXY, QgsRectangle, QgsVectorLayer,
)


def canvas_center_to_4326(iface) -> QgsPointXY:
    """マップキャンバスの中心座標を EPSG:4326 に変換して返す."""
    canvas = iface.mapCanvas()
    center = canvas.center()
    src_crs = canvas.mapSettings().destinationCrs()
    dst_crs = QgsCoordinateReferenceSystem('EPSG:4326')
    if src_crs != dst_crs:
        transform = QgsCoordinateTransform(
            src_crs, dst_crs, QgsProject.instance()
        )
        center = transform.transform(center)
    return center


def layer_extent_to_canvas(layer: QgsVectorLayer, iface) -> QgsRectangle:
    """レイヤの extent をキャンバス CRS に変換して返す."""
    extent = layer.extent()
    layer_crs = layer.crs()
    canvas_crs = iface.mapCanvas().mapSettings().destinationCrs()
    if layer_crs != canvas_crs:
        transform = QgsCoordinateTransform(
            layer_crs, canvas_crs, QgsProject.instance()
        )
        extent = transform.transformBoundingBox(extent)
    return extent


def rect_to_canvas(rect: QgsRectangle, src_crs, iface) -> QgsRectangle:
    """任意の QgsRectangle をキャンバス CRS に変換して返す."""
    canvas_crs = iface.mapCanvas().mapSettings().destinationCrs()
    if src_crs != canvas_crs:
        transform = QgsCoordinateTransform(
            src_crs, canvas_crs, QgsProject.instance()
        )
        rect = transform.transformBoundingBox(rect)
    return rect


def zoom_to_layer(layer: QgsVectorLayer, iface, factor: float = 1.1):
    """レイヤの範囲にズーム（CRS変換対応）."""
    layer.updateExtents()
    extent = layer_extent_to_canvas(layer, iface)
    if extent.isNull() or extent.isEmpty():
        return
    canvas = iface.mapCanvas()
    canvas.setExtent(extent)
    canvas.zoomByFactor(factor)
    canvas.refresh()


def zoom_to_feature_extent(feature, layer: QgsVectorLayer, iface,
                           factor: float = 1.2):
    """フィーチャの範囲にズーム（CRS変換対応）."""
    geom = feature.geometry()
    extent = geom.boundingBox()
    layer_crs = layer.crs()
    canvas_crs = iface.mapCanvas().mapSettings().destinationCrs()
    if layer_crs != canvas_crs:
        transform = QgsCoordinateTransform(
            layer_crs, canvas_crs, QgsProject.instance()
        )
        extent = transform.transformBoundingBox(extent)
    canvas = iface.mapCanvas()
    canvas.setExtent(extent)
    canvas.zoomByFactor(factor)
    canvas.refresh()
