"""Export helpers for Gridfinity Magnet Fix results."""

from __future__ import annotations

import os
import tempfile
import uuid

try:
    import FreeCAD as App
    import Mesh
    import MeshPart
    import Part
except ImportError:  # pragma: no cover - only available inside FreeCAD
    App = None
    Mesh = None
    MeshPart = None
    Part = None

from .settings import OUTPUT_MODE_ASSEMBLE, OUTPUT_MODE_MERGE


DEFAULT_MESH_DEFLECTION = 0.1
DEFAULT_ANGULAR_DEFLECTION = 0.523599


class ExportError(RuntimeError):
    """Raised when exporting a result fails."""


def export_result(result, filename: str):
    if App is None or Mesh is None:  # pragma: no cover
        raise ExportError("FreeCAD mesh export is not available in this environment.")
    if result is None:
        raise ExportError("No operation result is available to export.")
    if not filename:
        raise ExportError("No export filename was provided.")

    export_mode = getattr(result, "mode", OUTPUT_MODE_MERGE)
    ext = os.path.splitext(filename)[1].lower()
    if export_mode == OUTPUT_MODE_ASSEMBLE and ext != ".3mf":
        raise ExportError("Assembly export currently supports only .3mf files.")
    if export_mode == OUTPUT_MODE_MERGE and ext != ".stl":
        raise ExportError("Merged result export currently supports only .stl files.")

    deliverables = list(getattr(result, "deliverable_objects", ()) or ())
    if not deliverables:
        raise ExportError("No deliverable objects are available for export.")

    temp_doc_name = f"GFExport{uuid.uuid4().hex[:8]}"
    if export_mode == OUTPUT_MODE_ASSEMBLE and _can_native_export(deliverables):
        try:
            Mesh.export(deliverables, filename)
            return
        except Exception as exc:
            raise ExportError(f"Failed to export result to {filename}.") from exc

    temp_doc = App.newDocument(temp_doc_name)
    try:
        mesh_objects = []
        if export_mode == OUTPUT_MODE_MERGE:
            mesh_feature = temp_doc.addObject("Mesh::Feature", "ExportMesh1")
            mesh_feature.Label = "Merged_Result"
            mesh_feature.Mesh = build_result_export_mesh(result)
            mesh_objects.append(mesh_feature)
        else:
            for index, document_object in enumerate(deliverables, start=1):
                mesh_feature = temp_doc.addObject("Mesh::Feature", f"ExportMesh{index}")
                mesh_feature.Label = _export_label(document_object, index)
                mesh_feature.Mesh = build_export_mesh(document_object, export_mode=export_mode)
                if hasattr(document_object, "getGlobalPlacement"):
                    mesh_feature.Placement = document_object.getGlobalPlacement()
                elif hasattr(document_object, "Placement"):
                    mesh_feature.Placement = document_object.Placement
                mesh_objects.append(mesh_feature)
        temp_doc.recompute()
        Mesh.export(mesh_objects, filename)
    except Exception as exc:
        raise ExportError(f"Failed to export result to {filename}.") from exc
    finally:
        try:
            App.closeDocument(temp_doc.Name)
        except Exception:
            pass


def build_export_mesh(document_object, export_mode: str = OUTPUT_MODE_ASSEMBLE):
    shape = getattr(document_object, "Shape", None)
    if shape is None or shape.isNull():
        raise ExportError(f"Object {getattr(document_object, 'Label', '<unnamed>')} has no valid shape.")
    shape = _refine_export_shape(shape)
    if export_mode == OUTPUT_MODE_MERGE:
        return _mesh_shape_per_solid(shape)
    label = getattr(document_object, "Label", "<unnamed>")
    mesh = Mesh.Mesh()
    solids = _exportable_solids(shape)
    if solids:
        for solid in solids:
            mesh.addMesh(_mesh_from_single_shape(solid))
    else:
        mesh.addMesh(_mesh_from_single_shape(shape))
    try:
        _validate_export_mesh(mesh, label)
        return mesh
    except ExportError:
        rebuilt_shape = _rebuild_shape_from_faces(shape)
        if rebuilt_shape is not None:
            rebuilt_mesh = _mesh_shape_per_solid(rebuilt_shape)
            try:
                _validate_export_mesh(rebuilt_mesh, label)
                return rebuilt_mesh
            except ExportError:
                pass
        native_mesh = _mesh_via_native_export(document_object)
        _validate_export_mesh(native_mesh, label)
        return native_mesh


