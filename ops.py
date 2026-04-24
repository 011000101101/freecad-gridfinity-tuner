"""Document operations for Gridfinity Magnet Fix."""

from __future__ import annotations

from dataclasses import dataclass
import os
import sys

from .detect import detect_footprints
from .geometry import (
    child_cell_bboxes,
    effective_hole_centers,
    nominal_cell_bbox,
)
from .settings import (
    BASE_PROFILE_BOTTOM_RADIUS,
    BASE_PROFILE_HEIGHT,
    BASE_PROFILE_LOWER_SLOPE,
    BASE_PROFILE_TOP_RADIUS,
    BASE_PROFILE_UPPER_SLOPE,
    BASE_PROFILE_VERTICAL,
    BASE_PROFILE_WALL_RADIUS,
    Settings,
)

try:
    import FreeCAD as App
    import FreeCADGui as Gui
    import Part
except ImportError:  # pragma: no cover - only available inside FreeCAD
    App = None
    Gui = None
    Part = None

try:  # pragma: no cover - only available inside FreeCAD
    from BOPTools import ShapeMerge, SplitAPI
except ImportError:  # pragma: no cover
    ShapeMerge = None
    SplitAPI = None

if App is not None and (ShapeMerge is None or SplitAPI is None):  # pragma: no cover
    for candidate_path in (
        os.path.join(App.getResourceDir(), "Mod", "Part"),
        os.path.join(App.getHomePath(), "Mod", "Part"),
    ):
        if os.path.isdir(candidate_path) and candidate_path not in sys.path:
            sys.path.append(candidate_path)
    try:
        from BOPTools import ShapeMerge, SplitAPI
    except ImportError:
        ShapeMerge = None
        SplitAPI = None


class OperationError(RuntimeError):
    """Raised when model operations fail."""


@dataclass(slots=True)
class OperationResult:
    container: object
    final_object: object
    detections: list


TOP_FOOTPRINT_OUTER_INSET = 0.25


