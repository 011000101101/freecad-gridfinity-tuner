"""Temporary preview object helpers."""

from __future__ import annotations

from .geometry import hole_centers

try:
    import FreeCAD as App
    import FreeCADGui as Gui
    import Part
except ImportError:  # pragma: no cover - only available inside FreeCAD
    App = None
    Gui = None
    Part = None


PREVIEW_NAMES = ("GFPreviewFootprints", "GFPreviewHoles")


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

    footprint_shapes = [detection.outer_wire.copy() for detection in detections]
    hole_shapes = []
    hole_radius = settings.operation.hole_diameter / 2.0
    for detection in detections:
        for center_x, center_y in hole_centers(detection.bbox, detection.match.kind, settings.operation.hole_pitch):
            hole_shapes.append(
                Part.Wire(
                    [Part.makeCircle(hole_radius, App.Vector(center_x, center_y, detection.plane_z))]
                )
            )

    footprint_obj = doc.addObject("Part::Feature", PREVIEW_NAMES[0])
    footprint_obj.Shape = Part.makeCompound(footprint_shapes)

    holes_obj = doc.addObject("Part::Feature", PREVIEW_NAMES[1])
    holes_obj.Shape = Part.makeCompound(hole_shapes)

    if Gui is not None:  # pragma: no branch - GUI only
        footprint_obj.ViewObject.LineColor = (0.0, 0.8, 0.8)
        footprint_obj.ViewObject.LineWidth = 3
        holes_obj.ViewObject.LineColor = (1.0, 0.3, 0.2)
        holes_obj.ViewObject.LineWidth = 2
