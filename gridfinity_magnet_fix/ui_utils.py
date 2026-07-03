"""FreeCAD UI helpers."""

from __future__ import annotations

import os

try:
    import FreeCAD as App
    import FreeCADGui as Gui
except ImportError:  # pragma: no cover - only available inside FreeCAD
    App = None
    Gui = None


ICON_BASENAME = "gridfinity_magnet_fix.xpm"


def workbench_icon_path() -> str:
    if App is None:  # pragma: no cover
        return ""
    return os.path.join(App.getUserAppDataDir(), "Mod", "GridfinityMagnetFix", "resources", ICON_BASENAME)


def selected_document_object():
    if Gui is None:  # pragma: no cover
        return None
    selection_ex = Gui.Selection.getSelectionEx("", 0)
    if selection_ex:
        selection_object = selection_ex[0]
        return getattr(selection_object, "Object", None)
    selection = Gui.Selection.getSelection()
    if selection:
        return selection[0]
    return None


def is_compatible_document_object(obj) -> bool:
    if obj is None:
        return False
    shape = getattr(obj, "Shape", None)
    if shape is not None and getattr(shape, "Solids", None):
        return True
    if hasattr(obj, "Mesh"):
        return True
    return False
