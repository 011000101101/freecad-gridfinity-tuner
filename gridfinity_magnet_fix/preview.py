"""Temporary preview object helpers."""

from __future__ import annotations

from .geometry import effective_hole_centers, nominal_cell_bbox, subdivider_segments

try:
    import FreeCAD as App
    import FreeCADGui as Gui
    import Part
except ImportError:  # pragma: no cover - only available inside FreeCAD
    App = None
    Gui = None
    Part = None


PREVIEW_NAMES = ("GFPreviewFootprints", "GFPreviewHoles", "GFPreviewSubdividers")


def clear_preview(doc):
    if App is None or doc is None:  # pragma: no cover
        return
    for name in PREVIEW_NAMES:
        obj = doc.getObject(name)
        if obj is not None:
            doc.removeObject(obj.Name)


def update_preview(doc, detections, settings):
    if App is None or Part is None or doc is None:  # pragma: no cover
        return

    clear_preview(doc)
    if not detections:
        return

    footprint_shapes = []
    hole_shapes = []
    seam_shapes = []
    hole_radius = settings.operation.hole_diameter / 2.0
    for detection in detections:
        nominal_bbox = nominal_cell_bbox(detection.bbox, detection.match.kind)
        footprint_shapes.append(_bbox_wire(nominal_bbox, detection.plane_z))
        for center_x, center_y in effective_hole_centers(
            nominal_bbox,
            detection.match.kind,
            settings.operation.subdividers_enabled,
            settings.operation.hole_pitch,
        ):
            hole_shapes.append(
                Part.Wire(
                    [Part.makeCircle(hole_radius, App.Vector(center_x, center_y, detection.plane_z))]
                )
            )
        if settings.operation.subdividers_enabled:
            for start_x, start_y, end_x, end_y in subdivider_segments(nominal_bbox, detection.match.kind):
                seam_shapes.append(
                    Part.makeLine(
                        App.Vector(start_x, start_y, detection.plane_z),
                        App.Vector(end_x, end_y, detection.plane_z),
                    )
                )

    footprint_obj = doc.addObject("Part::Feature", PREVIEW_NAMES[0])
    footprint_obj.Shape = Part.makeCompound(footprint_shapes)

    holes_obj = doc.addObject("Part::Feature", PREVIEW_NAMES[1])
    holes_obj.Shape = Part.makeCompound(hole_shapes)

    seam_obj = None
    if seam_shapes:
        seam_obj = doc.addObject("Part::Feature", PREVIEW_NAMES[2])
        seam_obj.Shape = Part.makeCompound(seam_shapes)

    if Gui is not None:  # pragma: no branch - GUI only
        footprint_obj.ViewObject.LineColor = (0.0, 0.8, 0.8)
        footprint_obj.ViewObject.LineWidth = 3
        holes_obj.ViewObject.LineColor = (1.0, 0.3, 0.2)
        holes_obj.ViewObject.LineWidth = 2
        if seam_obj is not None:
            seam_obj.ViewObject.LineColor = (0.95, 0.75, 0.1)
            seam_obj.ViewObject.LineWidth = 2


def _bbox_wire(bbox, plane_z: float):
    return Part.makePolygon(
        (
            App.Vector(bbox.min_x, bbox.min_y, plane_z),
            App.Vector(bbox.max_x, bbox.min_y, plane_z),
            App.Vector(bbox.max_x, bbox.max_y, plane_z),
            App.Vector(bbox.min_x, bbox.max_y, plane_z),
            App.Vector(bbox.min_x, bbox.min_y, plane_z),
        )
    )
