"""Shared rim detection and optional body/rim splitting."""

from __future__ import annotations

from dataclasses import dataclass

from .geometry import nominal_cell_bbox
from .settings import BASE_PROFILE_TOP_RADIUS, RIM_INNER_PAD, RIM_TARGET_HEIGHT, Settings

try:
    import FreeCAD as App
    import Part
    import TechDraw
except ImportError:  # pragma: no cover
    App = None
    Part = None
    TechDraw = None


SEGMENT_RIM = "rim"
SEGMENT_RIM_LABEL = "Detected Rim"
SCAN_STEP = 0.2
AREA_EPSILON = 1e-4
SHAPE_EPSILON = 1e-6
RIM_HEIGHT_SCAN_ALLOWANCE = SCAN_STEP * 4.0


@dataclass(slots=True)
class SegmentComponent:
    key: str
    label: str
    shape: object


@dataclass(slots=True)
class RimDetectionResult:
    has_rim: bool
    inner_top_z: float | None
    possible_rim_min_z: float | None
    possible_rim_height: float = 0.0
    rim_z_min: float | None = None
    rim_z_max: float | None = None


@dataclass(slots=True)
class BodySplitResult:
    body_shape: object
    components: tuple[SegmentComponent, ...]
    rim_detection: RimDetectionResult


def split_body_and_optional_rim(body_shape, detections, settings: Settings, enabled: bool) -> BodySplitResult:
    if App is None or Part is None:  # pragma: no cover
        return BodySplitResult(
            body_shape=body_shape,
            components=(),
            rim_detection=RimDetectionResult(False, None, None),
        )
    if body_shape is None or body_shape.isNull():
        return BodySplitResult(
            body_shape=body_shape,
            components=(),
            rim_detection=RimDetectionResult(False, None, None),
        )
    if not enabled:
        return BodySplitResult(
            body_shape=body_shape.copy(),
            components=(),
            rim_detection=RimDetectionResult(False, None, None),
        )

    detection = detect_rim_band(body_shape, detections, settings)
    if not detection.has_rim or detection.rim_z_min is None or detection.rim_z_max is None:
        return BodySplitResult(
            body_shape=body_shape.copy(),
            components=(),
            rim_detection=detection,
        )

    rim_shape = _shape_common_safe(
        body_shape,
        _make_z_band_box(body_shape.BoundBox, detection.rim_z_min, detection.rim_z_max + SCAN_STEP),
    )
    if _shape_is_empty(rim_shape):
        return BodySplitResult(
            body_shape=body_shape.copy(),
            components=(),
            rim_detection=RimDetectionResult(False, detection.inner_top_z, detection.possible_rim_min_z),
        )

    body_without_rim = _shape_cut_safe(body_shape, rim_shape)
    body_without_rim = _refine_optional_shape(body_without_rim)
    rim_shape = _refine_optional_shape(rim_shape)
    return BodySplitResult(
        body_shape=body_without_rim,
        components=(SegmentComponent(SEGMENT_RIM, SEGMENT_RIM_LABEL, rim_shape),),
        rim_detection=detection,
    )


def detect_rim_band(body_shape, detections, settings: Settings) -> RimDetectionResult:
    if App is None or Part is None:  # pragma: no cover
        return RimDetectionResult(False, None, None)
    if body_shape is None or body_shape.isNull():
        return RimDetectionResult(False, None, None)

    z_min = float(body_shape.BoundBox.ZMin)
    z_max = float(body_shape.BoundBox.ZMax)
    height = z_max - z_min
    if height <= SHAPE_EPSILON:
        return RimDetectionResult(False, None, None)

    inset = RIM_INNER_PAD + settings.operation.rim_tolerance
    inner_projection = _build_body_inner_projection_volume(body_shape, inset)
    if _shape_is_empty(inner_projection):
        grouped = _group_detections_by_plane(detections)
        if len(grouped) != 1:
            return RimDetectionResult(False, None, None)
        _, plane_detections = next(iter(grouped.items()))
        footprint_bboxes = tuple(
            nominal_cell_bbox(detection.bbox, detection.match.kind)
            for detection in plane_detections
        )
        radius = max(0.0, BASE_PROFILE_TOP_RADIUS - inset)
        inner_projection = _build_projection_volume(footprint_bboxes, z_min, height, inset, radius)
    inner_body = _shape_common_safe(body_shape, inner_projection)
    if _shape_is_empty(inner_body):
        return RimDetectionResult(False, None, None)

    inner_top_z = _find_inner_top_z(inner_body, z_min, z_max)
    if inner_top_z is None:
        return RimDetectionResult(False, None, None)

    possible_rim_height = max(0.0, z_max - inner_top_z)
    minimum_rim_height = max(0.0, RIM_TARGET_HEIGHT - settings.operation.rim_tolerance - RIM_HEIGHT_SCAN_ALLOWANCE)
    if possible_rim_height < minimum_rim_height:
        return RimDetectionResult(
            has_rim=False,
            inner_top_z=inner_top_z,
            possible_rim_min_z=inner_top_z,
            possible_rim_height=possible_rim_height,
        )

    rim_z_min = inner_top_z if possible_rim_height <= RIM_TARGET_HEIGHT else z_max - RIM_TARGET_HEIGHT
    return RimDetectionResult(
        has_rim=True,
        inner_top_z=inner_top_z,
        possible_rim_min_z=inner_top_z,
        possible_rim_height=possible_rim_height,
        rim_z_min=rim_z_min,
        rim_z_max=z_max,
    )


