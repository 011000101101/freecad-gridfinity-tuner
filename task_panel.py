"""Task panel UI."""

from __future__ import annotations

from .detect import DetectionError, detect_footprints
from .mesh_prep import prepare_selected_mesh
from .ops import OperationError, execute, summarize_detections
from .preview import clear_preview, update_preview
from .settings import (
    DetectionSettings,
    OperationSettings,
    Settings,
    load_default_settings,
    restore_factory_defaults,
    save_default_settings,
)
from .ui_utils import selected_document_object

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui
except ImportError:  # pragma: no cover - only available inside FreeCAD
    Gui = None
    QtCore = None
    QtGui = None


class GridfinityMagnetFixTaskPanel:
    def __init__(self, doc, source_object, close_callback=None):
        self.doc = doc
        self.source_object = source_object
        self.close_callback = close_callback
        self.form = self._build_form()
        self.form.setWindowTitle("Gridfinity Magnet Fix")
        self._apply_settings(load_default_settings())
        self._wire_signals()
        if Gui is not None:
            Gui.Selection.addObserver(self)
        self._sync_selected_object()
        self.refresh_preview()

    def getStandardButtons(self):
        return QtGui.QDialogButtonBox.Close

    def accept(self):
        return True

    def reject(self):
        if Gui is not None:
            Gui.Selection.removeObserver(self)
        clear_preview(self.doc)
        if self.close_callback is not None:
            self.close_callback()
        return True

    def clicked(self, button):
        return None

    def gather_settings(self) -> Settings:
        detection = DetectionSettings(
            size_tolerance=self.size_tolerance.value(),
            z_tolerance=self.z_tolerance.value(),
            axis_angle_tolerance_deg=self.axis_angle_tolerance.value(),
            axis_length_ratio_min=self.axis_ratio_min.value(),
            allow_mixed_profiles=self.allow_mixed_profiles.isChecked(),
        )
        operation = OperationSettings(
            hole_diameter=self.hole_diameter.value(),
            hole_depth=self.hole_depth.value(),
            hole_pitch=self.hole_pitch.value(),
            subdividers_enabled=self.subdividers_enabled.isChecked(),
            chamfer_enabled=self.chamfer_enabled.isChecked(),
            chamfer_size=self.chamfer_size.value(),
            keep_intermediates_visible=self.keep_intermediates.isChecked(),
        )
        return Settings(detection=detection, operation=operation)

    def refresh_preview(self):
        self._sync_selected_object()
        if self.source_object is None:
            clear_preview(self.doc)
            self.object_name.setText("No selection")
            self.selection_hint.setText("Select a mesh or a solid, or any of their subelements.")
            self._set_mesh_controls_visible(False)
            self._set_solid_controls_visible(False)
            self.summary.setPlainText(
                "Select one mesh object to prepare it into a refined solid, or select one solid "
                "or any face/edge/vertex belonging to a solid to repair it."
            )
            return
        self.object_name.setText(self.source_object.Label)
        mode = self._current_mode()
        if mode == "mesh":
            clear_preview(self.doc)
            self.selection_hint.setText(
                "Mesh selected. The available task is to prepare it as a refined solid."
            )
            self._set_mesh_controls_visible(True)
            self._set_solid_controls_visible(False)
            self.summary.setPlainText(
                "Selected object is a mesh.\n"
                "Available category: Mesh Preparation.\n"
                "Run Shape from mesh -> Convert to solid -> Refine shape.\n"
                "The panel will remain open and switch to repair mode on the resulting solid."
            )
            return
        if mode != "solid":
            clear_preview(self.doc)
            self.selection_hint.setText("Selected object is not supported.")
            self._set_mesh_controls_visible(False)
            self._set_solid_controls_visible(False)
            self.summary.setPlainText(
                "Selected object is neither a mesh nor a solid shape supported by this tool."
            )
            return
        self.selection_hint.setText(
            "Solid selected. The available task is to repair Gridfinity magnet holes."
        )
        self._set_mesh_controls_visible(False)
        self._set_solid_controls_visible(True)
        settings = self.gather_settings()
        try:
            detections = detect_footprints(self.source_object.Shape, settings.detection)
        except DetectionError as exc:
            clear_preview(self.doc)
            self.summary.setPlainText(str(exc))
            return

        self.summary.setPlainText(summarize_detections(detections))
        if self.preview_enabled.isChecked():
            update_preview(self.doc, detections, settings)
        else:
            clear_preview(self.doc)

    def _build_form(self):
        widget = QtGui.QWidget()
        layout = QtGui.QVBoxLayout(widget)

        intro = QtGui.QLabel("Gridfinity Magnet Fix")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.object_group = QtGui.QGroupBox("Selection")
        object_layout = QtGui.QVBoxLayout(self.object_group)

        self.object_name = QtGui.QLabel("")
        self.object_name.setWordWrap(True)
        object_layout.addWidget(self.object_name)

        self.selection_hint = QtGui.QLabel("")
        self.selection_hint.setWordWrap(True)
        object_layout.addWidget(self.selection_hint)
        layout.addWidget(self.object_group)

        self.mesh_group = QtGui.QGroupBox("Mesh Preparation")
        mesh_layout = QtGui.QVBoxLayout(self.mesh_group)
        self.mesh_description = QtGui.QLabel(
            "Prepare the selected mesh using the native Part workflow:\n"
            "Shape from mesh -> Convert to solid -> Refine shape."
        )
        self.mesh_description.setWordWrap(True)
        mesh_layout.addWidget(self.mesh_description)
        self.mesh_button = QtGui.QPushButton("Prepare Selected Mesh")
        self.mesh_button.clicked.connect(self._run_mesh_prep)
        mesh_layout.addWidget(self.mesh_button)
        layout.addWidget(self.mesh_group)

        self.solid_controls = QtGui.QWidget()
        solid_layout = QtGui.QVBoxLayout(self.solid_controls)
        solid_layout.setContentsMargins(0, 0, 0, 0)

        self.solid_group = QtGui.QGroupBox("Gridfinity Repair")
        group_layout = QtGui.QVBoxLayout(self.solid_group)
        self.solid_description = QtGui.QLabel(
            "Detect bottom landings on the selected solid's lowest Z plane, "
            "rebuild the lower 5 mm from nominal Gridfinity cell geometry, "
            "optionally add subdividers, and cut OG-style magnet holes."
        )
        self.solid_description.setWordWrap(True)
        group_layout.addWidget(self.solid_description)

        form = QtGui.QFormLayout()
        group_layout.addLayout(form)

        self.size_tolerance = self._double_spin(0.0, 2.0, 0.1, 2)
        self.z_tolerance = self._double_spin(0.0, 1.0, 0.05, 3)
        self.axis_angle_tolerance = self._double_spin(0.0, 45.0, 6.0, 1)
        self.axis_ratio_min = self._double_spin(0.0, 1.0, 0.72, 2)
        self.hole_diameter = self._double_spin(0.1, 20.0, 6.15, 2)
        self.hole_depth = self._double_spin(0.1, 20.0, 2.2, 2)
        self.hole_pitch = self._double_spin(1.0, 50.0, 26.0, 2)
        self.chamfer_size = self._double_spin(0.0, 5.0, 0.5, 2)

        self.allow_mixed_profiles = QtGui.QCheckBox()
        self.preview_enabled = QtGui.QCheckBox()
        self.preview_enabled.setChecked(True)
        self.subdividers_enabled = QtGui.QCheckBox()
        self.chamfer_enabled = QtGui.QCheckBox()
        self.chamfer_enabled.setChecked(True)
        self.keep_intermediates = QtGui.QCheckBox()

        form.addRow("Size tolerance (mm)", self.size_tolerance)
        form.addRow("Z tolerance (mm)", self.z_tolerance)
        form.addRow("Axis angle tol (deg)", self.axis_angle_tolerance)
        form.addRow("Axis ratio minimum", self.axis_ratio_min)
        form.addRow("Allow mixed profiles", self.allow_mixed_profiles)
        form.addRow("Hole diameter (mm)", self.hole_diameter)
        form.addRow("Hole depth (mm)", self.hole_depth)
        form.addRow("Hole pitch (mm)", self.hole_pitch)
        form.addRow("Add subdividers", self.subdividers_enabled)
        form.addRow("Chamfer underside rim", self.chamfer_enabled)
        form.addRow("Chamfer size (mm)", self.chamfer_size)
        form.addRow("Preview detections", self.preview_enabled)
        form.addRow("Keep intermediates visible", self.keep_intermediates)

        defaults_row = QtGui.QHBoxLayout()
        self.update_defaults_button = QtGui.QPushButton("Update Defaults")
        self.update_defaults_button.clicked.connect(self._update_defaults)
        defaults_row.addWidget(self.update_defaults_button)
        self.restore_defaults_button = QtGui.QPushButton("Restore Defaults")
        self.restore_defaults_button.clicked.connect(self._restore_defaults)
        defaults_row.addWidget(self.restore_defaults_button)
        group_layout.addLayout(defaults_row)

        button_row = QtGui.QHBoxLayout()
        self.refresh_button = QtGui.QPushButton("Refresh Preview")
        self.refresh_button.clicked.connect(self.refresh_preview)
        button_row.addWidget(self.refresh_button)
        self.repair_button = QtGui.QPushButton("Repair Selected Solid")
        self.repair_button.clicked.connect(self._run_repair)
        button_row.addWidget(self.repair_button)
        group_layout.addLayout(button_row)
        solid_layout.addWidget(self.solid_group)
        layout.addWidget(self.solid_controls)

        self.summary = QtGui.QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setMinimumHeight(180)
        layout.addWidget(self.summary)
        return widget

    def _double_spin(self, minimum, maximum, value, decimals):
        widget = QtGui.QDoubleSpinBox()
        widget.setRange(minimum, maximum)
        widget.setDecimals(decimals)
        widget.setValue(value)
        return widget

    def _wire_signals(self):
        widgets = (
            self.size_tolerance,
            self.z_tolerance,
            self.axis_angle_tolerance,
            self.axis_ratio_min,
            self.hole_diameter,
            self.hole_depth,
            self.hole_pitch,
            self.chamfer_size,
        )
        for widget in widgets:
            widget.valueChanged.connect(self.refresh_preview)

        self.allow_mixed_profiles.toggled.connect(self.refresh_preview)
        self.preview_enabled.toggled.connect(self.refresh_preview)
        self.subdividers_enabled.toggled.connect(self.refresh_preview)
        self.chamfer_enabled.toggled.connect(self.refresh_preview)

    def _apply_settings(self, settings: Settings):
        self.size_tolerance.setValue(settings.detection.size_tolerance)
        self.z_tolerance.setValue(settings.detection.z_tolerance)
        self.axis_angle_tolerance.setValue(settings.detection.axis_angle_tolerance_deg)
        self.axis_ratio_min.setValue(settings.detection.axis_length_ratio_min)
        self.allow_mixed_profiles.setChecked(settings.detection.allow_mixed_profiles)
        self.hole_diameter.setValue(settings.operation.hole_diameter)
        self.hole_depth.setValue(settings.operation.hole_depth)
        self.hole_pitch.setValue(settings.operation.hole_pitch)
        self.subdividers_enabled.setChecked(settings.operation.subdividers_enabled)
        self.chamfer_enabled.setChecked(settings.operation.chamfer_enabled)
        self.chamfer_size.setValue(settings.operation.chamfer_size)
        self.keep_intermediates.setChecked(settings.operation.keep_intermediates_visible)

    def _update_defaults(self):
        save_default_settings(self.gather_settings())

    def _restore_defaults(self):
        settings = restore_factory_defaults()
        self._apply_settings(settings)
        self.refresh_preview()

    def addSelection(self, doc_name, object_name, sub_name, point):
        self._sync_selected_object()
        self.refresh_preview()

    def removeSelection(self, doc_name, object_name, sub_name):
        self._sync_selected_object()
        self.refresh_preview()

    def clearSelection(self, doc_name):
        self._sync_selected_object()
        self.refresh_preview()

    def setSelection(self, doc_name):
        self._sync_selected_object()
        self.refresh_preview()

    def _sync_selected_object(self):
        selected_object = selected_document_object()
        if selected_object is not None:
            self.source_object = selected_object

    def _current_mode(self):
        if self.source_object is None:
            return "none"
        shape = getattr(self.source_object, "Shape", None)
        if shape is not None and getattr(shape, "Solids", None):
            return "solid"
        if hasattr(self.source_object, "Mesh"):
            return "mesh"
        return "unsupported"

    def _set_solid_controls_visible(self, visible: bool):
        self.solid_controls.setVisible(visible)

    def _set_mesh_controls_visible(self, visible: bool):
        self.mesh_group.setVisible(visible)

    def _run_mesh_prep(self):
        self._sync_selected_object()
        if self._current_mode() != "mesh":
            QtGui.QMessageBox.warning(
                self.form,
                "Gridfinity Magnet Fix",
                "Select a mesh object or a mesh subelement first.",
            )
            return
        try:
            self.source_object = prepare_selected_mesh(self.source_object)
        except RuntimeError as exc:
            QtGui.QMessageBox.warning(self.form, "Gridfinity Magnet Fix", str(exc))
            return
        self.refresh_preview()

    def _run_repair(self):
        self._sync_selected_object()
        if self._current_mode() != "solid":
            QtGui.QMessageBox.warning(
                self.form,
                "Gridfinity Magnet Fix",
                "Select a solid object or one of its subelements first.",
            )
            return
        try:
            result = execute(self.doc, self.source_object, self.gather_settings())
        except (DetectionError, OperationError) as exc:
            QtGui.QMessageBox.warning(self.form, "Gridfinity Magnet Fix", str(exc))
            return
        if Gui is not None:
            Gui.Selection.removeObserver(self)
        clear_preview(self.doc)
        if self.close_callback is not None:
            self.close_callback()
        Gui.Control.closeDialog()
        if hasattr(result.final_object, "ViewObject"):
            result.final_object.ViewObject.Visibility = True
