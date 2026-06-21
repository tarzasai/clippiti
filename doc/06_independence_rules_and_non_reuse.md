# Independence Rules and Non-Reuse List

## Independence requirements
Clippiti Player must be standalone and unrelated to StreamKeeper and StreamCondor at runtime.

## Hard rules
- No imports from `streamkeeper.*` package in final codebase.
- No reads/writes to StreamKeeper config files.
- No SC config/state watcher integration.
- No webcast subsystem.
- No shared runtime directories with StreamKeeper.

## Components to exclude
- `services/webcast_server.py`
- `services/sc_sync.py`
- `services/sc_watcher.py`
- SC-related fields from config model:
  - allow/ignore filters
  - auto-activate linked to SC state
  - SC config path
- multi-stream table and grouped type view in `ui/streams_tab.py`
- centralized stream list CRUD as primary UI

## Components to redesign (not direct copy)
- `app.py` main window with tab layout
- `streams_controller.py` multi-stream API
- runtime orchestrator URL->ID map

## New boundaries
- distribution name example: `clippiti-player`
- package namespace example: `clippiti.*`
- config filename example: `ClippitiPlayer.yaml`
- runtime dir example: `/tmp/clippiti/<session_id>`
- clip dir example: `~/Videos/Clippiti/clips`
- recording dir example: `~/Videos/Clippiti/recordings`

## Licensing and attribution note
If code is copied from StreamKeeper into a new repository, preserve license headers and attribution according to the original project license and your distribution policy.

## Practical extraction method
- copy selected modules as starting point
- immediately rename package imports to `clippiti.*`
- add tests in new repo before large refactors
- remove unrelated branches/features early to avoid accidental coupling
