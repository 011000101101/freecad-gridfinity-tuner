"""Document operations for Gridfinity Magnet Fix."""

from __future__ import annotations

from dataclasses import dataclass

from .detect import DetectionError, detect_footprints
from .geometry import hole_centers
from .settings import Settings

try:
    import FreeCAD as App
    import FreeCADGui as Gui
    import Part
except ImportError:  # pragma: no cover - only available inside FreeCAD
    App = None
    Gui = None
    Part = None


class OperationError(RuntimeError):
    """Raised when model operations fail."""


@dataclass(slots=True)
class OperationResult:
    container: object
    final_object: object
    detections: list


def execute(doc, source_object, settings: Settings) -> OperationResult:
    if App is None or Part is None:  # pragma: no cover
        raise OperationError("FreeCAD Part API is not available in this environment.")
    if doc is None:
        raise OperationError("No active document.")
    if source_object is None or not hasattr(source_object, "Shape"):
        raise OperationError("Select a source object with a valid solid shape.")

    detections = detect_footprints(source_object.Shape, settings.detection)
    container = doc.addObject("App::Part", _unique_name(doc, "GridfinityMagnetFix"))
    container.Label = settings.operation.result_label

    source_copy = doc.addObject("Part::Feature", _unique_name(doc, "GFSource"))
    source_copy.Shape = source_object.Shape.copy()
    source_copy.Label = f"{source_object.Label} Source"
    source_copy.Placement = source_object.Placement
    container.addObject(source_copy)

    fill_feature = doc.addObject("Part::Feature", _unique_name(doc, "GFFillPads"))
    fill_feature.Shape = _build_fill_pad_shape(detections, settings.operation.fill_height)
    fill_feature.Label = "Fill Pads"
    container.addObject(fill_feature)

    fuse = doc.addObject("Part::Fuse", _unique_name(doc, "GFFused"))
    fuse.Base = source_copy
    fuse.Tool = fill_feature
    fuse.Label = "Filled Base"
    if hasattr(fuse, "Refine"):
        fuse.Refine = True
    container.addObject(fuse)

    hole_feature = doc.addObject("Part::Feature", _unique_name(doc, "GFHoleCutters"))
    hole_feature.Shape = _build_hole_cutter_shape(detections, settings)
    hole_feature.Label = "Hole Cutters"
    container.addObject(hole_feature)

    cut = doc.addObject("Part::Cut", _unique_name(doc, "GFHoleCut"))
    cut.Base = fuse
    cut.Tool = hole_feature
    cut.Label = "Magnet Pockets"
    if hasattr(cut, "Refine"):
        cut.Refine = True
    container.addObject(cut)

    doc.recompute()

    final_object = cut
    if settings.operation.chamfer_enabled:
        edge_list = _collect_chamfer_edges(
            cut.Shape,
            detections,
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
        for obj in (source_copy, fill_feature, fuse, hole_feature, cut):
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


def _build_fill_pad_shape(detections, fill_height: float):
    pads = []
    for detection in detections:
        outer_wire = detection.outer_wire.copy()
        pad_face = Part.Face(outer_wire)
        pads.append(pad_face.extrude(App.Vector(0.0, 0.0, fill_height)))
    return Part.makeCompound(pads)


def _build_hole_cutter_shape(detections, settings: Settings):
    cutters = []
    radius = settings.operation.hole_diameter / 2.0
    for detection in detections:
        for center_x, center_y in hole_centers(
            detection.bbox,
            detection.match.kind,
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


def _collect_chamfer_edges(shape, detections, radius: float, pitch: float, chamfer_size: float):
    edge_specs = []
    target_centers = []
    for detection in detections:
        for center_x, center_y in hole_centers(detection.bbox, detection.match.kind, pitch):
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


def _unique_name(doc, base_name: str) -> str:
    index = 1
    while doc.getObject(f"{base_name}{index}") is not None:
        index += 1
    return f"{base_name}{index}"
