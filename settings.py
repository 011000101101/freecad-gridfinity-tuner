"""Settings and shared constants."""

from __future__ import annotations

from dataclasses import dataclass, field


# Source:
# Gridfinity design reference and supplemental drawings identify a 41.5 mm
# outer 1x1 footprint, a 35.6 mm standard bottom landing, and a 37.2 mm
# fallback landing when the lower 0.8 mm chamfer is absent.
# https://gridfinity.xyz/specification/
# https://gridfinity.xyz/assets/img/spec_draft_willtree8.jpg
# https://raw.githubusercontent.com/Stu142/Gridfinity-Documentation/main/drawing_svg/bin_bottom_profile.svg
STANDARD_LANDING_LONG = 35.6
STANDARD_LANDING_SHORT = 15.6
NO_LOWER_CHAMFER_LONG = 37.2
NO_LOWER_CHAMFER_SHORT = 17.2
MAGNET_HOLE_PITCH = 26.0


@dataclass(slots=True)
class DetectionSettings:
    size_tolerance: float = 0.1
    z_tolerance: float = 0.05
    axis_angle_tolerance_deg: float = 6.0
    axis_length_ratio_min: float = 0.72
    allow_mixed_profiles: bool = False


@dataclass(slots=True)
class OperationSettings:
    fill_height: float = 3.0
    hole_diameter: float = 6.15
    hole_depth: float = 2.2
    hole_pitch: float = MAGNET_HOLE_PITCH
    chamfer_enabled: bool = True
    chamfer_size: float = 0.5
    result_label: str = "Gridfinity Magnet Fix"
    keep_intermediates_visible: bool = False


@dataclass(slots=True)
class Settings:
    detection: DetectionSettings = field(default_factory=DetectionSettings)
    operation: OperationSettings = field(default_factory=OperationSettings)
