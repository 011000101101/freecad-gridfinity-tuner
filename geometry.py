"""Pure geometry helpers shared by tests and FreeCAD integration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Iterable, Sequence

from .settings import (
    MAGNET_HOLE_PITCH,
    NO_LOWER_CHAMFER_LONG,
    NO_LOWER_CHAMFER_SHORT,
    STANDARD_LANDING_LONG,
    STANDARD_LANDING_SHORT,
)


class ProfileFamily(str, Enum):
    STANDARD = "standard"
    NO_LOWER_CHAMFER = "no_lower_chamfer"


class FootprintKind(str, Enum):
    FULL = "full"
    HALF_X = "half_x"
    HALF_Y = "half_y"
    QUARTER = "quarter"


@dataclass(frozen=True, slots=True)
class TargetFootprint:
    kind: FootprintKind
    family: ProfileFamily
    width: float
    height: float


@dataclass(frozen=True, slots=True)
class FootprintMatch:
    kind: FootprintKind
    family: ProfileFamily
    width: float
    height: float
    expected_width: float
    expected_height: float
    total_error: float


@dataclass(frozen=True, slots=True)
class BBox2D:
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y

    @property
    def center_x(self) -> float:
        return (self.min_x + self.max_x) / 2.0

    @property
    def center_y(self) -> float:
        return (self.min_y + self.max_y) / 2.0


def target_footprints() -> tuple[TargetFootprint, ...]:
    return (
        TargetFootprint(
            FootprintKind.FULL,
            ProfileFamily.STANDARD,
            STANDARD_LANDING_LONG,
            STANDARD_LANDING_LONG,
        ),
        TargetFootprint(
            FootprintKind.HALF_X,
            ProfileFamily.STANDARD,
            STANDARD_LANDING_LONG,
            STANDARD_LANDING_SHORT,
        ),
        TargetFootprint(
            FootprintKind.HALF_Y,
            ProfileFamily.STANDARD,
            STANDARD_LANDING_SHORT,
            STANDARD_LANDING_LONG,
        ),
        TargetFootprint(
            FootprintKind.QUARTER,
            ProfileFamily.STANDARD,
            STANDARD_LANDING_SHORT,
            STANDARD_LANDING_SHORT,
        ),
        TargetFootprint(
            FootprintKind.FULL,
            ProfileFamily.NO_LOWER_CHAMFER,
            NO_LOWER_CHAMFER_LONG,
            NO_LOWER_CHAMFER_LONG,
        ),
        TargetFootprint(
            FootprintKind.HALF_X,
            ProfileFamily.NO_LOWER_CHAMFER,
            NO_LOWER_CHAMFER_LONG,
            NO_LOWER_CHAMFER_SHORT,
        ),
        TargetFootprint(
            FootprintKind.HALF_Y,
            ProfileFamily.NO_LOWER_CHAMFER,
            NO_LOWER_CHAMFER_SHORT,
            NO_LOWER_CHAMFER_LONG,
        ),
        TargetFootprint(
            FootprintKind.QUARTER,
            ProfileFamily.NO_LOWER_CHAMFER,
            NO_LOWER_CHAMFER_SHORT,
            NO_LOWER_CHAMFER_SHORT,
        ),
    )


def classify_bbox(width: float, height: float, tolerance: float) -> FootprintMatch | None:
    best_match: FootprintMatch | None = None
    for target in target_footprints():
        width_error = abs(width - target.width)
        height_error = abs(height - target.height)
        if width_error > tolerance or height_error > tolerance:
            continue
        match = FootprintMatch(
            kind=target.kind,
            family=target.family,
            width=width,
            height=height,
            expected_width=target.width,
            expected_height=target.height,
            total_error=width_error + height_error,
        )
        if best_match is None or match.total_error < best_match.total_error:
            best_match = match
    return best_match


def hole_centers(
    bbox: BBox2D,
    kind: FootprintKind,
    hole_pitch: float = MAGNET_HOLE_PITCH,
) -> tuple[tuple[float, float], ...]:
    half_pitch = hole_pitch / 2.0
    cx = bbox.center_x
    cy = bbox.center_y
    if kind == FootprintKind.FULL:
        return (
            _rounded_point(cx - half_pitch, cy - half_pitch),
            _rounded_point(cx + half_pitch, cy + half_pitch),
            _rounded_point(cx - half_pitch, cy + half_pitch),
            _rounded_point(cx + half_pitch, cy - half_pitch),
        )
    if kind == FootprintKind.HALF_X:
        return (
            _rounded_point(cx - half_pitch, cy),
            _rounded_point(cx + half_pitch, cy),
        )
    if kind == FootprintKind.HALF_Y:
        return (
            _rounded_point(cx, cy - half_pitch),
            _rounded_point(cx, cy + half_pitch),
        )
    if kind == FootprintKind.QUARTER:
        return (_rounded_point(cx, cy),)
    raise ValueError(f"Unsupported footprint kind: {kind}")


def edge_axis_aligned_length(
    start: tuple[float, float],
    end: tuple[float, float],
    angle_tolerance_deg: float,
) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        return 0.0
    angle = abs(math.degrees(math.atan2(dy, dx))) % 180.0
    deviations = (
        abs(angle - 0.0),
        abs(angle - 90.0),
        abs(angle - 180.0),
    )
    if min(deviations) <= angle_tolerance_deg:
        return length
    return 0.0


def axis_aligned_ratio(
    points: Sequence[tuple[float, float]],
    angle_tolerance_deg: float,
) -> float:
    if len(points) < 2:
        return 0.0
    total = 0.0
    aligned = 0.0
    for start, end in zip(points, points[1:]):
        segment_length = math.hypot(end[0] - start[0], end[1] - start[1])
        total += segment_length
        aligned += edge_axis_aligned_length(start, end, angle_tolerance_deg)
    if total <= 1e-9:
        return 0.0
    return aligned / total


def bbox_from_points(points: Iterable[tuple[float, float]]) -> BBox2D:
    points = tuple(points)
    if not points:
        raise ValueError("Cannot compute a bounding box from no points")
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return BBox2D(min(xs), min(ys), max(xs), max(ys))


def points_within_bbox(points: Iterable[tuple[float, float]], bbox: BBox2D, tolerance: float) -> bool:
    for x, y in points:
        if x < bbox.min_x - tolerance or x > bbox.max_x + tolerance:
            return False
        if y < bbox.min_y - tolerance or y > bbox.max_y + tolerance:
            return False
    return True


def _rounded_point(x: float, y: float) -> tuple[float, float]:
    return (round(x, 6), round(y, 6))