def build_result_export_mesh(result):
    export_mode = getattr(result, "mode", OUTPUT_MODE_MERGE)
    if export_mode == OUTPUT_MODE_ASSEMBLE:
        raise ExportError("Result-level export mesh is only used for merged export.")

    upper_object = getattr(result, "upper_component", None)
    base_object = getattr(result, "base_component", None)
    if upper_object is None or base_object is None:
        deliverables = list(getattr(result, "deliverable_objects", ()) or ())
        if len(deliverables) != 1:
            raise ExportError("Merged export requires upper and base components or a single deliverable.")
        return build_export_mesh(deliverables[0], export_mode=OUTPUT_MODE_MERGE)

    upper_shape = getattr(upper_object, "Shape", None)
    base_shape = getattr(base_object, "Shape", None)
    if upper_shape is None or upper_shape.isNull():
        raise ExportError("Prepared upper body is missing for merged export.")
    if base_shape is None or base_shape.isNull():
        raise ExportError("Repaired base component is missing for merged export.")

    from .ops import _merge_optional_base_with_rebuild

    export_shape = _merge_optional_base_with_rebuild(_refine_export_shape(upper_shape), base_shape)
    mesh = _mesh_from_single_shape(export_shape)
    _validate_export_mesh(mesh, "Merged Result")
    return mesh


def _mesh_from_single_shape(shape):
    if MeshPart is not None:
        return MeshPart.meshFromShape(
            Shape=shape,
            LinearDeflection=DEFAULT_MESH_DEFLECTION,
            AngularDeflection=DEFAULT_ANGULAR_DEFLECTION,
            Relative=False,
        )
    return Mesh.Mesh(shape.tessellate(DEFAULT_MESH_DEFLECTION))


def _mesh_shape_per_solid(shape):
    mesh = Mesh.Mesh()
    solids = _exportable_solids(shape)
    if solids:
        for solid in solids:
            mesh.addMesh(_mesh_from_single_shape(solid))
        return mesh
    mesh.addMesh(_mesh_from_single_shape(shape))
    return mesh


def _refine_export_shape(shape):
    try:
        refined = shape.removeSplitter()
    except Exception:
        return shape
    try:
        if refined.isNull():
            return shape
    except Exception:
        return shape
    return refined


def _exportable_solids(shape):
    solids = list(getattr(shape, "Solids", None) or ())
    if not solids:
        return ()
    exportable = []
    for solid in solids:
        exportable.append(_repair_export_solid(solid))
    return tuple(exportable)


def _repair_export_solid(solid):
    candidates = [solid]
    for builder in (
        lambda current: current.removeSplitter(),
        _rebuild_solid_from_faces,
    ):
        try:
            candidate = builder(solid)
        except Exception:
            continue
        if candidate is None:
            continue
        candidates.append(candidate)

    best_candidate = solid
    for candidate in candidates:
        try:
            mesh = _mesh_from_single_shape(candidate)
        except Exception:
            continue
        if mesh.isSolid() and not mesh.hasNonManifolds():
            return candidate
        best_candidate = candidate
    return best_candidate


def _rebuild_solid_from_faces(solid):
    if Part is None:
        return solid
    shell = Part.Shell(list(getattr(solid, "Faces", ()) or ()))
    rebuilt = Part.Solid(shell)
    try:
        rebuilt = rebuilt.removeSplitter()
    except Exception:
        pass
    return rebuilt


def _rebuild_shape_from_faces(shape):
    if Part is None:
        return None
    faces = list(getattr(shape, "Faces", ()) or ())
    if not faces:
        return None
    try:
        shell = Part.Shell(faces)
        rebuilt = Part.Solid(shell)
    except Exception:
        return None
    try:
        rebuilt = rebuilt.removeSplitter()
    except Exception:
        pass
    return rebuilt


def _validate_export_mesh(mesh, label: str):
    if mesh.hasNonManifolds():
        raise ExportError(f"Export mesh for {label} contains non-manifold edges.")
    if not mesh.isSolid():
        raise ExportError(f"Export mesh for {label} is not closed.")


def _export_label(document_object, index: int) -> str:
    label = getattr(document_object, "Label", "") or f"Component {index}"
    return label.replace(" ", "_")


def _can_native_export(document_objects) -> bool:
    if not document_objects:
        return False
    for document_object in document_objects:
        if getattr(document_object, "Document", None) is None:
            return False
        if getattr(document_object, "Name", None) is None:
            return False
        if getattr(document_object, "Shape", None) is None:
            return False
    return True


def _mesh_via_native_export(document_object):
    if App is None or Mesh is None:
        raise ExportError("Native mesh export is not available in this environment.")
    temp_doc_name = f"GFNativeMesh{uuid.uuid4().hex[:8]}"
    temp_doc = App.newDocument(temp_doc_name)
    fd, path = tempfile.mkstemp(suffix=".stl", prefix="gf_native_mesh_")
    os.close(fd)
    try:
        part_feature = temp_doc.addObject("Part::Feature", "ExportShape")
        part_feature.Label = _export_label(document_object, 1)
        part_feature.Shape = getattr(document_object, "Shape")
        temp_doc.recompute()
        Mesh.export([part_feature], path)
        return Mesh.Mesh(path)
    except Exception as exc:
        raise ExportError(
            f"Native mesh export fallback failed for {getattr(document_object, 'Label', '<unnamed>')}."
        ) from exc
    finally:
        try:
            App.closeDocument(temp_doc.Name)
        except Exception:
            pass
        try:
            os.remove(path)
        except Exception:
            pass
