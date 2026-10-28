"""Regenerate the documented UI and gameplay screenshots with dummy SDL."""

from __future__ import annotations

import os
import random
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ["SPACEGAME_CONFIG_DIR"] = tempfile.mkdtemp(prefix="spacegame-shots-")

import pygame

from AppClass import App
from EnemyAsteroidClass import BossEnemy, EnemyShip
from GameProcessClass import GameProcess
from MenuClass import Menu
from utils import VH, VW


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT = os.path.join(ROOT, "screenshots")


def save(name, scene):
    canvas = pygame.Surface((VW, VH)).convert()
    scene.draw(canvas)
    pygame.image.save(canvas, os.path.join(OUTPUT, name))


def menu(app, screen, filename):
    random.seed(20261028)
    scene = Menu(app, initial_screen=screen)
    scene.screen_fade = 0
    save(filename, scene)


def game_with_enemies(app, mode="normal"):
    game = GameProcess(app, mode)
    game.time = 8.4
    game.game_time = 53.0
    game.wave = 4
    game.score = 7260
    game.display_score = 7260
    game.meme_points = 2600 if mode == "meme" else 0
    game.player.posX = VW * .5 - game.player.width * .5
    game.player.posY = VH - 165
    for kind, x, y in (
        ("scout", 280, 170), ("fighter", 470, 230),
        ("bomber", 790, 160), ("raider", 990, 285),
        ("elite", 640, 115),
    ):
        enemy = EnemyShip(kind, mode, game.resources, x=x, y=y,
                          wave=game.wave, balance=game.balance)
        enemy.entered = True
        enemy.target_y = y
        enemy.posY = y
        game.enemies.append(enemy)
    game.spawn_enemy_bullet(330, 310, 1.2, 0.0)
    game.spawn_enemy_bullet(884, 330, 1.9, 0.0)
    game._spawn_powerup(402, 348, "weapon")
    return game


def capture_all():
    pygame.init()
    pygame.display.set_mode((VW, VH))
    app = App(force_windowed=True)
    app.settings.language = "uk"
    app.settings.muted = True

    menu(app, "main", "StartMenu.png")
    menu(app, "mode", "ModeSelect.png")
    menu(app, "settings", "Settings.png")
    menu(app, "leaderboard", "Leaderboard.png")

    normal = game_with_enemies(app)
    save("Game.png", normal)
    normal._spawn_boss()
    normal.boss.posY = 188
    normal.boss.entered = True
    normal.boss.hp = int(normal.boss.max_hp * .68)
    save("Boss.png", normal)

    over = game_with_enemies(app)
    over.state = "gameover"
    over.overlay_time = 1.2
    over.result = {"score": 7260, "best": 8140, "is_new": False,
                   "best_before": 8140, "wave": 5, "kills": 39,
                   "time": 142.0}
    over._build_gameover_widgets()
    save("GameOver.png", over)

    meme = game_with_enemies(app, "meme")
    meme.superpower_charges["chainsaw"] = 1
    meme.meme_event.start("straw_boat")
    meme.meme_event.time = 2.4
    save("MemeMode.png", meme)
    shop = game_with_enemies(app, "meme")
    shop.superpower_charges["chainsaw"] = 1
    save("Superpowers.png", shop)

    for kind, filename in (
        ("straw_boat", "StrawBoat.png"),
        ("vacuum_hurricane", "VacuumHurricane.png"),
        ("golden_dragon", "GoldenDragon.png"),
        ("red_envelopes", "RedEnvelopes.png"),
        ("coffin_dance", "CoffinDance.png"),
    ):
        event_game = game_with_enemies(app, "meme")
        event_game.meme_event.start(kind)
        event_game.meme_event.time = 2.7
        save(filename, event_game)

    tiger = game_with_enemies(app, "meme")
    tiger.tiger_ultimate.start()
    tiger.tiger_ultimate.loader_thread.join(timeout=10)
    tiger.tiger_ultimate.phase = "claw_strike"
    tiger.tiger_ultimate.elapsed = sum(duration for _name, duration
                                        in tiger.tiger_ultimate.PHASES[:3]) + .46
    tiger.tiger_ultimate.phase_time = .46
    tiger.tiger_ultimate.next_cut_event = 2
    save("TigerClaws.png", tiger)

    saw = game_with_enemies(app, "meme")
    saw.chainsaw.start()
    saw.chainsaw.phase = "chase"
    saw.chainsaw.elapsed = 1.6
    saw.chainsaw.saws = [
        [236.0, 220.0, saw.enemies[0]],
        [476.0, 305.0, saw.enemies[1]],
        [808.0, 205.0, saw.enemies[2]],
        [1030.0, 345.0, saw.enemies[3]],
    ]
    save("Chainsaw.png", saw)

    for scene in (normal, over, meme, shop, tiger, saw):
        scene.on_exit()
    pygame.quit()


if __name__ == "__main__":
    capture_all()
