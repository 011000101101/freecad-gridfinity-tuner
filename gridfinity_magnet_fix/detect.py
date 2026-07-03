"""FreeCAD-specific footprint detection."""

from __future__ import annotations

from dataclasses import dataclass
import math

from .geometry import BBox2D, FootprintMatch, axis_aligned_ratio, bbox_from_points, classify_bbox, points_within_bbox
from .settings import DetectionSettings

try:
    import FreeCAD as App
    import Part
except ImportError:  # pragma: no cover - only available inside FreeCAD
    App = None
    Part = None


class DetectionError(RuntimeError):
    """Raised when a solid cannot be processed."""


@dataclass(slots=True)
class DetectedFootprint:
    face_index: int
    plane_z: float
    bbox: BBox2D
    match: FootprintMatch
    outer_wire: object
    axis_ratio: float


def require_freecad():
    if App is None or Part is None:  # pragma: no cover - only available inside FreeCAD
        raise DetectionError("FreeCAD Part API is not available in this environment.")


def detect_footprints(shape, settings: DetectionSettings) -> list[DetectedFootprint]:
    require_freecad()
    if shape is None or shape.isNull():
        raise DetectionError("Selected object does not contain a valid shape.")
    if not getattr(shape, "Solids", None):
        raise DetectionError(
            "Gridfinity Magnet Fix only supports solids. If this came from a mesh, run Refine shape first."
        )

    target_z = shape.BoundBox.ZMin
    detections: list[DetectedFootprint] = []
    for face_index, face in enumerate(shape.Faces, start=1):
        if not _is_bottom_plane(face, target_z, settings.z_tolerance):
            continue
        outer_wire = face.OuterWire
        projected_points = _project_wire_points_2d(outer_wire)
        if len(projected_points) < 4:
            continue
        bbox = bbox_from_points(projected_points)
        match = classify_bbox(bbox.width, bbox.height, settings.size_tolerance)
        if match is None:
            continue
        axis_ratio = axis_aligned_ratio(projected_points, settings.axis_angle_tolerance_deg)
        if axis_ratio < settings.axis_length_ratio_min:
            continue
        if not points_within_bbox(projected_points, bbox, settings.size_tolerance):
            continue
        detections.append(
            DetectedFootprint(
                face_index=face_index,
                plane_z=target_z,
                bbox=bbox,
                match=match,
                outer_wire=outer_wire,
                axis_ratio=axis_ratio,
            )
        )

    if not detections:
        raise DetectionError(
            "No qualifying bottom landing found on the solid's lowest Z plane. "
            "If this came from an STL or mesh conversion, run Refine shape first."
        )

    families = {det.match.family for det in detections}
    if len(families) > 1 and not settings.allow_mixed_profiles:
        raise DetectionError(
            "Mixed landing profiles detected. Enable 'Allow mixed landing profiles' to continue."
        )
    return detections


def _is_bottom_plane(face, target_z: float, z_tolerance: float) -> bool:
    surface = getattr(face, "Surface", None)
    if surface is None or not hasattr(surface, "Axis"):
        return False
    normal = surface.Axis
    if abs(abs(normal.z) - 1.0) > 1e-6:
        return False
    points = _sample_wire_points(face.OuterWire)
    if not points:
        return False
    return all(abs(point.z - target_z) <= z_tolerance for point in points)


def _sample_wire_points(wire) -> list:
    sampled = []
    for edge in wire.Edges:
        points = _sample_edge_points(edge)
        if sampled and points:
            points = points[1:]
        sampled.extend(points)
    if sampled and not _points_match(sampled[0], sampled[-1]):
        sampled.append(sampled[0])
    return sampled


def _project_wire_points_2d(wire) -> list[tuple[float, float]]:
    return [(point.x, point.y) for point in _sample_wire_points(wire)]


def _sample_edge_points(edge) -> list:
    count = max(3, int(math.ceil(edge.Length / 1.0)) + 1)
    points = list(edge.discretize(Number=count))
    if len(points) >= 2 and _points_match(points[0], points[-1]):
        return points[:-1]
    return points


def _points_match(point_a, point_b, tolerance: float = 1e-7) -> bool:
    return point_a.distanceToPoint(point_b) <= tolerance
