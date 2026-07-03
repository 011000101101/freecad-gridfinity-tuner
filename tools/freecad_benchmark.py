#!/usr/bin/env python3
"""Headless regression benchmark harness for Gridfinity Magnet Fix."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

from freecad_repro import REPO_ROOT, run_case


BASELINE_PATH = Path(REPO_ROOT) / "tests" / "freecad_regression_baseline.json"
BENCHMARK_CASES = [
    ("small_merge", "Gridfinity Metric Small Wrench Holder Inverse.stl", False, "merge"),
    ("small_assemble", "Gridfinity Metric Small Wrench Holder Inverse.stl", False, "assemble"),
    ("medium_merge", "Gridfinity Metric Medium Wrench Holder Inverse.stl", False, "merge"),
    ("medium_assemble", "Gridfinity Metric Medium Wrench Holder Inverse.stl", False, "assemble"),
    ("bruch_merge", "1x5x3-cutout-for-bruch.stl", False, "merge"),
    ("bruch_assemble", "1x5x3-cutout-for-bruch.stl", False, "assemble"),
]


def _load_baseline():
    if not BASELINE_PATH.exists():
        return {}
    with open(BASELINE_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _rel_close(actual, expected, rel_tol=0.01, abs_tol=1e-3):
    return math.isclose(actual, expected, rel_tol=rel_tol, abs_tol=abs_tol)


def _shape_map(report):
    return {shape["name"]: shape for shape in report["shapes"]}


def _summarize_case(report):
    shapes = _shape_map(report)
    metrics = report["metrics"]
    deliverable_meshes = report["deliverable_meshes"]
    return {
        "output_mode": report["output_mode"],
        "timings": report["timings"],
        "detections": len(report["detections"]),
        "source_valid": shapes["source_refined"]["is_valid"],
        "upper_valid": shapes["prepared_upper_body"]["is_valid"],
        "base_valid": shapes["repaired_base_component"]["is_valid"],
        "final_valid": shapes["final_shape"]["is_valid"] if shapes["final_shape"]["has_shape"] else True,
        "deliverable_count": len(report["deliverables"]),
        "deliverable_meshes": deliverable_meshes,
        "base_hole_face_count": metrics["base_hole_face_count"],
        "expected_hole_count": metrics["expected_hole_count"],
        "prepared_upper_band_volume": metrics["prepared_upper_band_volume"],
        "base_lower_band_volume": metrics["base_lower_band_volume"],
        "final_lower_band_volume": metrics["final_lower_band_volume"],
        "export_exists": report["export"]["exists"],
        "export_size": report["export"]["size"],
        "export_mesh": report.get("export_mesh"),
    }


def _validate_case(case_name, report, baseline_entry=None):
    shapes = _shape_map(report)
    metrics = report["metrics"]
    failures = []
    output_mode = report["output_mode"]
    deliverable_meshes = report["deliverable_meshes"]
    deliverable_labels = {mesh_info["label"] for mesh_info in deliverable_meshes}

    if not shapes["source_refined"]["is_valid"]:
        failures.append("source_refined is invalid")
    if not shapes["prepared_upper_body"]["is_valid"]:
        failures.append("prepared_upper_body is invalid")
    if not shapes["repaired_base_component"]["is_valid"]:
        failures.append("repaired_base_component is invalid")
    if (shapes["repaired_base_component"]["volume"] or 0.0) <= 1e-3:
        failures.append("repaired_base_component is empty")
    if metrics["prepared_upper_band_volume"] <= 1e-3:
        failures.append("prepared_upper_body upper band is empty")
    if metrics["base_lower_band_volume"] <= 1e-3:
        failures.append("repaired_base_component lower band is empty")
    if metrics["base_hole_face_count"] < metrics["expected_hole_count"]:
        failures.append("repaired_base_component hole count regression")
    if output_mode == "merge":
        if not shapes["final_shape"]["has_shape"] or not shapes["final_shape"]["is_valid"]:
            failures.append("merged final shape is invalid")
        if metrics["final_lower_band_volume"] <= 1e-3:
            failures.append("merged final lower band is empty")
        if len(report["deliverables"]) != 1:
            failures.append("merge mode should expose exactly one deliverable")
        if not report["export"]["exists"] or report["export"]["size"] <= 0:
            failures.append("merge export was not produced")
        for mesh_info in deliverable_meshes:
            if not mesh_info["is_solid"]:
                failures.append(f"merged export mesh {mesh_info['label']} is not closed")
            if mesh_info["has_non_manifolds"]:
                failures.append(f"merged export mesh {mesh_info['label']} has non-manifold edges")
    else:
        required_labels = {"Outer Shell", "Top Surface", "Remainder", "Repaired Base Component"}
        missing_labels = sorted(required_labels - deliverable_labels)
        if missing_labels:
            failures.append(f"assembly mode is missing required deliverables: {', '.join(missing_labels)}")
        if not report["export"]["exists"] or report["export"]["size"] <= 0:
            failures.append("assembly export was not produced")
        for mesh_info in deliverable_meshes:
            if not mesh_info["is_solid"]:
                failures.append(f"deliverable mesh {mesh_info['label']} is not closed")
            if mesh_info["has_non_manifolds"]:
                failures.append(f"deliverable mesh {mesh_info['label']} has non-manifold edges")

    export_mesh = report.get("export_mesh")
    if export_mesh is not None:
        if not export_mesh["is_solid"]:
            failures.append("written export mesh is not closed")
        if export_mesh["has_non_manifolds"]:
            failures.append("written export mesh has non-manifold edges")

    if baseline_entry:
        if len(report["detections"]) != baseline_entry["detections"]:
            failures.append("detection count changed from baseline")
        if len(report["deliverables"]) != baseline_entry["deliverable_count"]:
            failures.append("deliverable count changed from baseline")
        if not _rel_close(
            metrics["prepared_upper_band_volume"],
            baseline_entry["prepared_upper_band_volume"],
            rel_tol=0.01,
            abs_tol=0.5,
        ):
            failures.append("prepared_upper_body volume drifted from baseline")
        if not _rel_close(
            metrics["base_lower_band_volume"],
            baseline_entry["base_lower_band_volume"],
            rel_tol=0.01,
            abs_tol=0.5,
        ):
            failures.append("repaired_base_component volume drifted from baseline")
        if metrics["base_hole_face_count"] != baseline_entry["base_hole_face_count"]:
            failures.append("base hole face count changed from baseline")

    return failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    selected = set(args.case)
    output_dir = args.output or os.path.expanduser("~/.cache/GridfinityMagnetFix/benchmarks")
    os.makedirs(output_dir, exist_ok=True)

    baseline = _load_baseline()
    results = {}
    failures = {}
    for case_name, filename, subdividers_enabled, output_mode in BENCHMARK_CASES:
        if selected and case_name not in selected:
            continue
        print(
            f"[case] {case_name} ({filename}) mode={output_mode}",
            file=sys.stderr,
            flush=True,
        )
        stl_path = os.path.join(REPO_ROOT, filename)
        case_output = os.path.join(output_dir, case_name)
        os.makedirs(case_output, exist_ok=True)
        report = run_case(
            stl_path,
            subdividers_enabled=subdividers_enabled,
            output_mode=output_mode,
            export_shapes=False,
            output_dir=case_output,
            export_result_file=True,
        )
        results[case_name] = report
        case_failures = _validate_case(case_name, report, baseline.get(case_name))
        if case_failures:
            failures[case_name] = case_failures

    rendered = {
        "results": {name: _summarize_case(report) for name, report in results.items()},
        "failures": failures,
    }
    print(json.dumps(rendered, indent=2, sort_keys=True))

    if args.update_baseline:
        with open(BASELINE_PATH, "w", encoding="utf-8") as handle:
            json.dump({name: _summarize_case(report) for name, report in results.items()}, handle, indent=2, sort_keys=True)
            handle.write("\n")

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
