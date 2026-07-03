"""Workbench registration for FreeCAD."""

try:
    import FreeCAD as App
    import FreeCADGui as Gui
except ImportError:  # pragma: no cover - only available inside FreeCAD
    App = None
    Gui = None


if Gui is not None:  # pragma: no branch
    WorkbenchBase = Gui.Workbench
else:  # pragma: no cover - only available inside FreeCAD
    class WorkbenchBase:  # type: ignore[no-redef]
        pass


class GridfinityMagnetFixWorkbench(WorkbenchBase):
    MenuText = "Gridfinity Magnet Fix"
    ToolTip = "Repair Gridfinity bottom faces and generate OG magnet holes."
    Icon = ""

    def GetClassName(self):
        return "Gui::PythonWorkbench"

    def Initialize(self):
        from gridfinity_magnet_fix.commands import (
            COMMAND_NAME,
            MESH_PREP_COMMAND_NAME,
            ensure_registered,
        )

        ensure_registered()
        self.appendToolbar("Gridfinity Magnet Fix", [COMMAND_NAME, MESH_PREP_COMMAND_NAME])
        self.appendMenu("Gridfinity Magnet Fix", [COMMAND_NAME, MESH_PREP_COMMAND_NAME])

    def Activated(self):
        from gridfinity_magnet_fix.commands import activate_context_presenter

        activate_context_presenter()
        return None

    def Deactivated(self):
        from gridfinity_magnet_fix.commands import deactivate_context_presenter

        deactivate_context_presenter()
        return None

try:
    from gridfinity_magnet_fix.ui_utils import workbench_icon_path

    GridfinityMagnetFixWorkbench.Icon = workbench_icon_path()
except Exception:
    GridfinityMagnetFixWorkbench.Icon = ""

if Gui is not None:  # pragma: no cover - only available inside FreeCAD
    Gui.addWorkbench(GridfinityMagnetFixWorkbench())
