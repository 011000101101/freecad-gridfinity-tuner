"""Mesh to refined solid conversion."""

from __future__ import annotations

try:
    import FreeCAD as App
    import FreeCADGui as Gui
    import Part
except ImportError:  # pragma: no cover - only available inside FreeCAD
    App = None
    Gui = None
    Part = None

from .ui_utils import selected_document_object


MESH_STITCH_TOLERANCE_MM = 0.1


def prepare_selected_mesh(source_object=None):
    if App is None or Part is None or Gui is None:  # pragma: no cover
        raise RuntimeError("FreeCAD Part API is not available in this environment.")
    doc = App.ActiveDocument
    if doc is None:
        raise RuntimeError("No active document.")

    source_object = source_object or selected_document_object()
    if source_object is None or not hasattr(source_object, "Mesh"):
        raise RuntimeError("Select exactly one mesh object.")

    mesh = source_object.Mesh
    shape = Part.Shape()

    # Source:
    # The standard Part workflow is Shape from mesh -> Convert to solid ->
    # Refine shape. This follows the documented user steps directly.
    # https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/FreeCAD_and_Mesh_Import.md
    try:
        shape.makeShapeFromMesh(mesh.Topology, MESH_STITCH_TOLERANCE_MM, True)
    except TypeError:
        try:
            shape.makeShapeFromMesh(mesh.Topology, MESH_STITCH_TOLERANCE_MM)
        except TypeError:
            shape.makeShapeFromMesh(mesh.Topology)

    if shape.isNull():
        raise RuntimeError("Failed to create a Part shape from the selected mesh.")

    shape_obj = doc.addObject("Part::Feature", _unique_name(doc, "MeshShape"))
    shape_obj.Label = f"{source_object.Label} Shape"
    shape_obj.Shape = shape
    shape_obj.purgeTouched()

    faces = list(shape_obj.Shape.Faces)
    if not faces:
        raise RuntimeError("Shape from mesh did not produce any faces that can be converted to a solid.")

    try:
        solid_shape = Part.Solid(Part.Shell(faces))
    except Exception as exc:
        raise RuntimeError(
            "Shape from mesh did not produce a closed shell that can be converted to a solid."
        ) from exc

    solid_obj = doc.addObject("Part::Feature", _unique_name(doc, "MeshSolid"))
    solid_obj.Label = f"{source_object.Label} Solid"
    solid_obj.Shape = solid_shape

    refined_shape = solid_shape.removeSplitter()
    refined_obj = doc.addObject("Part::Feature", _unique_name(doc, "RefinedSolid"))
    refined_obj.Label = f"{source_object.Label} Refined"
    refined_obj.Shape = refined_shape

    doc.recompute()

    if hasattr(source_object, "ViewObject"):
        source_object.ViewObject.Visibility = False
    shape_obj.ViewObject.Visibility = False
    solid_obj.ViewObject.Visibility = False
    refined_obj.ViewObject.Visibility = True
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(refined_obj)
    return refined_obj


def _unique_name(doc, base_name: str) -> str:
    index = 1
    while doc.getObject(f"{base_name}{index}") is not None:
        index += 1
    return f"{base_name}{index}"