def execute(doc, source_object, settings: Settings) -> OperationResult:
    if App is None or Part is None or SplitAPI is None or ShapeMerge is None:  # pragma: no cover
        raise OperationError("FreeCAD Part API is not available in this environment.")
    if doc is None:
        raise OperationError("No active document.")
    if source_object is None or not hasattr(source_object, "Shape"):
        raise OperationError("Select a source object with a valid solid shape.")

    detections = detect_footprints(source_object.Shape, settings.detection)
    _validate_operation(detections, settings)
    container = doc.addObject("App::Part", _unique_name(doc, "GridfinityMagnetFix"))
    container.Label = settings.operation.result_label

    source_copy = doc.addObject("Part::Feature", _unique_name(doc, "GFSource"))
    source_copy.Shape = source_object.Shape.copy()
    source_copy.Label = f"{source_object.Label} Source"
    source_copy.Placement = source_object.Placement
    container.addObject(source_copy)

    fill_feature = doc.addObject("Part::Feature", _unique_name(doc, "GFFillPads"))
    fill_feature.Shape = _build_fill_pad_shape(detections)
    fill_feature.Label = "Lower Rebuild Volume"
    container.addObject(fill_feature)

    source_cut = doc.addObject("Part::Feature", _unique_name(doc, "GFSourceCut"))
    source_cut.Shape = source_object.Shape.copy().cut(fill_feature.Shape)
    source_cut.Label = "Source Without Lower Section"
    container.addObject(source_cut)

    preprocessed_feature = doc.addObject("Part::Feature", _unique_name(doc, "GFPreprocessedLower"))
    preprocessed_feature.Shape = _build_preprocessed_rebuild_volume(detections, settings)
    preprocessed_feature.Label = "Preprocessed Lower Rebuild Volume"
    container.addObject(preprocessed_feature)

    grouped_cutter_shapes = _build_grouped_channel_cutter_shapes(
        preprocessed_feature.Shape,
        detections,
        settings,
    )
    channel_cutter_shape = Part.makeCompound(grouped_cutter_shapes)

    channel_feature = doc.addObject("Part::Feature", _unique_name(doc, "GFChannelCutters"))
    channel_feature.Shape = channel_cutter_shape
    channel_feature.Label = "Profile Cutters"
    container.addObject(channel_feature)

    channel_cells_feature = None
    if settings.operation.keep_intermediates_visible:
        channel_cell_shapes = _build_channel_cell_cutter_shapes(
            preprocessed_feature.Shape,
            detections,
            settings,
        )
        channel_cells_feature = doc.addObject("Part::Feature", _unique_name(doc, "GFChannelCells"))
        channel_cells_feature.Shape = Part.makeCompound(channel_cell_shapes)
        channel_cells_feature.Label = "Channel Cutter Cells"
        container.addObject(channel_cells_feature)

    rebuild_feature = doc.addObject("Part::Feature", _unique_name(doc, "GFRebuiltLower"))
    rebuild_feature.Shape = _rebuild_lower_section(preprocessed_feature.Shape, grouped_cutter_shapes)
    rebuild_feature.Label = "Rebuilt Lower Section"
    container.addObject(rebuild_feature)

    repaired_feature = doc.addObject("Part::Feature", _unique_name(doc, "GFRepairedBase"))
    repaired_feature.Shape = _merge_optional_base_with_rebuild(source_cut.Shape, rebuild_feature.Shape)
    repaired_feature.Label = "Repaired Base"
    container.addObject(repaired_feature)

    hole_feature = doc.addObject("Part::Feature", _unique_name(doc, "GFHoleCutters"))
    hole_feature.Shape = _build_hole_cutter_shape(detections, settings)
    hole_feature.Label = "Hole Cutters"
    container.addObject(hole_feature)

    cut = doc.addObject("Part::Feature", _unique_name(doc, "GFHoleCut"))
    cut.Shape = repaired_feature.Shape.cut(hole_feature.Shape)
    cut.Label = "Magnet Pockets"
    container.addObject(cut)

    doc.recompute()

    final_object = cut
    if settings.operation.chamfer_enabled:
        edge_list = _collect_chamfer_edges(
            cut.Shape,
            detections,
            settings.operation.subdividers_enabled,
            settings.operation.hole_diameter / 2.0,
            settings.operation.hole_pitch,
            settings.operation.chamfer_size,
        )
        if edge_list:
            chamfer = doc.addObject("Part::Chamfer", _unique_name(doc, "GFChamfer"))
            chamfer.Base = cut
            chamfer.Edges = edge_list
            chamfer.Label = "Magnet Hole Chamfer"
            container.addObject(chamfer)
            final_object = chamfer
            doc.recompute()

    if not settings.operation.keep_intermediates_visible and Gui is not None:
        hidden_objects = [
            source_copy,
            fill_feature,
            source_cut,
            preprocessed_feature,
            channel_feature,
            rebuild_feature,
            repaired_feature,
            hole_feature,
            cut,
        ]
        if channel_cells_feature is not None:
            hidden_objects.append(channel_cells_feature)
        for obj in hidden_objects:
            if obj is final_object:
                continue
            obj.ViewObject.Visibility = False
        if hasattr(source_object, "ViewObject"):
            source_object.ViewObject.Visibility = False

    if hasattr(final_object, "ViewObject") and Gui is not None:
        final_object.ViewObject.Visibility = True
    return OperationResult(container=container, final_object=final_object, detections=detections)


def summarize_detections(detections) -> str:
    lines = []
    families = {detection.match.family.value for detection in detections}
    lines.append(f"Detected {len(detections)} bottom landing(s)")
    lines.append(f"Profile families: {', '.join(sorted(families))}")
    for index, detection in enumerate(detections, start=1):
        lines.append(
            (
                f"{index}. face {detection.face_index}: "
                f"{detection.match.kind.value} "
                f"{detection.bbox.width:.2f} x {detection.bbox.height:.2f} mm "
                f"at Z={detection.plane_z:.2f} "
                f"(ratio {detection.axis_ratio:.2f})"
            )
        )
    return "\n".join(lines)


