#!/usr/bin/env python3
"""Headless rim-detection regression benchmark."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "gridfinity_magnet_fix"
CASE_DEFS = {
    "small": ("Gridfinity Metric Small Wrench Holder Inverse.stl", False),
    "medium": ("Gridfinity Metric Medium Wrench Holder Inverse.stl", False),
    "bruch": ("1x5x3-cutout-for-bruch.stl", True),
}


@dataclass
class _ShapeObject:
    Label: str
    Shape: object
    Placement: object

    def getGlobalPlacement(self):
        return self.Placement


def _load_mesh_to_solid(mesh_module, part_module, tolerance_mm: float, stl_path: str):
    mesh = mesh_module.Mesh(stl_path)
    shape = part_module.Shape()
    try:
        shape.makeShapeFromMesh(mesh.Topology, tolerance_mm, True)
    except TypeError:
        try:
            shape.makeShapeFromMesh(mesh.Topology, tolerance_mm)
        except TypeError:
            shape.makeShapeFromMesh(mesh.Topology)
    return part_module.Solid(part_module.Shell(list(shape.Faces))).removeSplitter()


def run_case(case_name: str):
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    import FreeCAD as App
    import Mesh
    import Part

    from gridfinity_magnet_fix.detect import detect_footprints
    from gridfinity_magnet_fix.export_ops import build_export_mesh
    from gridfinity_magnet_fix.mesh_prep import MESH_STITCH_TOLERANCE_MM
    from gridfinity_magnet_fix.ops import (
        _build_fill_pad_shape,
        _build_grouped_channel_cutter_shapes,
        _build_hole_cutter_shape,
        _build_preprocessed_rebuild_volume,
        _rebuild_lower_section,
    )
    from gridfinity_magnet_fix.segmentation import split_body_and_optional_rim
    from gridfinity_magnet_fix.settings import factory_settings

    filename, expect_rim = CASE_DEFS[case_name]
    source_shape = _load_mesh_to_solid(Mesh, Part, MESH_STITCH_TOLERANCE_MM, str(REPO_ROOT / filename))
    settings = factory_settings()
    detections = detect_footprints(source_shape, settings.detection)

    fill_shape = _build_fill_pad_shape(detections)
    upper_shape = source_shape.copy().cut(fill_shape).removeSplitter()
    preprocessed_shape = _build_preprocessed_rebuild_volume(detections, settings)
    cutter_shapes = _build_grouped_channel_cutter_shapes(preprocessed_shape, detections, settings)
    rebuilt_lower = _rebuild_lower_section(preprocessed_shape, cutter_shapes)
    base_shape = rebuilt_lower.cut(_build_hole_cutter_shape(detections, settings))

    split = split_body_and_optional_rim(upper_shape, detections, settings, True)
    deliverables = [
        _ShapeObject("Prepared Upper Body", split.body_shape, App.Placement()),
    ]
    if split.components:
        deliverables.append(_ShapeObject(split.components[0].label, split.components[0].shape, App.Placement()))
    deliverables.append(_ShapeObject("Repaired Base Component", base_shape, App.Placement()))

    deliverable_meshes = []
    for deliverable in deliverables:
        mesh = build_export_mesh(deliverable, export_mode="assemble")
        deliverable_meshes.append(
            {
                "label": deliverable.Label,
                "is_solid": mesh.isSolid(),
                "has_non_manifolds": mesh.hasNonManifolds(),
                "components": mesh.countComponents(),
                "facets": mesh.CountFacets,
            }
        )

    has_rim = any(component.key == "rim" for component in split.components)
    failures = []
    if has_rim != expect_rim:
        failures.append(f"expected rim={expect_rim}, got rim={has_rim}")
    if not split.body_shape.isValid():
        failures.append("prepared upper body is invalid after rim split")
    if float(getattr(base_shape, "Volume", 0.0)) <= 1e-3:
        failures.append("repaired base component is empty")
    for mesh_info in deliverable_meshes:
        if not mesh_info["is_solid"]:
            failures.append(f"{mesh_info['label']} mesh is not closed")
        if mesh_info["has_non_manifolds"]:
            failures.append(f"{mesh_info['label']} mesh has non-manifold edges")

    return {
        "case": case_name,
        "file": filename,
        "expected_rim": expect_rim,
        "has_rim": has_rim,
        "rim_detection": {
            "inner_top_z": split.rim_detection.inner_top_z,
            "possible_rim_min_z": split.rim_detection.possible_rim_min_z,
            "possible_rim_height": split.rim_detection.possible_rim_height,
            "rim_z_min": split.rim_detection.rim_z_min,
            "rim_z_max": split.rim_detection.rim_z_max,
        },
        "deliverables": deliverable_meshes,
        "failures": failures,
    }


def main():
    selected = sys.argv[1:] or list(CASE_DEFS)
    results = {}
    failures = {}
    for case_name in selected:
        if case_name not in CASE_DEFS:
            raise SystemExit(f"Unknown case: {case_name}")
        report = run_case(case_name)
        results[case_name] = report
        if report["failures"]:
            failures[case_name] = report["failures"]
    print(json.dumps({"results": results, "failures": failures}, indent=2, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
