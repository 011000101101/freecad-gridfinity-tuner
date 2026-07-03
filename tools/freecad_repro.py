#!/usr/bin/env python3
"""Headless FreeCAD repro and benchmark helpers for Gridfinity Magnet Fix."""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from dataclasses import dataclass


REPO_ROOT = "/media/sf_macros"
DEFAULT_STL_PATH = os.path.join(REPO_ROOT, "Gridfinity Metric Small Wrench Holder Inverse.stl")
OUTPUT_DIR = os.environ.get(
    "GRIDFINITY_MAGNET_FIX_DEBUG_DIR",
    os.path.expanduser("~/.cache/GridfinityMagnetFix/freecad_repro"),
)
REPORT_PATH = os.path.join(OUTPUT_DIR, "report.json")
UPPER_BAND_MIN_OFFSET = 6.0
LOWER_BAND_HEIGHT = 5.0
PROGRESS_ENABLED = os.environ.get("GRIDFINITY_MAGNET_FIX_PROGRESS", "0") == "1"


@dataclass
class _ShapeObject:
    Label: str
    Shape: object
    Placement: object

    def getGlobalPlacement(self):
        return self.Placement


@dataclass
class _ExportResult:
    mode: str
    deliverable_objects: tuple
    upper_component: object | None = None
    base_component: object | None = None


def _safe_call(fn, fallback=None):
    try:
        return fn()
    except Exception:
        return fallback


def _timed(stage_timings, label, fn):
    start = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - start
    stage_timings[label] = elapsed
    if PROGRESS_ENABLED:
        print(f"[stage] {label}: {elapsed:.3f}s", file=sys.stderr, flush=True)
    return result


def _shape_check(shape):
    if not hasattr(shape, "check"):
        return None
    for args in ((), (True,), (False,)):
        try:
            return repr(shape.check(*args))
        except Exception:
            continue
    return None


def _shape_summary(name, shape):
    if shape is None:
        return {"name": name, "has_shape": False}
    return {
        "name": name,
        "has_shape": True,
        "is_null": _safe_call(lambda: shape.isNull()),
        "is_valid": _safe_call(lambda: shape.isValid()),
        "solids": len(getattr(shape, "Solids", []) or []),
        "faces": len(getattr(shape, "Faces", []) or []),
        "edges": len(getattr(shape, "Edges", []) or []),
        "volume": _safe_call(lambda: float(shape.Volume)),
        "area": _safe_call(lambda: float(shape.Area)),
        "bound_box": _safe_call(
            lambda: {
                "xmin": float(shape.BoundBox.XMin),
                "ymin": float(shape.BoundBox.YMin),
                "zmin": float(shape.BoundBox.ZMin),
                "xmax": float(shape.BoundBox.XMax),
                "ymax": float(shape.BoundBox.YMax),
                "zmax": float(shape.BoundBox.ZMax),
            }
        ),
        "check": _shape_check(shape),
    }


def _band_volume(part_module, app_module, shape, z_min, z_max):
    if shape is None or _safe_call(lambda: shape.isNull(), True) or z_max <= z_min:
        return 0.0
    bbox = shape.BoundBox
    slab = part_module.makeBox(
        bbox.XLength + 20.0,
        bbox.YLength + 20.0,
        z_max - z_min,
        app_module.Vector(bbox.XMin - 10.0, bbox.YMin - 10.0, z_min),
    )
    try:
        common = shape.common(slab)
    except Exception:
        return 0.0
    if common.isNull():
        return 0.0
    return float(getattr(common, "Volume", 0.0))


def _vertical_cylindrical_face_count(shape, expected_radius, radius_tol=0.05):
    count = 0
    for face in getattr(shape, "Faces", ()):
        surface = getattr(face, "Surface", None)
        if surface is None or not hasattr(surface, "Radius") or not hasattr(surface, "Axis"):
            continue
        if abs(float(surface.Radius) - expected_radius) > radius_tol:
            continue
        axis = surface.Axis
        if abs(axis.x) > 1e-6 or abs(axis.y) > 1e-6 or abs(abs(axis.z) - 1.0) > 1e-6:
            continue
        count += 1
    return count


def _export_shape(name, shape, output_dir):
    if shape is None or _safe_call(lambda: shape.isNull(), True):
        return None
    path = os.path.join(output_dir, f"{name}.brep")
    try:
        shape.exportBrep(path)
        return path
    except Exception:
        return None


def _shape_from_object(document_object):
    return getattr(document_object, "Shape", None)