def _build_fill_pad_shape(detections, height: float = BASE_PROFILE_HEIGHT):
    pads = []
    for detection in detections:
        nominal_bbox = nominal_cell_bbox(detection.bbox, detection.match.kind)
        pad_face = Part.Face(
            _rounded_rect_wire(nominal_bbox, 0.0).translated(App.Vector(0.0, 0.0, detection.plane_z))
        )
        pads.append(pad_face.extrude(App.Vector(0.0, 0.0, height)))
    return _fuse_shapes(pads)


def _build_hole_cutter_shape(detections, settings: Settings):
    cutters = []
    radius = settings.operation.hole_diameter / 2.0
    for detection in detections:
        nominal_bbox = nominal_cell_bbox(detection.bbox, detection.match.kind)
        for center_x, center_y in effective_hole_centers(
            nominal_bbox,
            detection.match.kind,
            settings.operation.subdividers_enabled,
            settings.operation.hole_pitch,
        ):
            cutters.append(
                Part.makeCylinder(
                    radius,
                    settings.operation.hole_depth,
                    App.Vector(center_x, center_y, detection.plane_z),
                    App.Vector(0.0, 0.0, 1.0),
                )
            )
    return Part.makeCompound(cutters)


def _build_channel_cell_cutter_shapes(preprocessed_shape, detections, settings: Settings):
    cutter_solids = []
    for detection in detections:
        nominal_bbox = nominal_cell_bbox(detection.bbox, detection.match.kind)
        child_bboxes = child_cell_bboxes(
            nominal_bbox,
            detection.match.kind,
            settings.operation.subdividers_enabled,
        )
        for child_bbox in child_bboxes:
            raw_cell = _build_single_cell_raw_channel_volume(child_bbox, detection.plane_z)
            keep_cell = _build_base_island_solid(child_bbox, detection.plane_z)
            try:
                cell_cutter = raw_cell.cut(keep_cell)
            except ValueError as exc:
                if "Null shape" in str(exc):
                    continue
                raise
            if _shape_is_empty(cell_cutter):
                continue
            try:
                clipped_cutter = cell_cutter.common(preprocessed_shape)
            except ValueError as exc:
                if "Null shape" in str(exc):
                    continue
                raise
            if not _shape_is_empty(clipped_cutter):
                cutter_solids.extend(_shape_solids(clipped_cutter))

    if not cutter_solids:
        raise OperationError("Profile cutters produced an empty shape.")
    return cutter_solids


def _build_grouped_channel_cutter_shapes(preprocessed_shape, detections, settings: Settings):
    grouped_cutters = []
    for detection in detections:
        nominal_bbox = nominal_cell_bbox(detection.bbox, detection.match.kind)
        raw_shape = _build_single_cell_raw_channel_volume(nominal_bbox, detection.plane_z)
        child_bboxes = child_cell_bboxes(
            nominal_bbox,
            detection.match.kind,
            settings.operation.subdividers_enabled,
        )
        keep_shapes = [
            _build_base_island_solid(child_bbox, detection.plane_z)
            for child_bbox in child_bboxes
        ]
        grouped_cutters.extend(
            _build_detection_channel_cutters(preprocessed_shape, raw_shape, keep_shapes)
        )
    if not grouped_cutters:
        raise OperationError("Profile cutters produced an empty shape.")
    return grouped_cutters


def _build_detection_channel_cutters(preprocessed_shape, raw_shape, keep_shapes, tolerance: float = 1e-6):
    try:
        channel_region = raw_shape.common(preprocessed_shape)
    except ValueError as exc:
        if "Null shape" in str(exc):
            return []
        raise
    if _shape_is_empty(channel_region):
        return []
    if not keep_shapes:
        return _shape_solids(channel_region)

    try:
        partitioned = SplitAPI.slice(channel_region, list(keep_shapes), "Split", tolerance)
    except Exception as exc:
        raise OperationError("Unable to build grouped channel cutter for a detected footprint.") from exc

    cutter_pieces = []
    for piece in _shape_solids(partitioned):
        if _piece_overlaps_any_tool(piece, keep_shapes, tolerance):
            continue
        cutter_pieces.append(piece)
    return cutter_pieces


