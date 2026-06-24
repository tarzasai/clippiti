"""Configuration dialog for editing runtime and startup settings."""

from copy import deepcopy
from importlib.metadata import version, PackageNotFoundError

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
  QCheckBox,
  QComboBox,
  QDialog,
  QDialogButtonBox,
  QFileDialog,
  QFormLayout,
  QHBoxLayout,
  QLabel,
  QLineEdit,
  QPlainTextEdit,
  QPushButton,
  QSpinBox,
  QTabWidget,
  QVBoxLayout,
  QWidget,
)
import yaml

from ..model.config import normalize_config

# Determine version: prefer installed distribution metadata, fallback to package __version__
try:
  dist_ver = version('clippiti')
except PackageNotFoundError:
  import clippiti
  dist_ver = getattr(clippiti, '__version__', 'dev')


class SettingsDialog(QDialog):
  TOOLBAR_POSITION_OPTIONS: list[tuple[str, str]] = [
    ("top-right-horizontal", "Top-right, horizontal"),
    ("top-right-vertical", "Top-right, vertical"),
    ("bottom-right-horizontal", "Bottom-right, horizontal"),
    ("bottom-right-vertical", "Bottom-right, vertical"),
    ("bottom-left-vertical", "Bottom-left, vertical"),
    ("bottom-left-horizontal", "Bottom-left, horizontal"),
    ("top-left-horizontal", "Top-left, horizontal"),
    ("top-left-vertical", "Top-left, vertical"),
  ]

  def __init__(self, config: dict[str, object], parent=None) -> None:
    super().__init__(parent)
    self.setWindowTitle("Settings")
    self.setMinimumWidth(760)
    self.resize(self.minimumWidth(), 640)

    self._source = normalize_config(deepcopy(config))

    tabs = QTabWidget(self)
    tabs.addTab(self._build_general_tab(), "General")
    tabs.addTab(self._build_actions_tab(), "Actions")
    tabs.addTab(self._build_about_tab(), "About")

    restart_hint = QLabel("(*) requires relaunch")
    restart_hint.setWordWrap(False)

    buttons = QDialogButtonBox(
      QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.setContentsMargins(0, 0, 0, 0)
    buttons.setMinimumHeight(32)
    buttons.setFixedHeight(32)
    for button in buttons.buttons():
      button.setMinimumHeight(32)
      button.setFixedHeight(32)
    buttons.accepted.connect(self.accept)
    buttons.rejected.connect(self.reject)

    footer_layout = QHBoxLayout()
    footer_layout.setContentsMargins(0, 0, 0, 0)
    footer_layout.setSpacing(8)
    footer_layout.addWidget(restart_hint)
    footer_layout.addStretch(1)
    footer_layout.addWidget(buttons)

    layout = QVBoxLayout(self)
    layout.setSpacing(12)
    layout.addWidget(tabs)
    layout.addLayout(footer_layout)

  def updated_config(self) -> dict[str, object]:
    general = self._source["general"]
    recording = self._source["recording"]
    clip = self._source["clip"]
    snapshot = self._source["snapshot"]
    streamlink = self._source["streamlink"]

    general["ffmpeg_path"] = self._ffmpeg_path_input.text().strip() or "ffmpeg"
    general["controls_area"] = int(self._controls_area_input.value())
    general["controls_resize_debounce_ms"] = int(self._resize_debounce_input.value())
    general["controls_position"] = str(self._controls_position_input.currentData())
    general["segment_seconds"] = int(self._segment_seconds_input.value())
    general["window_segments"] = int(self._window_segments_input.value())

    streamlink["default_args"] = self._streamlink_default_args_input.toPlainText().strip()

    mpv_options_text = self._mpv_options_input.toPlainText().strip()
    if not mpv_options_text:
      general["mpv_options"] = {}
    else:
      loaded = yaml.safe_load(mpv_options_text)
      if not isinstance(loaded, dict):
        raise ValueError("mpv_options must be a YAML mapping")
      general["mpv_options"] = loaded

    recording["dir"] = self._recording_dir_input.text().strip() or str(recording.get("dir", ""))
    recording["filename_format"] = self._recording_filename_input.text().strip() or "{author}.{timestamp}"
    recording["auto_remux_to_mp4"] = self._recording_remux_input.isChecked()

    clip["dir"] = self._clip_dir_input.text().strip() or str(clip.get("dir", ""))
    clip["default_duration"] = int(self._clip_duration_input.value())
    clip["filename_format"] = self._clip_filename_input.text().strip() or "{author}.{timestamp}"

    snapshot["dir"] = self._snapshot_dir_input.text().strip() or str(snapshot.get("dir", ""))
    snapshot["filename_format"] = self._snapshot_filename_input.text().strip() or "{author}.{timestamp}"

    return normalize_config(self._source)

  def _build_general_tab(self) -> QWidget:
    tab = QWidget(self)
    layout = QFormLayout(tab)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(8)

    general = self._source["general"]
    streamlink = self._source["streamlink"]

    self._controls_position_input = QComboBox(tab)
    for value, label in self.TOOLBAR_POSITION_OPTIONS:
      self._controls_position_input.addItem(label, value)
    current_position = str(general.get("controls_position", "bottom-right-vertical"))
    current_index = self._controls_position_input.findData(current_position)
    self._controls_position_input.setCurrentIndex(max(0, current_index))
    controls_position_row = self._build_inline_hint_row(
      self._controls_position_input,
      "Default toolbar corner and orientation",
      tab,
    )

    self._controls_area_input = QSpinBox(tab)
    self._controls_area_input.setRange(50, 2000)
    self._controls_area_input.setValue(int(general.get("controls_area", 300)))
    controls_area_row = self._build_inline_hint_row(
      self._controls_area_input,
      "Distance (in px) from the corner to open the toolbar",
      tab,
    )

    self._resize_debounce_input = QSpinBox(tab)
    self._resize_debounce_input.setRange(0, 2000)
    self._resize_debounce_input.setValue(int(general.get("controls_resize_debounce_ms", 40)))
    resize_debounce_row = self._build_inline_hint_row(
      self._resize_debounce_input,
      "Delay before video reposition on window resize to avoid stutter",
      tab,
    )

    self._segment_seconds_input = QSpinBox(tab)
    self._segment_seconds_input.setRange(1, 120)
    self._segment_seconds_input.setValue(int(general.get("segment_seconds", 5)))
    segment_seconds_row = self._build_inline_hint_row(
      self._segment_seconds_input,
      "Length of each HLS chunk",
      tab,
    )

    self._window_segments_input = QSpinBox(tab)
    self._window_segments_input.setRange(2, 120)
    self._window_segments_input.setValue(int(general.get("window_segments", 12)))
    window_segments_row = self._build_inline_hint_row(
      self._window_segments_input,
      "How many chunks are kept in rolling buffer",
      tab,
    )

    self._ffmpeg_path_input = QLineEdit(str(general.get("ffmpeg_path", "ffmpeg")), tab)

    self._streamlink_default_args_input = QPlainTextEdit(tab)
    self._streamlink_default_args_input.setPlainText(str(streamlink.get("default_args", "")))
    streamlink_height = self._streamlink_default_args_input.fontMetrics().height() * 3 + 16
    self._streamlink_default_args_input.setMinimumHeight(streamlink_height)

    self._mpv_options_input = QPlainTextEdit(tab)
    mpv_options = general.get("mpv_options", {})
    if isinstance(mpv_options, dict) and mpv_options:
      self._mpv_options_input.setPlainText(yaml.safe_dump(mpv_options, sort_keys=True).strip())
    else:
      self._mpv_options_input.setPlainText("")
    self._mpv_options_input.setPlaceholderText(
      "hwdec: auto\nvideo_sync: audio\ninterpolation: true"
    )

    sl_hint = QLabel(
      '<span style="margin:0; padding:0;">'
      'Command-line arguments passed to streamlink. '
      '<a href="https://streamlink.github.io/cli.html">online docs</a>'
      '</span>',
      tab,
    )
    sl_hint.setOpenExternalLinks(True)
    sl_hint.setWordWrap(False)
    sl_hint.setMargin(0)
    sl_hint.setIndent(0)
    sl_hint.setContentsMargins(0, 0, 0, 0)

    yaml_hint = QLabel(
      '<span style="margin:0; padding:0;">'
      'YAML mapping of mpv options. '
      '<a href="https://mpv.io/manual/master/#options">online docs</a>'
      '</span>',
      tab,
    )
    yaml_hint.setOpenExternalLinks(True)
    yaml_hint.setWordWrap(False)
    yaml_hint.setMargin(0)
    yaml_hint.setIndent(0)
    yaml_hint.setContentsMargins(0, 0, 0, 0)

    layout.addRow("", self._build_section_label("Interface", tab))
    layout.addRow("default toolbar pos.", controls_position_row)
    layout.addRow("toolbar trigger area", controls_area_row)
    layout.addRow("resize debounce (ms)", resize_debounce_row)
    layout.addRow("", self._build_section_label("Pipeline & Player (*)", tab))
    layout.addRow(
      "ffmpeg executable",
      self._build_file_row(self._ffmpeg_path_input, "Select ffmpeg executable", "Browse..."),
    )
    layout.addRow("segment seconds (*)", segment_seconds_row)
    layout.addRow("window segments (*)", window_segments_row)
    layout.addRow("streamlink args (*)", self._streamlink_default_args_input)
    layout.addRow("", sl_hint)
    layout.addRow("mpv options (*)", self._mpv_options_input)
    layout.addRow("", yaml_hint)
    return tab

  def _build_actions_tab(self) -> QWidget:
    tab = QWidget(self)
    layout = QFormLayout(tab)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(8)

    recording = self._source["recording"]
    clip = self._source["clip"]
    snapshot = self._source["snapshot"]

    filename_hint = QLineEdit("{author}, {category}, {title}, {timestamp}", tab)
    filename_hint.setReadOnly(True)
    layout.addRow("Filename variables", filename_hint)

    # Recording
    self._recording_dir_input = QLineEdit(str(recording.get("dir", "")), tab)
    self._recording_filename_input = QLineEdit(
      str(recording.get("filename_format", "{author}.{timestamp}")),
      tab,
    )
    self._recording_remux_input = QCheckBox("Auto remux the .ts file when the recording is finished", tab)
    self._recording_remux_input.setChecked(bool(recording.get("auto_remux_to_mp4", False)))

    layout.addRow("", self._build_section_label("Recording", tab))
    layout.addRow("output dir", self._build_directory_row(self._recording_dir_input, "Select recording output folder"))
    layout.addRow("filename format", self._recording_filename_input)
    layout.addRow("convert to MP4", self._recording_remux_input)

    # Clip
    self._clip_dir_input = QLineEdit(str(clip.get("dir", "")), tab)
    self._clip_duration_input = QSpinBox(tab)
    self._clip_duration_input.setRange(5, 600)
    self._clip_duration_input.setValue(int(clip.get("default_duration", 30)))
    self._clip_filename_input = QLineEdit(
      str(clip.get("filename_format", "{author}.{timestamp}")),
      tab,
    )

    layout.addRow("", self._build_section_label("Clip", tab))
    layout.addRow("output dir", self._build_directory_row(self._clip_dir_input, "Select clip output folder"))
    layout.addRow("filename format", self._clip_filename_input)
    layout.addRow("default duration (s)", self._clip_duration_input)

    # Snapshot
    self._snapshot_dir_input = QLineEdit(str(snapshot.get("dir", "")), tab)
    self._snapshot_filename_input = QLineEdit(
      str(snapshot.get("filename_format", "{author}.{timestamp}")),
      tab,
    )

    layout.addRow("", self._build_section_label("Snapshot", tab))
    layout.addRow("output dir", self._build_directory_row(self._snapshot_dir_input, "Select snapshot output folder"))
    layout.addRow("filename format", self._snapshot_filename_input)
    return tab

  def _build_about_tab(self) -> QWidget:
    widget = QWidget()
    layout = QVBoxLayout()
    layout.addStretch(1)
    title = QLabel('<h1>Clippiti</h1>')
    title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(title)
    description = QLabel('<h4>A livestream player with clipping and recording capabilities.</h4>')
    description.setAlignment(Qt.AlignmentFlag.AlignCenter)
    description.setWordWrap(True)
    layout.addWidget(description)
    version = QLabel(f'<p>Version {dist_ver}</p>')
    version.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(version)
    links = QLabel(
      '<p><a href="https://github.com/tarzasai/Clippiti">GitHub Repository</a></p>'
      '<p><a href="https://github.com/tarzasai/Clippiti/wiki">Documentation</a></p>'
    )
    links.setAlignment(Qt.AlignmentFlag.AlignCenter)
    links.setOpenExternalLinks(True)
    layout.addWidget(links)
    copyright_text = QLabel('<p>© 2026 Tarzasai</p>')
    copyright_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(copyright_text)
    layout.addStretch(2)
    widget.setLayout(layout)
    return widget

  def _build_directory_row(self, line_edit: QLineEdit, title: str) -> QHBoxLayout:
    row_layout = QHBoxLayout()
    row_layout.setContentsMargins(0, 0, 0, 0)
    row_layout.setSpacing(8)
    row_layout.addWidget(line_edit)

    browse = QPushButton("Browse...", self)
    browse.clicked.connect(lambda: self._choose_directory(line_edit, title))
    row_layout.addWidget(browse)
    return row_layout

  def _build_file_row(self, line_edit: QLineEdit, title: str, button_text: str) -> QHBoxLayout:
    row_layout = QHBoxLayout()
    row_layout.setContentsMargins(0, 0, 0, 0)
    row_layout.setSpacing(8)
    row_layout.addWidget(line_edit)

    browse = QPushButton(button_text, self)
    browse.clicked.connect(lambda: self._choose_file(line_edit, title))
    row_layout.addWidget(browse)
    return row_layout

  def _build_inline_hint_row(self, field: QWidget, hint_text: str, parent: QWidget) -> QHBoxLayout:
    hint = QLabel(hint_text, parent)
    hint.setMargin(0)
    hint.setIndent(0)
    hint.setContentsMargins(0, 0, 0, 0)

    row_layout = QHBoxLayout()
    row_layout.setContentsMargins(0, 0, 0, 0)
    row_layout.setSpacing(8)
    row_layout.addWidget(field)
    row_layout.addWidget(hint)
    row_layout.addStretch(1)
    return row_layout

  def _choose_directory(self, line_edit: QLineEdit, title: str) -> None:
    start_dir = line_edit.text().strip() or "~"
    selected = QFileDialog.getExistingDirectory(self, title, start_dir)
    if selected:
      line_edit.setText(selected)

  def _choose_file(self, line_edit: QLineEdit, title: str) -> None:
    start_path = line_edit.text().strip() or "~"
    selected, _ = QFileDialog.getOpenFileName(self, title, start_path)
    if selected:
      line_edit.setText(selected)

  def _build_section_label(self, text: str, parent: QWidget) -> QLabel:
    label = QLabel(text, parent)
    font = label.font()
    font.setPointSizeF(font.pointSizeF() * 1.2)
    label.setFont(font)
    label.setContentsMargins(0, 8, 0, 2)
    return label
