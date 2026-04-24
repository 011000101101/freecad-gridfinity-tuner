"""FreeCAD GUI command registration."""

from __future__ import annotations

from .mesh_prep import prepare_selected_mesh
from .task_panel import GridfinityMagnetFixTaskPanel
from .ui_utils import selected_document_object, workbench_icon_path

try:
    import FreeCAD as App
    import FreeCADGui as Gui
    from PySide import QtGui
except ImportError:  # pragma: no cover - only available inside FreeCAD
    App = None
    Gui = None
    QtGui = None


COMMAND_NAME = "Gridfinity_Magnet_Fix"
MESH_PREP_COMMAND_NAME = "Gridfinity_Mesh_To_Refined_Solid"
_ACTIVE_PANEL = None


class GridfinityMagnetFixCommand:
    def GetResources(self):
        return {
            "MenuText": "Repair Gridfinity Magnet Holes",
            "ToolTip": "Detect bottom landings, fill legacy features, and cut OG Gridfinity magnet holes.",
            "Pixmap": workbench_icon_path(),
        }

    def Activated(self):
        show_context_panel()

    def IsActive(self):
        return Gui.ActiveDocument is not None


class GridfinityMeshPrepCommand:
    def GetResources(self):
        return {
            "MenuText": "Prepare Mesh As Refined Solid",
            "ToolTip": (
                "Convert a selected mesh into a shape, solid, and refined solid using native Part workflow."
            ),
            "Pixmap": workbench_icon_path(),
        }

    def Activated(self):
        try:
            result = prepare_selected_mesh()
        except RuntimeError as exc:
            _show_warning(str(exc))
            return
        _show_info(
            "Prepared mesh as refined solid.\n"
            f"Result: {result.Label}"
        )

    def IsActive(self):
        return Gui.ActiveDocument is not None


def ensure_registered():
    if Gui is None:  # pragma: no cover
        return
    if COMMAND_NAME not in Gui.listCommands():
        Gui.addCommand(COMMAND_NAME, GridfinityMagnetFixCommand())
    if MESH_PREP_COMMAND_NAME not in Gui.listCommands():
        Gui.addCommand(MESH_PREP_COMMAND_NAME, GridfinityMeshPrepCommand())


def show_context_panel():
    global _ACTIVE_PANEL
    if Gui is None or Gui.ActiveDocument is None:  # pragma: no cover
        return
    source_object = selected_document_object()
    if _ACTIVE_PANEL is not None:
        _ACTIVE_PANEL.source_object = source_object
        _ACTIVE_PANEL.refresh_preview()
        return
    _ACTIVE_PANEL = GridfinityMagnetFixTaskPanel(
        Gui.ActiveDocument.Document,
        source_object,
        close_callback=_clear_active_panel,
    )
    Gui.Control.showDialog(_ACTIVE_PANEL)


def _clear_active_panel():
    global _ACTIVE_PANEL
    _ACTIVE_PANEL = None


def _show_warning(message: str):
    if QtGui is not None:
        QtGui.QMessageBox.warning(None, "Gridfinity Magnet Fix", message)
    elif App is not None:  # pragma: no cover - fallback
        App.Console.PrintError(f"{message}\n")


def _show_info(message: str):
    if QtGui is not None:
        QtGui.QMessageBox.information(None, "Gridfinity Magnet Fix", message)
    elif App is not None:  # pragma: no cover - fallback
        App.Console.PrintMessage(f"{message}\n")