def _build_preprocessed_rebuild_volume(detections, settings: Settings):
    solids = []
    for plane_z, plane_detections in _group_detections_by_plane(detections).items():
        nominal_bboxes = []
        for detection in plane_detections:
            nominal_bbox = nominal_cell_bbox(detection.bbox, detection.match.kind)
            nominal_bboxes.append(nominal_bbox)
        solids.append(_build_preprocessed_plane_volume(tuple(nominal_bboxes), plane_z))
    return _fuse_shapes(solids)


def _build_single_cell_raw_channel_volume(bbox, plane_z: float):
    base_face = Part.Face(
        _rounded_rect_wire(bbox, 0.0).translated(App.Vector(0.0, 0.0, plane_z))
    )
    return base_face.extrude(App.Vector(0.0, 0.0, BASE_PROFILE_HEIGHT))


def _collect_chamfer_edges(
    shape,
    detections,
    subdividers_enabled: bool,
    radius: float,
    pitch: float,
    chamfer_size: float,
):
    edge_specs = []
    target_centers = []
    for detection in detections:
        nominal_bbox = nominal_cell_bbox(detection.bbox, detection.match.kind)
        for center_x, center_y in effective_hole_centers(
            nominal_bbox,
            detection.match.kind,
            subdividers_enabled,
            pitch,
        ):
            target_centers.append((center_x, center_y, detection.plane_z))

    for edge_index, edge in enumerate(shape.Edges, start=1):
        curve = getattr(edge, "Curve", None)
        if curve is None or not hasattr(curve, "Center") or not hasattr(curve, "Radius"):
            continue
        center = curve.Center
        if abs(curve.Radius - radius) > 1e-3:
            continue
        if any(
            abs(center.x - target_x) <= 1e-3
            and abs(center.y - target_y) <= 1e-3
            and abs(center.z - target_z) <= 1e-3
            for target_x, target_y, target_z in target_centers
        ):
            edge_specs.append((edge_index, chamfer_size, chamfer_size))
    return edge_specs


def _build_base_island_solid(bbox, plane_z: float):
    lower_bbox = _inset_bbox(bbox, BASE_PROFILE_LOWER_SLOPE + BASE_PROFILE_UPPER_SLOPE)
    middle_bbox = _inset_bbox(bbox, BASE_PROFILE_UPPER_SLOPE)
    lower_wire = _rounded_rect_wire(lower_bbox, BASE_PROFILE_BOTTOM_RADIUS).translated(
        App.Vector(0.0, 0.0, plane_z)
    )
    middle_wire = _rounded_rect_wire(middle_bbox, BASE_PROFILE_WALL_RADIUS).translated(
        App.Vector(0.0, 0.0, plane_z + BASE_PROFILE_LOWER_SLOPE)
    )
    middle_top_wire = middle_wire.translated(App.Vector(0.0, 0.0, BASE_PROFILE_VERTICAL))
    top_wire = _rounded_rect_wire(bbox, BASE_PROFILE_TOP_RADIUS).translated(
        App.Vector(0.0, 0.0, plane_z + BASE_PROFILE_HEIGHT)
    )

    lower_transition = Part.makeLoft([lower_wire, middle_wire], True, True)
    middle_prism = Part.Face(middle_wire).extrude(App.Vector(0.0, 0.0, BASE_PROFILE_VERTICAL))
    upper_transition = Part.makeLoft([middle_top_wire, top_wire], True, True)
    return _fuse_shapes((lower_transition, middle_prism, upper_transition))


def _inset_bbox(bbox, inset: float):
    return type(bbox)(
        bbox.min_x + inset,
        bbox.min_y + inset,
        bbox.max_x - inset,
        bbox.max_y - inset,
    )


def _rounded_rect_wire(bbox, radius: float):
    width = bbox.width
    height = bbox.height
    radius = max(0.0, min(radius, width / 2.0 - 1e-6, height / 2.0 - 1e-6))
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


