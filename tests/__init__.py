"""Test package bootstrap.

The environment is configured before any game module is imported so that
pygame never tries to open a real window or audio device and the persistent
files go to a throw-away directory.
"""

import os
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault(
    "SPACEGAME_CONFIG_DIR",
    tempfile.mkdtemp(prefix="spacegame-tests-"),
)
