# SpaceGame

**SpaceGame** is a 2D arcade space shooter built with Python and Pygame. Fight enemy waves and bosses, improve your ship, and explore a lighthearted Meme Mode. The game includes Ukrainian and English interfaces.

> Українська версія документації: [README.uk.md](README.uk.md).

## Features

- **Game modes:** Endless Normal and Meme modes, a mission campaign, and LAN/direct-IP co-op.
- **Four ships:** Fighter, Interceptor, Cruiser, and Engineer, each with distinct weapons and passive bonuses.
- **Combat progression:** enemy waves, multi-phase bosses, four weapon types, combo scoring, salvage, and upgrades between waves.
- **Meme superpowers:** buy Tiger and Chainsaw charges with Meme Points. Press `1` for Tiger and `2` for Chainsaw; the first press buys a charge when you have enough points, and the next activates it.
- **Tiger Ultimate:** the full video plays and disappears before the claw strikes begin. Lighting returns to normal as gameplay resumes.
- **Chainsaw Ultimate:** pauses for a screen-split effect, then sends chainsaws after enemies. Enemies flee and ignore the player while it is active.
- **Meme events:** enemies and bosses aim at the sailing straw boat; absorbed shots add arrows to its deck (up to 100). The boat has drum, water, and Mandarin battle-call cues; a vacuum hurricane pulls nearby entities and sounds its own air-raid siren; a golden dragon attacks enemies; red envelopes can be collected; and Coffin Dance plays its synthesized dance loop. Coffin Dance is intentionally rare: it can appear every 36th kill or every third boss in Meme Mode.
- **Display scaling:** the game renders to a fixed 1280×720 canvas. Integer scale factors keep pixel edges crisp; fractional sizes such as 1920×1080 use filtered scaling to avoid unevenly stretched glyphs. Fullscreen and windowed sizes can be selected in Settings.
- **Accessibility and persistence:** configurable sound, graphics quality, reduced flashes, screen shake, focus pause, and language. Settings, records, and campaign progress are saved locally.

## Requirements

- Python 3.10 or newer
- pygame-ce 2.5.8+ (or a compatible Pygame 2.5+ build)
- An audio device is optional

## Install and run

```bash
git clone https://github.com/Trotsvitalya/SpaceGame.git
cd SpaceGame
python -m pip install -r requirements.txt
python MainGame.py
```

Use `python MainGame.py --windowed` (or `-w`) to force windowed mode. `F11` toggles fullscreen. In Settings, choose a display resolution/window size; the change applies immediately and is saved for the next launch. The window can also be resized by dragging its edge.

## Controls

| Action | Keys |
| --- | --- |
| Move | Arrow keys or `WASD` |
| Fire | Hold `Space` |
| Pause / resume | `Esc` or `P` |
| Restart | `R`, or `Enter` on pause/game-over screens |
| Return to menu | `M`, or `Esc` on the game-over screen |
| Toggle fullscreen | `F11` |
| Choose an upgrade | `1`–`3`, arrows and `Enter`, or mouse |
| Buy / activate Tiger | `1` in Meme Mode |
| Buy / activate Chainsaw | `2` in Meme Mode |
| Navigate menus | Arrows / `WASD`, `Tab`, `Enter`, `Esc`, or mouse |

Meme Points are earned in Meme Mode and are held in a separate wallet from the run score. Power-up cards show progress toward their purchase cost and the number of charges owned.

## Game modes

### Normal Mode

A classic space shooter with enemy waves, hazards, bosses, ship upgrades, and a restrained visual style.

### Meme Mode

Features a separate palette, music, score wallet, sound effects, and timed visual events. During Straw Boat and Coffin Dance events, Mandarin battle shouts can play; regular bonus pickups do not play Chinese voice clips. The hurricane has a distinct synthesized air-raid siren, the boat combines a drum cue with water-like notes, and Coffin Dance uses its own upbeat synthesized music loop.

Tiger power-ups can drop when at least three enemies are alive. Their drop chance is 20%, with an 18-second cooldown. A collected Tiger drop activates immediately. Tiger charges can also be purchased for 4,000 Meme Points; Chainsaw charges cost 1,800 Meme Points.

## Ships

| Ship | Role | Weapon | Passive |
| --- | --- | --- | --- |
| Fighter | All-rounder | Pulse | Balanced stats |
| Interceptor | Agile | Burst | Extra invulnerability after respawn |
| Cruiser | Armored | Piercing lance | Extra shield after respawn |
| Engineer | Support | Spread shot | More salvage and a wider pickup magnet |

## Waves and upgrades

Waves begin about every 24 seconds. Every fifth wave ends with a boss. After every third wave and after boss fights, choose an upgrade or skip it. Upgrades improve damage, fire rate, hull, multishot, engines, salvage collection, or shields.

## Settings and saved data

The Settings screen lets you set music and effects volume, mute audio, fullscreen, display resolution/window size, screen shake, FPS display, graphics quality, reduced flashes, pause-on-focus-loss, language, and difficulty. Changes are saved automatically.

`settings.json`, `scores.json`, and campaign data are stored outside version control. To use a custom config directory:

```powershell
$env:SPACEGAME_CONFIG_DIR = "C:\temp\spacegame-config"
python MainGame.py
```

## Audio and assets

Procedural sound effects and fallback music are created in `AudioSynth.py`. Optional music can be placed in `assets/music/GameProcess/` and `assets/music/Meme/` (MP3, OGG, WAV, or FLAC). See [ASSETS.md](ASSETS.md) for asset provenance and license notes. The included `wt034.ttf` font and Tiger media retain their original owners' terms.

## Project map

| Path | Purpose |
| --- | --- |
| `MainGame.py`, `AppClass.py` | Startup, window, scaling, and scene changes |
| `MenuClass.py`, `UIClass.py` | Menus, settings, hangar, and widgets |
| `GameProcessClass.py` | Gameplay, waves, collisions, Meme shop, and HUD |
| `TigerUltimate.py`, `ChainsawUltimate.py` | Superpower animations and combat behavior |
| `MemeEventSystem.py` | Straw Boat, hurricane, dragon, envelopes, and Coffin Dance |
| `AudioClass.py`, `AudioSynth.py` | Audio playback and generated sound bank |
| `SettingsClass.py`, `Localization.py` | Saved preferences, scores, and translations |
| `assets/` | Game images, fonts, video, sounds, and music |
| `screenshots/` | In-game screenshots |
| `tests/` | Automated tests |

## Screenshots

| Menus and settings | Gameplay and Meme Mode |
| --- | --- |
| ![Main menu](screenshots/StartMenu.png) | ![Gameplay](screenshots/Game.png) |
| ![Settings](screenshots/Settings.png) | ![Meme shop](screenshots/Superpowers.png) |
| ![Mode selection](screenshots/ModeSelect.png) | ![Boss](screenshots/Boss.png) |
| ![Straw Boat](screenshots/StrawBoat.png) | ![Vacuum Hurricane](screenshots/VacuumHurricane.png) |
| ![Coffin Dance](screenshots/CoffinDance.png) | ![Chainsaw](screenshots/Chainsaw.png) |

## Validation

Run the automated test suite:

```bash
python -m unittest discover -s tests -v
```

Check Python syntax:

```bash
python -m py_compile *.py tools/*.py
```

## License

The source code and original project assets are released under the [Unlicense](LICENSE). Third-party media and fonts retain their own license terms; see [ASSETS.md](ASSETS.md).