def _fuse_shapes(shapes):
    shapes = [shape for shape in shapes if shape is not None]
    if not shapes:
        raise OperationError("No shapes available to fuse.")
    fused = shapes[0]
    for shape in shapes[1:]:
        fused = fused.fuse(shape)
    try:
        fused = fused.removeSplitter()
    except Exception:
        pass
    return fused


def _merge_level_faces(bboxes, plane_z: float, inset: float, radius: float):
    faces = []
    for bbox in bboxes:
        inset_bbox = _inset_bbox(bbox, inset)
        wire = _rounded_rect_wire(inset_bbox, radius).translated(App.Vector(0.0, 0.0, plane_z))
        faces.append(Part.Face(wire))
    return _fuse_shapes(faces)


def _build_preprocessed_plane_volume(child_bboxes, plane_z: float):
    adjusted_face = _merge_level_faces(
        _top_ceiling_bboxes(child_bboxes),
        plane_z=plane_z,
        inset=0.0,
        radius=0.0,
    )
    adjusted_solid = adjusted_face.extrude(App.Vector(0.0, 0.0, BASE_PROFILE_HEIGHT))
    return _fillet_vertical_edges(adjusted_solid, BASE_PROFILE_TOP_RADIUS)


def _top_ceiling_bboxes(child_bboxes):
    ceiling_bboxes = []
    for bbox in child_bboxes:
        ceiling_bboxes.append(
            type(bbox)(
                bbox.min_x + (_edge_inset_for_side(child_bboxes, bbox, "left") * TOP_FOOTPRINT_OUTER_INSET),
                bbox.min_y + (_edge_inset_for_side(child_bboxes, bbox, "bottom") * TOP_FOOTPRINT_OUTER_INSET),
                bbox.max_x - (_edge_inset_for_side(child_bboxes, bbox, "right") * TOP_FOOTPRINT_OUTER_INSET),
                bbox.max_y - (_edge_inset_for_side(child_bboxes, bbox, "top") * TOP_FOOTPRINT_OUTER_INSET),
            )
        )
    return tuple(ceiling_bboxes)


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


def _fillet_vertical_edges(shape, radius: float):
    solids = getattr(shape, "Solids", None)
    if solids is not None and len(solids) > 1:
        return _fuse_shapes(_fillet_vertical_edges(solid, radius) for solid in solids)
    vertical_edges = []
    for edge in getattr(shape, "Edges", ()):
        vertices = getattr(edge, "Vertexes", ())
        if len(vertices) != 2:
            continue
        start = vertices[0].Point
        end = vertices[1].Point
        if (
            abs(start.x - end.x) <= 1e-6
            and abs(start.y - end.y) <= 1e-6
            and abs(start.z - end.z) > 1e-6
        ):
            vertical_edges.append(edge)
    if not vertical_edges:
        return shape
    try:
        filleted = shape.makeFillet(radius, vertical_edges)
    except Exception:
        return shape
    try:
        filleted = filleted.removeSplitter()
    except Exception:
        pass
    return filleted


def _merge_optional_base_with_rebuild(base_shape, rebuild_shape):
    if rebuild_shape is None or rebuild_shape.isNull():
        raise OperationError("Rebuilt lower section produced a null shape.")
    if _shape_is_empty(base_shape):
        return rebuild_shape.copy()
    try:
        merged = base_shape.fuse(rebuild_shape)
    except ValueError as exc:
        if "Null shape" not in str(exc):
            raise
        try:
            merged = base_shape.oldFuse(rebuild_shape)
        except Exception as old_fuse_exc:
            raise OperationError("Unable to merge prepared source with rebuilt lower section.") from old_fuse_exc
    try:
        merged = merged.removeSplitter()
    except Exception:
        pass
    return merged


def _shape_is_empty(shape) -> bool:
    if shape is None:
        return True
    try:
        if shape.isNull():
            return True
    except Exception:
        return True
    solids = getattr(shape, "Solids", None)
    if solids is not None and len(solids) == 0:
        return True
    try:
        if hasattr(shape, "Volume") and abs(shape.Volume) <= 1e-9:
            return True
    except Exception:
        pass
    return False