def _find_inner_top_z(inner_body, z_min: float, z_max: float) -> float | None:
    z = z_max
    while z > z_min + SHAPE_EPSILON:
        sample_z = max(z_min, z - SCAN_STEP)
        if _shape_cross_section_area(inner_body, sample_z) > AREA_EPSILON:
            return min(z_max, sample_z + SCAN_STEP)
        z = sample_z
    return None


def _shape_cross_section_area(shape, z_value: float) -> float:
    if _shape_is_empty(shape):
        return 0.0
    area = 0.0
    for face in _horizontal_slice_faces(shape, z_value):
        try:
            area += float(face.Area)
        except Exception:
            continue
    return area


def _horizontal_slice_faces(shape, z_value: float):
    plane = Part.makePlane(
        shape.BoundBox.XLength + 20.0,
        shape.BoundBox.YLength + 20.0,
        App.Vector(shape.BoundBox.XMin - 10.0, shape.BoundBox.YMin - 10.0, z_value),
        App.Vector(0.0, 0.0, 1.0),
    )
    try:
        section = shape.section(plane)
    except Exception:
        return []
    edges = list(getattr(section, "Edges", ()) or ())
    if not edges:
        return []
    faces = []
    for edge_group in Part.sortEdges(edges):
        try:
            wire = Part.Wire(edge_group)
        except Exception:
            continue
        if not wire.isClosed():
            continue
        try:
            face = Part.makeFace([wire], "Part::FaceMakerBullseye")
        except Exception:
            try:
                face = Part.Face(wire)
            except Exception:
                continue
        faces.append(face)
    return faces


def _make_z_band_box(bound_box, z_min: float, z_max: float):
    if z_max <= z_min:
        z_max = z_min + SCAN_STEP
    return Part.makeBox(
        bound_box.XLength + 20.0,
        bound_box.YLength + 20.0,
        z_max - z_min,
        App.Vector(bound_box.XMin - 10.0, bound_box.YMin - 10.0, z_min),
    )


def _build_projection_volume(footprint_bboxes, plane_z: float, height: float, inset: float, radius: float):
    adjusted = []
    for bbox in footprint_bboxes:
        adjusted.append(
            type(bbox)(
                bbox.min_x + (_edge_inset_for_side(footprint_bboxes, bbox, "left") * inset),
                bbox.min_y + (_edge_inset_for_side(footprint_bboxes, bbox, "bottom") * inset),
                bbox.max_x - (_edge_inset_for_side(footprint_bboxes, bbox, "right") * inset),
                bbox.max_y - (_edge_inset_for_side(footprint_bboxes, bbox, "top") * inset),
            )
        )
    faces = []
    for bbox in adjusted:
        if bbox.width <= SHAPE_EPSILON or bbox.height <= SHAPE_EPSILON:
            continue
        wire = _rounded_rect_wire(bbox, max(0.0, radius)).translated(App.Vector(0.0, 0.0, plane_z))
        faces.append(Part.Face(wire))
    merged = _fuse_shapes(faces)
    solid = merged.extrude(App.Vector(0.0, 0.0, height))
    return _refine_optional_shape(solid)


