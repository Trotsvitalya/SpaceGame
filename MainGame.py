"""SpaceGame entry point.

Run with:
    python MainGame.py
Windows note: if fullscreen causes trouble, use:
    python MainGame.py --windowed
"""

from __future__ import annotations

import os
import sys


def main():
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