def _shape_solids(shape):
    if shape is None:
        return []
    solids = getattr(shape, "Solids", None)
    if solids is not None and len(solids) > 0:
        return list(solids)
    return [shape]


def _bbox_overlaps(left_bbox, right_bbox, tolerance: float = 1e-6) -> bool:
    return not (
        left_bbox.XMax < right_bbox.XMin - tolerance
        or left_bbox.XMin > right_bbox.XMax + tolerance
        or left_bbox.YMax < right_bbox.YMin - tolerance
        or left_bbox.YMin > right_bbox.YMax + tolerance
        or left_bbox.ZMax < right_bbox.ZMin - tolerance
        or left_bbox.ZMin > right_bbox.ZMax + tolerance
    )


def _rebuild_lower_section(base_shape, tool_shapes, tolerance: float = 1e-6):
    if _shape_is_empty(base_shape):
        raise OperationError("Preprocessed lower rebuild volume is empty.")
    if not tool_shapes:
        rebuilt = base_shape.copy()
        return rebuilt if rebuilt.isValid() else _heal_shape(rebuilt)

    try:
        partitioned = SplitAPI.slice(base_shape, list(tool_shapes), "Split", tolerance)
    except Exception as exc:
        raise OperationError("Unable to partition the preprocessed rebuild volume with channel cutters.") from exc

    kept_pieces = []
    for piece in _shape_solids(partitioned):
        if _piece_is_channel_volume(piece, tool_shapes, tolerance):
            continue
        kept_pieces.append(piece)

    if not kept_pieces:
        raise OperationError("Rebuilt lower section became empty after channel partitioning.")

    if len(kept_pieces) == 1:
        rebuilt = kept_pieces[0].copy()
    else:
        rebuilt = ShapeMerge.mergeSolids(kept_pieces, False)
    if rebuilt.isValid():
        return rebuilt
    healed = _heal_shape(rebuilt)
    return healed if healed.isValid() else rebuilt


def _piece_is_channel_volume(piece, tool_shapes, tolerance: float) -> bool:
    piece_volume = getattr(piece, "Volume", 0.0)
    if piece_volume <= tolerance:
        return True
    return _piece_overlaps_any_tool(piece, tool_shapes, tolerance)


def _piece_overlaps_any_tool(piece, tool_shapes, tolerance: float) -> bool:
    for tool_shape in tool_shapes:
        if _shape_is_empty(tool_shape):
            continue
        if not _bbox_overlaps(piece.BoundBox, tool_shape.BoundBox, tolerance):
            continue
        try:
            overlap = piece.common(tool_shape)
        except ValueError as exc:
            if "Null shape" in str(exc):
                continue
            raise
        overlap_volume = getattr(overlap, "Volume", 0.0) if not overlap.isNull() else 0.0
        if overlap_volume > tolerance:
            return True
    return False


def _heal_shape(shape):
    healed = shape
    try:
        healed = healed.removeSplitter()
    except Exception:
        pass
    if hasattr(healed, "fixTolerance"):
        try:
            fixed = healed.copy()
            fixed.fixTolerance(1e-6)
            healed = fixed
        except Exception:
            pass
    if hasattr(healed, "limitTolerance"):
        for args in ((1e-7, 1e-4), (1e-7, 1e-4, None)):
            try:
                fixed = healed.copy()
                fixed.limitTolerance(*args)
                healed = fixed
                break
            except Exception:
                continue
    if hasattr(healed, "fix"):
        for args in ((1e-6, 1e-7, 1e-3), (0.0, 0.0, 0.0), tuple()):
            try:
                fixed = healed.copy()
                fixed.fix(*args)
                healed = fixed
                break
            except Exception:
                continue
    try:
        healed = healed.removeSplitter()
    except Exception:
        pass
    return healed


def _validate_operation(detections, settings: Settings):
    return None


def _unique_name(doc, base_name: str) -> str:
    index = 1
    while doc.getObject(f"{base_name}{index}") is not None:
        index += 1
    return f"{base_name}{index}"