def _build_body_inner_projection_volume(body_shape, inset: float):
    projection_face = _build_body_projection_face(body_shape)
    if projection_face is None:
        return None
    try:
        inner_shape = projection_face.makeOffset2D(-inset)
    except Exception:
        return None
    inner_face = _largest_face(inner_shape)
    if inner_face is None:
        return None
    z_min = float(body_shape.BoundBox.ZMin)
    z_span = float(body_shape.BoundBox.ZMax - body_shape.BoundBox.ZMin)
    if z_span <= SHAPE_EPSILON:
        return None
    translated_face = inner_face.translated(App.Vector(0.0, 0.0, z_min - inner_face.BoundBox.ZMin))
    return _refine_optional_shape(translated_face.extrude(App.Vector(0.0, 0.0, z_span)))


def _build_body_projection_face(body_shape):
    face = _build_projected_footprint_face(body_shape)
    if face is not None:
        return face
    return _build_low_slice_footprint_face(body_shape)


def _build_projected_footprint_face(body_shape):
    if TechDraw is None:
        return None
    try:
        projected = TechDraw.project(body_shape, App.Vector(0.0, 0.0, 1.0))
    except Exception:
        return None
    edges = []
    for item in projected if isinstance(projected, (list, tuple)) else (projected,):
        edges.extend(list(getattr(item, "Edges", ()) or ()))
    return _largest_face_from_edges(edges)


def _build_low_slice_footprint_face(body_shape):
    z_min = float(body_shape.BoundBox.ZMin)
    z_sample = min(float(body_shape.BoundBox.ZMax), z_min + max(SCAN_STEP, 0.05))
    faces = _horizontal_slice_faces(body_shape, z_sample)
    return _largest_face(faces)


def _largest_face_from_edges(edges):
    if not edges:
        return None
    faces = []
    for edge_group in Part.sortEdges(edges):
        try:
            wire = Part.Wire(edge_group)
        except Exception:
            continue
        if not wire.isClosed():
            continue
        try:
            face = Part.Face(wire)
        except Exception:
            try:
                face = Part.makeFace([wire], "Part::FaceMakerBullseye")
            except Exception:
                continue
        faces.append(face)
    return _largest_face(faces)


def _largest_face(shape_or_faces):
    if shape_or_faces is None:
        return None
    if hasattr(shape_or_faces, "Area") and hasattr(shape_or_faces, "OuterWire"):
        return shape_or_faces
    faces = list(getattr(shape_or_faces, "Faces", ()) or ())
    if not faces and isinstance(shape_or_faces, (list, tuple)):
        faces = [face for face in shape_or_faces if face is not None]
    if not faces:
        return None
    best_face = None
    best_area = -1.0
    for face in faces:
        try:
            area = float(face.Area)
        except Exception:
            continue
        if area > best_area:
            best_area = area
            best_face = face
    return best_face


def _rounded_rect_wire(bbox, radius: float):
    width = bbox.width
    height = bbox.height
    radius = max(0.0, min(radius, max(width / 2.0 - 1e-6, 0.0), max(height / 2.0 - 1e-6, 0.0)))
    z = 0.0
    if radius <= 1e-6:
        return Part.Wire(
            Part.makePolygon(
                (
                    App.Vector(bbox.min_x, bbox.min_y, z),
                    App.Vector(bbox.max_x, bbox.min_y, z),
                    App.Vector(bbox.max_x, bbox.max_y, z),
                    App.Vector(bbox.min_x, bbox.max_y, z),
                    App.Vector(bbox.min_x, bbox.min_y, z),
                )
            ).Edges
        )

    left = bbox.min_x
    right = bbox.max_x
    bottom = bbox.min_y
    top = bbox.max_y
    edges = [
        Part.makeLine(App.Vector(left + radius, bottom, z), App.Vector(right - radius, bottom, z)),
        Part.makeCircle(radius, App.Vector(right - radius, bottom + radius, z), App.Vector(0.0, 0.0, 1.0), 270.0, 360.0),
        Part.makeLine(App.Vector(right, bottom + radius, z), App.Vector(right, top - radius, z)),
        Part.makeCircle(radius, App.Vector(right - radius, top - radius, z), App.Vector(0.0, 0.0, 1.0), 0.0, 90.0),
        Part.makeLine(App.Vector(right - radius, top, z), App.Vector(left + radius, top, z)),
        Part.makeCircle(radius, App.Vector(left + radius, top - radius, z), App.Vector(0.0, 0.0, 1.0), 90.0, 180.0),
        Part.makeLine(App.Vector(left, top - radius, z), App.Vector(left, bottom + radius, z)),
        Part.makeCircle(radius, App.Vector(left + radius, bottom + radius, z), App.Vector(0.0, 0.0, 1.0), 180.0, 270.0),
    ]
    return Part.Wire(edges)


