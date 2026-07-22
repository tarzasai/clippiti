"""Application context: shared singleton services and mutable session state.

A single ``AppContext`` is created by the composition root (``MainWindow``) and
passed to collaborators that need services or shared state, instead of threading
many individual callables/objects through their constructors.

Live player state (``muted``, ``rotation``) is delegated to the player, which
remains the single source of truth; the context is only the access point.
"""

from dataclasses import dataclass
from typing import Protocol

from .services.buffer import SessionRuntime
from .services.clipper import ClipConfig, ClipService
from .services.recording import AsyncRecordingService, RecordingConfig
from .services.remuxer import RemuxQueueService
from .services.snapshot import SnapshotService


class PlayerControls(Protocol):
  """Structural interface the video surface exposes to the app context.

  ``VideoSurface`` satisfies this without the context depending on the widget.
  """

  muted: bool
  volume: int

  def current_rotation(self) -> int: ...

  def live_lag_seconds(self) -> float | None: ...


@dataclass
class AppContext:
  # Singleton services; the composition root owns their lifetime.
  remux_queue: RemuxQueueService
  recording: AsyncRecordingService
  snapshot: SnapshotService
  player: PlayerControls

  # Config-scoped collaborators, rebuilt when settings change.
  clip_service: ClipService | None = None
  clip_cfg: ClipConfig | None = None
  recording_cfg: RecordingConfig | None = None

  # Session-scoped mutable state (Flask ``g``-like).
  runtime: SessionRuntime | None = None
  recording_rotation: int = 0

  # Live player state, delegated so the player stays the single source of truth.
  @property
  def muted(self) -> bool:
    return self.player.muted

  @muted.setter
  def muted(self, value: bool) -> None:
    self.player.muted = value

  @property
  def rotation(self) -> int:
    return self.player.current_rotation()
