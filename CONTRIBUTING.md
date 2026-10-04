# Contributing to Clippiti

Thank you for considering contributing to Clippiti! This document provides guidelines and instructions for contributing.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How Can I Contribute?](#how-can-i-contribute)
- [Getting Started](#getting-started)
- [Development Process](#development-process)
- [Pull Request Process](#pull-request-process)
- [Coding Standards](#coding-standards)
- [Commit Messages](#commit-messages)
- [Testing Guidelines](#testing-guidelines)
- [Documentation](#documentation)

## Code of Conduct

### Our Pledge

We are committed to providing a welcoming and inclusive environment for everyone, regardless of:
- Age, body size, disability, ethnicity, gender identity and expression
- Level of experience, education, socio-economic status
- Nationality, personal appearance, race, religion
- Sexual identity and orientation

### Our Standards

**Positive Behavior**:
- Using welcoming and inclusive language
- Being respectful of differing viewpoints
- Gracefully accepting constructive criticism
- Focusing on what's best for the community
- Showing empathy towards other community members

**Unacceptable Behavior**:
- Trolling, insulting/derogatory comments, and personal attacks
- Public or private harassment
- Publishing others' private information without permission
- Other conduct which could be considered inappropriate

## How Can I Contribute?

### Reporting Bugs

Before submitting a bug report:
1. Check existing issues to avoid duplicates
2. Gather relevant information (OS, Python version, logs)
3. Create a minimal reproducible example

**Bug Report Template**:
```markdown
**Description**
Clear description of the bug.

**Steps to Reproduce**
1. Step one
2. Step two
3. Step three

**Expected Behavior**
What should happen.

**Actual Behavior**
What actually happens.

**Environment**
- OS: [e.g., Ubuntu 22.04]
- Python: [e.g., 3.12.0]
- Clippiti: [e.g., 1.0.0]
- Streamlink: [e.g., 8.5.0]
- mpv/libmpv: [e.g., 0.38.0]
- FFmpeg: [e.g., 6.1]

**Logs**
```
Paste relevant log output here
```
```

### Suggesting Enhancements

Enhancement suggestions are tracked as GitHub issues. When creating an enhancement suggestion, include:

- **Clear title** describing the enhancement
- **Detailed description** of the proposed functionality
- **Use case** explaining why it would be useful
- **Possible implementation** if you have ideas
- **Alternative solutions** you've considered

**Enhancement Template**:
```markdown
**Enhancement Description**
Clear description of the proposed feature.

**Use Case**
Why would this be useful? Who would benefit?

**Proposed Implementation**
How might this work?

**Alternatives Considered**
Other approaches you've thought about.
```

### Contributing Code

Areas where contributions are especially welcome:

#### High Priority
- 🧪 **Unit Tests** - Test coverage for core services and models
- 🎞️ **Buffer & Clipping** - Rolling buffer robustness, clip accuracy
- 📚 **Documentation** - Guides, examples, troubleshooting
- 🎨 **UI Improvements** - Icons, dark mode, accessibility

#### Medium Priority
- ⚡ **Performance** - Buffer memory/disk footprint, remux throughput
- 🔧 **Features** - Recording formats, clip export options, hotkeys
- 🌍 **Internationalization** - Multi-language support

#### Low Priority
- 🔗 **Integrations** - OBS, webhooks, external editors
- 📦 **Packaging** - Flatpak, AppImage, Snap
- 🚀 **Advanced Features** - Multi-source, analytics

## Getting Started

### Development Setup

1. **Fork the repository** on GitHub

2. **Clone your fork**:
  ```bash
  git clone https://github.com/tarzasai/Clippiti.git
  cd Clippiti
  ```

3. **Add upstream remote**:
  ```bash
  git remote add upstream https://github.com/tarzasai/Clippiti.git
  ```

4. **Set up development environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   ```

5. **Verify setup**:
   ```bash
   ./run_from_source.sh --help
   # Or:
   PYTHONPATH=src python3 -m clippiti --help
   ```

### System Dependencies

Clippiti relies on external media tools that must be available on your system:

- **mpv / libmpv** - playback engine (used via `python-mpv`)
- **FFmpeg** - buffering, clipping, and remuxing

### Development Dependencies

```bash
# Optional: Install additional development tools
pip install black pylint mypy pre-commit
```

## Development Process

### Branching Strategy

```mermaid
gitgraph
   commit id: "main"
   branch feature/new-feature
   checkout feature/new-feature
   commit id: "Add feature"
   commit id: "Tests"
   checkout main
   merge feature/new-feature
   commit id: "Release"
```

**Branch Naming**:
- `feature/description` - New features
- `fix/description` - Bug fixes
- `docs/description` - Documentation
- `refactor/description` - Code refactoring
- `test/description` - Test additions

**Example**:
```bash
git checkout -b feature/clip-export-formats
```

### Keeping Your Fork Updated

```bash
# Fetch upstream changes
git fetch upstream

# Merge into your main branch
git checkout main
git merge upstream/main

# Update your feature branch
git checkout feature/your-feature
git rebase main
```

## Pull Request Process

### Before Submitting

- [ ] Code follows project style guide (see [Coding Standards](#coding-standards))
- [ ] All tests pass
- [ ] New code has appropriate tests
- [ ] Documentation updated if needed
- [ ] Commit messages follow conventions
- [ ] No merge conflicts with main branch

### PR Checklist

1. **Create descriptive title**:
   ```
   [Category] Brief description

   Examples:
   [Feature] Add MKV clip export option
   [Fix] Resolve rolling buffer overflow on long sessions
   [Docs] Add troubleshooting guide
   ```

2. **Fill out PR template**:
   ```markdown
   ## Description
   Brief overview of changes and motivation.

   ## Changes
   - Specific change 1
   - Specific change 2
   - Specific change 3

   ## Testing
   How were these changes tested?

   ## Related Issues
   Fixes #123
   Closes #456

   ## Screenshots (if applicable)

   ## Checklist
   - [ ] Code follows style guide
   - [ ] Tests added/updated
   - [ ] Documentation updated
   - [ ] No breaking changes
   ```

3. **Request review** from maintainers

4. **Address feedback** promptly and professionally

5. **Squash commits** if requested before merge

### Review Process

```mermaid
flowchart TD
    PR[Create PR] --> AutoChecks{CI Checks Pass?}
    AutoChecks -->|No| FixIssues[Fix Issues]
    FixIssues --> PR

    AutoChecks -->|Yes| Review[Maintainer Review]
    Review --> Feedback{Changes Requested?}

    Feedback -->|Yes| MakeChanges[Make Changes]
    MakeChanges --> Review

    Feedback -->|No| Approve[Approved]
    Approve --> Merge[Merge to Main]

    style PR fill:#007bff,color:#fff
    style Approve fill:#28a745,color:#fff
    style Merge fill:#28a745,color:#fff
```

## Coding Standards

### Python Style Guide

Follow **PEP 8** with project-specific conventions:

#### Indentation and Formatting

```python
# Use 2 spaces for indentation
def example_function():
  if condition:
    do_something()
    if nested:
      do_more()

# Maximum line length: 120 characters
very_long_function_name(param1, param2, param3, param4, param5)  # OK if under 120

# For longer lines, use proper wrapping:
result = very_long_function_name(
  first_parameter, second_parameter,
  third_parameter, fourth_parameter
)
```

#### Naming Conventions

```python
# Functions and variables: snake_case
def start_recording(output_path: str) -> bool:
  is_recording = False
  return is_recording

# Classes: PascalCase
class BufferEngine:
  pass

# Constants: UPPER_CASE
MAX_BUFFER_SECONDS = 300
DEFAULT_CLIP_LENGTH = 30

# Private methods: _leading_underscore
def _internal_helper(self) -> None:
  pass
```

#### Type Hints

**Use Python 3.12 native syntax**:

```python
# Good - Native types
def process_segments(
  segments: list[dict[str, Any]],
  threshold: float = 0.5
) -> list[str]:
  return [s['path'] for s in segments]

# Good - Union operator
def get_config(key: str) -> str | int | None:
  return config.get(key)

# Avoid - Old typing module
from typing import List, Dict, Optional, Union
def old_style(items: List[Dict[str, str]]) -> Optional[int]:
  pass
```

#### Docstrings

```python
def save_clip(start: float, end: float, output: str) -> bool:
  """Save a clip from the rolling buffer.

  Args:
    start: Clip start offset in seconds.
    end: Clip end offset in seconds.
    output: Destination file path.

  Returns:
    True if the clip was written successfully, False otherwise.

  Raises:
    ValueError: If the time range is invalid.
    FileNotFoundError: If FFmpeg is not available.
  """
  pass
```

#### Imports

```python
"""Module docstring."""

# Standard library (alphabetical)
import json
import logging
from pathlib import Path

# Third-party packages (alphabetical)
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QMainWindow
import mpv

# Local modules (alphabetical)
from .model.config import Configuration
from .resources import resource_path

# Module constants
LOG = logging.getLogger(__name__)
DEFAULT_TIMEOUT = 30
```

### Code Quality Tools

```bash
# Format code (optional)
black --line-length 120 src/

# Lint code (optional)
pylint src/

# Type check (optional)
mypy src/
```

## Commit Messages

### Format

```
[Category] Brief description (50 chars or less)

More detailed explanation if needed (wrap at 72 chars).
Explain what and why, not how (code shows how).

- Bullet points are okay
- Use present tense ("Add feature" not "Added feature")
- Reference issues: Fixes #123, Closes #456
```

### Categories

- `[Feature]` - New feature
- `[Fix]` - Bug fix
- `[Docs]` - Documentation only
- `[Refactor]` - Code restructuring without behavior change
- `[Test]` - Adding or updating tests
- `[Chore]` - Maintenance tasks (dependencies, build, etc.)
- `[Style]` - Formatting, whitespace (no code change)

### Examples

**Good commits**:
```bash
[Feature] Add MKV clip export option

Implements an alternative container for saved clips and wires the
choice into the clip dialog and configuration.

Closes #234

[Fix] Resolve rolling buffer overflow on long sessions

Caps the on-disk segment ring and prunes expired segments so memory
and disk usage stay bounded during multi-hour sessions.

Fixes #123

[Docs] Add troubleshooting section to README

Includes common issues and solutions based on user feedback.
```

**Bad commits** (avoid these):
```bash
fix bug          # Too vague
WIP              # Don't commit work-in-progress
Fixed stuff      # Unclear what was fixed
```

## Testing Guidelines

### Running Tests

Run the suite inside the project virtual environment:

```bash
.venv/bin/python -m pytest
```

Coverage is configured in `pyproject.toml` (`--cov=clippiti.services --cov=clippiti.model.config`,
with a minimum threshold). Run a single file or test with:

```bash
.venv/bin/python -m pytest tests/test_buffer_engine.py
.venv/bin/python -m pytest tests/test_clipper.py -k save_clip
```

> Always use the virtual environment interpreter so workspace source is imported
> instead of stale site-packages.

### Manual Testing

Before submitting a PR, test these workflows:

- [ ] Application starts without errors
- [ ] A stream loads and plays via mpv
- [ ] Rolling buffer fills and stays within its configured limit
- [ ] Clipping saves a correct, playable file
- [ ] Recording starts, stops, and produces a valid output
- [ ] Remux/queue processing completes without errors
- [ ] All menu actions work as expected

### Testing Checklist for New Features

- [ ] Feature works on Linux (if possible)
- [ ] Feature works on Windows (if possible)
- [ ] Feature works on macOS (if possible)
- [ ] No regression in existing functionality
- [ ] Error cases handled gracefully
- [ ] User-facing messages are clear

### Writing Tests

Place tests under `tests/` mirroring the module under test, and prefer
`pytest` style:

```python
# tests/test_clipper.py
from clippiti.services.clipper import Clipper

def test_clip_time_range_validation():
  """Clipper rejects an inverted time range."""
  clipper = Clipper()
  assert clipper.is_valid_range(start=5.0, end=10.0)
  assert not clipper.is_valid_range(start=10.0, end=5.0)
```

## Documentation

### When to Update Documentation

Update docs when you:
- Add new features or configuration options
- Change existing behavior
- Fix bugs that affect usage
- Add new dependencies

### Documentation Files

- **README.md** - Overview, quick start, basic usage
- **doc/architecture-overview.md** - System design, components
- **doc/runtime-workflows.md** - Runtime flows and interactions
- **doc/module-reference.md** - Module-by-module reference
- **doc/configuration-and-cli.md** - Configuration and CLI reference
- **doc/operations-and-troubleshooting.md** - Operations and troubleshooting
- **doc/resource-footprint.md** - Memory, disk, and CPU footprint
- **Code comments** - Complex logic, non-obvious decisions

### Documentation Style

```markdown
# Use clear headings

## Organize hierarchically

### Include code examples

```bash
# Use syntax highlighting
./run_from_source.sh --help
```

**Bold for emphasis**, *italic for terms*.

- Bullet points for lists
- Keep sentences concise
- Use active voice

Use Mermaid diagrams for:
- Architecture overviews
- Flow diagrams
- Sequence diagrams
```

### Mermaid Diagram Guidelines

```mermaid
graph TD
    A[Component A] --> B[Component B]
    B --> C[Component C]

    style A fill:#007bff,color:#fff
    style B fill:#28a745,color:#fff
    style C fill:#dc3545,color:#fff
```

**Requirements**:
- Always set **both** `fill` and `color` for dark mode compatibility
- Use descriptive labels
- Keep diagrams simple and focused
- Test rendering in GitHub

## Getting Help

### Resources

- **Documentation** - Start with README and the doc/ directory
- **Issues** - Search existing issues for similar problems
- **Discussions** - Ask questions in GitHub Discussions
- **Code Examples** - Check the tests/ directory

### Contact

- **GitHub Issues** - Bug reports and feature requests
- **GitHub Discussions** - Questions and general discussion
- **Pull Requests** - Code contributions

### Response Times

We aim to:
- Acknowledge issues within **48 hours**
- Review PRs within **1 week**
- Release updates **monthly** (or as needed for critical fixes)

## Recognition

Contributors will be:
- Listed in project contributors
- Mentioned in release notes
- Recognized in README (for significant contributions)

## License

By contributing, you agree that your contributions will be licensed under the project's MIT License.

---

Thank you for contributing to Clippiti! 🎉