def _group_detections_by_plane(detections):
    grouped = {}
    for detection in detections:
        grouped.setdefault(round(detection.plane_z, 6), []).append(detection)
    return grouped


def _edge_inset_for_side(all_bboxes, target_bbox, side: str) -> int:
    for other_bbox in all_bboxes:
        if other_bbox == target_bbox:
            continue
        if side == "left" and _touches_vertically(other_bbox, target_bbox, target_bbox.min_x, target_bbox.min_y, target_bbox.max_y):
            return 0
        if side == "right" and _touches_vertically(other_bbox, target_bbox, target_bbox.max_x, target_bbox.min_y, target_bbox.max_y):
            return 0
        if side == "bottom" and _touches_horizontally(other_bbox, target_bbox, target_bbox.min_y, target_bbox.min_x, target_bbox.max_x):
            return 0
        if side == "top" and _touches_horizontally(other_bbox, target_bbox, target_bbox.max_y, target_bbox.min_x, target_bbox.max_x):
            return 0
    return 1


def _touches_vertically(other_bbox, target_bbox, x_edge: float, min_y: float, max_y: float) -> bool:
    if abs(other_bbox.max_x - x_edge) <= 1e-6 and abs(target_bbox.min_x - x_edge) <= 1e-6:
        return other_bbox.min_y <= min_y + 1e-6 and other_bbox.max_y >= max_y - 1e-6
    if abs(other_bbox.min_x - x_edge) <= 1e-6 and abs(target_bbox.max_x - x_edge) <= 1e-6:
        return other_bbox.min_y <= min_y + 1e-6 and other_bbox.max_y >= max_y - 1e-6
    return False


def _touches_horizontally(other_bbox, target_bbox, y_edge: float, min_x: float, max_x: float) -> bool:
    if abs(other_bbox.max_y - y_edge) <= 1e-6 and abs(target_bbox.min_y - y_edge) <= 1e-6:
        return other_bbox.min_x <= min_x + 1e-6 and other_bbox.max_x >= max_x - 1e-6
    if abs(other_bbox.min_y - y_edge) <= 1e-6 and abs(target_bbox.max_y - y_edge) <= 1e-6:
        return other_bbox.min_x <= min_x + 1e-6 and other_bbox.max_x >= max_x - 1e-6
    return False


def _shape_common_safe(left, right):
    if _shape_is_empty(left) or _shape_is_empty(right):
        return None
    try:
        return left.common(right)
    except Exception:
        return None


def _shape_cut_safe(left, right):
    if _shape_is_empty(left):
        return left
    if _shape_is_empty(right):
        return left.copy()
    try:
        return left.cut(right)
    except Exception:
        return left.copy()


def _fuse_shapes(shapes):
    shapes = [shape for shape in shapes if not _shape_is_empty(shape)]
    if not shapes:
        return None
    fused = shapes[0]
    for shape in shapes[1:]:
        fused = fused.fuse(shape)
    return _refine_optional_shape(fused)


def _refine_optional_shape(shape):
    if _shape_is_empty(shape):
        return shape
    try:
        refined = shape.removeSplitter()
    except Exception:
        return shape
    try:
        return shape if refined.isNull() else refined
    except Exception:
        return shape


def _shape_is_empty(shape) -> bool:
    if shape is None:
        return True
    try:
        if shape.isNull():
            return True
    except Exception:
        return True
    solids = getattr(shape, "Solids", None)
    faces = getattr(shape, "Faces", ())
    edges = getattr(shape, "Edges", ())
    if solids is not None and len(solids) == 0 and len(faces) == 0 and len(edges) == 0:
        return True
    if len(faces) > 0 or len(edges) > 0:
        return False
    try:
        if hasattr(shape, "Volume") and abs(shape.Volume) <= SHAPE_EPSILON:
            return True
    except Exception:
        pass
    return False
