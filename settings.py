"""Settings and shared constants."""

from __future__ import annotations

from dataclasses import dataclass, field

try:
    import FreeCAD as App
except ImportError:  # pragma: no cover - only available inside FreeCAD
    App = None


# Source:
# Gridfinity design reference and supplemental drawings identify a 41.5 mm
# outer 1x1 footprint, a 35.6 mm standard bottom landing, and a 37.2 mm
# fallback landing when the lower 0.8 mm chamfer is absent.
# https://gridfinity.xyz/specification/
# https://gridfinity.xyz/assets/img/spec_draft_willtree8.jpg
# https://raw.githubusercontent.com/Stu142/Gridfinity-Documentation/main/drawing_svg/bin_bottom_profile.svg
NOMINAL_GRID_INTERVAL = 42.0
HALF_GRID_INTERVAL = NOMINAL_GRID_INTERVAL / 2.0
LOWER_REBUILD_HEIGHT = 5.0
STANDARD_LANDING_LONG = 35.6
STANDARD_LANDING_SHORT = 15.6
NO_LOWER_CHAMFER_LONG = 37.2
NO_LOWER_CHAMFER_SHORT = 17.2
MAGNET_HOLE_PITCH = 26.0
BASE_PROFILE_LOWER_SLOPE = 0.8
BASE_PROFILE_VERTICAL = 1.8
BASE_PROFILE_UPPER_SLOPE = 2.4
BASE_PROFILE_HEIGHT = LOWER_REBUILD_HEIGHT
BASE_PROFILE_BOTTOM_RADIUS = 0.8
BASE_PROFILE_WALL_RADIUS = 1.6
BASE_PROFILE_TOP_RADIUS = 4.0
PARAM_ROOT = "User parameter:BaseApp/Preferences/Mod/GridfinityMagnetFix"


@dataclass(slots=True)
class DetectionSettings:
    size_tolerance: float = 0.1
    z_tolerance: float = 0.05
    axis_angle_tolerance_deg: float = 6.0
    axis_length_ratio_min: float = 0.72
    allow_mixed_profiles: bool = False


@dataclass(slots=True)
class OperationSettings:
    hole_diameter: float = 6.15
    hole_depth: float = 2.2
    hole_pitch: float = MAGNET_HOLE_PITCH
    subdividers_enabled: bool = False
    chamfer_enabled: bool = True
    chamfer_size: float = 0.5
    result_label: str = "Gridfinity Magnet Fix"
    keep_intermediates_visible: bool = False


@dataclass(slots=True)
class Settings:
    detection: DetectionSettings = field(default_factory=DetectionSettings)
    operation: OperationSettings = field(default_factory=OperationSettings)


def factory_settings() -> Settings:
    return Settings()


def load_default_settings() -> Settings:
    defaults = factory_settings()
    if App is None:  # pragma: no cover
        return defaults

    params = App.ParamGet(PARAM_ROOT)
    detection = DetectionSettings(
        size_tolerance=params.GetFloat("size_tolerance", defaults.detection.size_tolerance),
        z_tolerance=params.GetFloat("z_tolerance", defaults.detection.z_tolerance),
        axis_angle_tolerance_deg=params.GetFloat(
            "axis_angle_tolerance_deg",
            defaults.detection.axis_angle_tolerance_deg,
        ),
        axis_length_ratio_min=params.GetFloat(
            "axis_length_ratio_min",
            defaults.detection.axis_length_ratio_min,
        ),
        allow_mixed_profiles=params.GetBool(
            "allow_mixed_profiles",
            defaults.detection.allow_mixed_profiles,
        ),
    )
    operation = OperationSettings(
        hole_diameter=params.GetFloat("hole_diameter", defaults.operation.hole_diameter),
        hole_depth=params.GetFloat("hole_depth", defaults.operation.hole_depth),
        hole_pitch=params.GetFloat("hole_pitch", defaults.operation.hole_pitch),
        subdividers_enabled=params.GetBool(
            "subdividers_enabled",
            defaults.operation.subdividers_enabled,
        ),
        chamfer_enabled=params.GetBool("chamfer_enabled", defaults.operation.chamfer_enabled),
        chamfer_size=params.GetFloat("chamfer_size", defaults.operation.chamfer_size),
        result_label=params.GetString("result_label", defaults.operation.result_label),
        keep_intermediates_visible=params.GetBool(
            "keep_intermediates_visible",
            defaults.operation.keep_intermediates_visible,
        ),
    )
    return Settings(detection=detection, operation=operation)


def save_default_settings(settings: Settings):
    if App is None:  # pragma: no cover
        return

    params = App.ParamGet(PARAM_ROOT)
    params.SetFloat("size_tolerance", settings.detection.size_tolerance)
    params.SetFloat("z_tolerance", settings.detection.z_tolerance)
    params.SetFloat("axis_angle_tolerance_deg", settings.detection.axis_angle_tolerance_deg)
    params.SetFloat("axis_length_ratio_min", settings.detection.axis_length_ratio_min)
    params.SetBool("allow_mixed_profiles", settings.detection.allow_mixed_profiles)
    params.SetFloat("hole_diameter", settings.operation.hole_diameter)
    params.SetFloat("hole_depth", settings.operation.hole_depth)
    params.SetFloat("hole_pitch", settings.operation.hole_pitch)
    params.SetBool("subdividers_enabled", settings.operation.subdividers_enabled)
    params.SetBool("chamfer_enabled", settings.operation.chamfer_enabled)
    params.SetFloat("chamfer_size", settings.operation.chamfer_size)
    params.SetString("result_label", settings.operation.result_label)
    params.SetBool("keep_intermediates_visible", settings.operation.keep_intermediates_visible)


def restore_factory_defaults() -> Settings:
    defaults = factory_settings()
    save_default_settings(defaults)
    return defaults