def run_case(
    stl_path,
    subdividers_enabled=False,
    output_mode="merge",
    export_shapes=True,
    output_dir=OUTPUT_DIR,
    export_result_file=False,
):
    os.makedirs(output_dir, exist_ok=True)
    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)

    import FreeCAD as App
    import Mesh
    import Part

    from gridfinity_magnet_fix.export_ops import build_export_mesh, build_result_export_mesh, export_result
    from gridfinity_magnet_fix.geometry import effective_hole_centers, nominal_cell_bbox
    from gridfinity_magnet_fix.mesh_prep import MESH_STITCH_TOLERANCE_MM
    from gridfinity_magnet_fix.ops import (
        _build_fill_pad_shape,
        _build_grouped_channel_cutter_shapes,
        _build_hole_cutter_shape,
        _build_preprocessed_rebuild_volume,
        _collect_chamfer_edges,
        _merge_optional_base_with_rebuild,
        _rebuild_lower_section,
        _refine_optional_shape,
    )
    from gridfinity_magnet_fix.segmentation import segment_upper_body
    from gridfinity_magnet_fix.settings import Settings

    timings = {}
    mesh = _timed(timings, "mesh_load", lambda: Mesh.Mesh(stl_path))

    def _mesh_to_solid():
        shape = Part.Shape()
        try:
            shape.makeShapeFromMesh(mesh.Topology, MESH_STITCH_TOLERANCE_MM, True)
        except TypeError:
            try:
                shape.makeShapeFromMesh(mesh.Topology, MESH_STITCH_TOLERANCE_MM)
            except TypeError:
                shape.makeShapeFromMesh(mesh.Topology)
        solid_shape = Part.Solid(Part.Shell(list(shape.Faces)))
        return solid_shape.removeSplitter()

    refined_shape = _timed(timings, "mesh_to_solid", _mesh_to_solid)
    source_min_z = float(refined_shape.BoundBox.ZMin)

    export_path = None
    settings = Settings()
    settings.operation.keep_intermediates_visible = True
    settings.operation.subdividers_enabled = subdividers_enabled
    settings.operation.output_mode = output_mode

    from gridfinity_magnet_fix.detect import detect_footprints

    detections = _timed(
        timings,
        "detect_footprints",
        lambda: detect_footprints(refined_shape, settings.detection),
    )
    fill_shape = _timed(timings, "build_fill_pads", lambda: _build_fill_pad_shape(detections))
    def _cut_source_lower():
        upper = refined_shape.copy().cut(fill_shape)
        if output_mode == "assemble":
            upper = _refine_optional_shape(upper)
        return upper

    upper_shape = _timed(timings, "cut_source_lower", _cut_source_lower)
    preprocessed_shape = _timed(
        timings,
        "build_preprocessed_lower",
        lambda: _build_preprocessed_rebuild_volume(detections, settings),
    )
    profile_cutter_shapes = _timed(
        timings,
        "build_profile_cutters",
        lambda: _build_grouped_channel_cutter_shapes(preprocessed_shape, detections, settings),
    )
    rebuilt_lower_shape = _timed(
        timings,
        "rebuild_lower_section",
        lambda: _rebuild_lower_section(preprocessed_shape, profile_cutter_shapes),
    )
    hole_cutter_shape = _timed(
        timings,
        "build_hole_cutters",
        lambda: _build_hole_cutter_shape(detections, settings),
    )
    base_shape = _timed(
        timings,
        "build_base_component",
        lambda: rebuilt_lower_shape.cut(hole_cutter_shape),
    )
    if settings.operation.chamfer_enabled:
        edge_specs = _collect_chamfer_edges(
            base_shape,
            detections,
            settings.operation.subdividers_enabled,
            settings.operation.hole_diameter / 2.0,
            settings.operation.hole_pitch,
            settings.operation.chamfer_size,
        )
        if edge_specs:
            def _apply_chamfer():
                edges = [base_shape.Edges[index - 1] for index, _, _ in edge_specs]
                return base_shape.makeChamfer(settings.operation.chamfer_size, edges)
            base_shape = _timed(timings, "apply_base_chamfer", _apply_chamfer)

    if output_mode == "merge":
        final_shape = _timed(
            timings,
            "merge_repaired_base",
            lambda: _merge_optional_base_with_rebuild(upper_shape, base_shape),
        )
        deliverable_objects = (
            _ShapeObject("Merged Result", final_shape, App.Placement()),
        )
    else:
        final_shape = None
        segmentation = _timed(
            timings,
            "segment_upper_body",
            lambda: segment_upper_body(upper_shape, detections, settings),
        )
        segmented_objects = tuple(
            _ShapeObject(component.label, component.shape, App.Placement())
            for component in segmentation.components
        )
        deliverable_objects = segmented_objects + (
            _ShapeObject("Repaired Base Component", base_shape, App.Placement()),
        )

    upper_component = _ShapeObject("Prepared Upper Body", upper_shape, App.Placement())
    base_component = _ShapeObject("Repaired Base Component", base_shape, App.Placement())
    export_result_wrapper = _ExportResult(
        output_mode,
        deliverable_objects,
        upper_component=upper_component,
        base_component=base_component,
    )
    if export_result_file:
        suffix = ".3mf" if output_mode == "assemble" else ".stl"
        export_path = os.path.join(output_dir, f"exported_result{suffix}")
        _timed(timings, "export_result", lambda: export_result(export_result_wrapper, export_path))

    deliverable_shapes = [
        _shape_summary(document_object.Label, _shape_from_object(document_object))
        for document_object in deliverable_objects
    ]
    deliverable_meshes = []
    if output_mode == "merge":
        mesh = build_result_export_mesh(export_result_wrapper)
        deliverable_meshes.append(
            {
                "label": "Merged Result",
                "is_solid": mesh.isSolid(),
                "has_non_manifolds": mesh.hasNonManifolds(),
                "components": mesh.countComponents(),
                "facets": mesh.CountFacets,
            }
        )
    else:
        for document_object in deliverable_objects:
            mesh = build_export_mesh(document_object, export_mode=output_mode)
            deliverable_meshes.append(
                {
                    "label": document_object.Label,
                    "is_solid": mesh.isSolid(),
                    "has_non_manifolds": mesh.hasNonManifolds(),
                    "components": mesh.countComponents(),
                    "facets": mesh.CountFacets,
                }
            )
    hole_radius = settings.operation.hole_diameter / 2.0

    report = {
            "stl_path": stl_path,
            "subdividers_enabled": subdividers_enabled,
            "output_mode": output_mode,
            "timings": timings,
            "result_mode": output_mode,
            "detections": [
                {
                    "face_index": det.face_index,
                    "plane_z": det.plane_z,
                    "bbox": {
                        "min_x": det.bbox.min_x,
                        "min_y": det.bbox.min_y,
                        "max_x": det.bbox.max_x,
                        "max_y": det.bbox.max_y,
                    },
                    "kind": det.match.kind.value,
                    "family": det.match.family.value,
                }
                for det in detections
            ],
            "shapes": [
                _shape_summary("source_refined", refined_shape),
                _shape_summary("prepared_upper_body", upper_shape),
                _shape_summary("repaired_base_component", base_shape),
                _shape_summary("final_shape", final_shape),
            ],
            "deliverables": deliverable_shapes,
            "deliverable_meshes": deliverable_meshes,
            "metrics": {
                "source_volume": _safe_call(lambda: float(refined_shape.Volume), 0.0),
                "prepared_upper_band_volume": _band_volume(
                    Part,
                    App,
                    upper_shape,
                    source_min_z + UPPER_BAND_MIN_OFFSET,
                    upper_shape.BoundBox.ZMax + 1.0,
                ) if upper_shape is not None else 0.0,
                "base_lower_band_volume": _band_volume(
                    Part,
                    App,
                    base_shape,
                    source_min_z,
                    source_min_z + LOWER_BAND_HEIGHT,
                ) if base_shape is not None else 0.0,
                "final_lower_band_volume": _band_volume(
                    Part,
                    App,
                    final_shape,
                    source_min_z,
                    source_min_z + LOWER_BAND_HEIGHT,
                ) if final_shape is not None else 0.0,
                "expected_hole_count": sum(
                    len(
                        effective_hole_centers(
                            nominal_cell_bbox(det.bbox, det.match.kind),
                            det.match.kind,
                            subdividers_enabled,
                            settings.operation.hole_pitch,
                        )
                    )
                    for det in detections
                ),
                "base_hole_face_count": _vertical_cylindrical_face_count(base_shape, hole_radius) if base_shape is not None else 0,
            },
            "export": {
                "path": export_path,
                "exists": bool(export_path and os.path.exists(export_path)),
                "size": os.path.getsize(export_path) if export_path and os.path.exists(export_path) else 0,
            },
            "exports": {
                "source_refined": _export_shape("source_refined", refined_shape, output_dir) if export_shapes else None,
                "prepared_upper_body": _export_shape("prepared_upper_body", upper_shape, output_dir) if export_shapes else None,
                "repaired_base_component": _export_shape("repaired_base_component", base_shape, output_dir) if export_shapes else None,
                "final_shape": _export_shape("final_shape", final_shape, output_dir) if export_shapes else None,
            },
        }
    if export_path and os.path.exists(export_path):
        try:
            exported_mesh = Mesh.Mesh(export_path)
            report["export_mesh"] = {
                "is_solid": exported_mesh.isSolid(),
                "has_non_manifolds": exported_mesh.hasNonManifolds(),
                "components": exported_mesh.countComponents(),
                "facets": exported_mesh.CountFacets,
            }
        except Exception:
            report["export_mesh"] = None
    return report


def main():
    stl_path = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GRIDFINITY_MAGNET_FIX_STL", DEFAULT_STL_PATH)
    subdividers_enabled = os.environ.get("GRIDFINITY_MAGNET_FIX_SUBDIVIDERS", "0") == "1"
    output_mode = os.environ.get("GRIDFINITY_MAGNET_FIX_OUTPUT_MODE", "merge")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    report = run_case(
        stl_path,
        subdividers_enabled=subdividers_enabled,
        output_mode=output_mode,
        export_shapes=True,
        output_dir=OUTPUT_DIR,
        export_result_file=True,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as handle:
        handle.write(rendered)
        handle.write("\n")
    print(rendered)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
