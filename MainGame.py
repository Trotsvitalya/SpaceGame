"""SpaceGame entry point.

Run with:
    python MainGame.py
Windows note: if fullscreen causes trouble, use:
    python MainGame.py --windowed
"""

from __future__ import annotations

import os
import sys


def _set_windows_dpi_awareness():
    """Prevent Windows from scaling the already-scaled Pygame framebuffer."""
    if os.name != "nt":
        return
    try:
        import ctypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        try:
            # Per-monitor v2: opt out of Windows bitmap stretching before SDL
            # creates the display window. Ignore failure when a manifest or
            # another launcher has already selected the process DPI mode.
            if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
                return
        except (AttributeError, OSError, TypeError):
            pass
        try:
            shcore = ctypes.WinDLL("shcore", use_last_error=True)
            if shcore.SetProcessDpiAwareness(2) == 0:  # PROCESS_PER_MONITOR_DPI_AWARE
                return
        except (AttributeError, OSError, TypeError):
            pass
        try:
            user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass
    except (ImportError, OSError):
        pass


def main():
    _set_windows_dpi_awareness()
    import pygame

    os.environ.setdefault("SDL_VIDEO_CENTERED", "1")
    pygame.mixer.pre_init(44100, -16, 2, 512)
    pygame.init()
    force_windowed = "--windowed" in sys.argv or "-w" in sys.argv

    from AppClass import App

    app = App(force_windowed=force_windowed)
    try:
        app.run()
    finally:
        try:
            app.settings.save()
            app.audio.stop_music()
        except Exception:
            pass
        pygame.quit()


if __name__ == "__main__":
    main()
