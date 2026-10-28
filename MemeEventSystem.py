"""Rotating Chinese-culture meme events for Meme Mode."""

from __future__ import annotations

import math
import random

import pygame

from utils import VH, VW, clamp


class MemeEventSystem:
    EVENTS = ("straw_boat", "vacuum_hurricane", "golden_dragon",
              "red_envelopes")
    DURATIONS = {
        "straw_boat": 6.5,
        "vacuum_hurricane": 6.0,
        "golden_dragon": 6.5,
        "red_envelopes": 6.0,
        "coffin_dance": 5.8,
    }
    BOAT_MAX_ARROWS = 100

    def __init__(self):
        self.kind = None
        self.time = 0.0
        self.cooldown = 10.0
        self.next_event = 0
        self.arrow_count = 22
        self.dragon_hits = set()
        self.envelopes = []
        self.last_ended = None

    @property
    def active(self):
        return self.kind is not None

    def start(self, kind):
        if kind not in self.EVENTS and kind != "coffin_dance":
            return False
        self.kind = kind
        self.time = 0.0
        self.arrow_count = 22
        self.dragon_hits.clear()
        self.envelopes.clear()
        if kind == "red_envelopes":
            for index in range(14):
                self.envelopes.append({
                    "x": random.uniform(40, VW - 40),
                    "y": random.uniform(-VH * .65, -30),
                    "speed": random.uniform(90, 175),
                    "phase": random.uniform(0, math.tau),
                })
        return True

    def update(self, dt):
        if self.kind is None:
            self.cooldown -= dt
            if self.cooldown <= 0:
                kind = self.EVENTS[self.next_event % len(self.EVENTS)]
                self.next_event += 1
                self.cooldown = 13.0
                self.start(kind)
                return "start"
            return None
        self.time += dt
        if self.kind == "red_envelopes":
            for envelope in self.envelopes:
                envelope["y"] += envelope["speed"] * dt
                envelope["x"] += math.sin(self.time * 2.8 + envelope["phase"]) * 34 * dt
        if self.time >= self.DURATIONS[self.kind]:
            self.last_ended = self.kind
            self.kind = None
            self.envelopes.clear()
            return "end"
        return None

    def apply(self, game, dt):
        if self.kind == "vacuum_hurricane":
            self._pull_toward_vortex(game, dt)
        elif self.kind == "golden_dragon":
            self._damage_dragon_targets(game)
        elif self.kind == "red_envelopes":
            self._collect_envelopes(game)

    def _pull_toward_vortex(self, game, dt):
        cx, cy = VW * .5, VH * .48
        enemies_to_remove = []
        entities = list(game.enemies)
        entities.extend(game.player_bullets)
        entities.extend(game.enemy_bullets)
        entities.extend(game.powerups)
        entities.extend(game.players)
        if game.boss is not None:
            entities.append(game.boss)
        for entity in entities:
            if not getattr(entity, "alive", True):
                continue
            dx, dy = cx - entity.posX, cy - entity.posY
            distance = max(1.0, math.hypot(dx, dy))
            falloff = clamp(1.0 - distance / 850.0, .12, 1.0)
            speed = (95.0 if entity in game.players else 175.0) * falloff
            swirl = 48.0 * falloff
            entity.posX += (dx / distance * speed - dy / distance * swirl) * dt
            entity.posY += (dy / distance * speed + dx / distance * swirl) * dt
            if entity in game.enemies and distance < 48:
                enemies_to_remove.append(entity)
            elif entity is game.boss and distance < 72:
                entity.damage(max(1, entity.max_hp // 5))
                if entity.hp <= 0:
                    game._defeat_boss()
        for enemy in enemies_to_remove:
            game._kill_enemy(enemy, award=True, drop=False)

    def _dragon_position(self):
        progress = clamp(self.time / self.DURATIONS["golden_dragon"], 0.0, 1.0)
        x = -180 + (VW + 360) * progress
        y = VH * .48 + math.sin(progress * math.tau * 2.2) * VH * .13
        return x, y, progress

    def _boat_position(self):
        progress = clamp(self.time / self.DURATIONS["straw_boat"], 0.0, 1.0)
        x = -270 + (VW + 540) * progress
        y = VH * .51 + math.sin(self.time * 2.6) * 11
        return x, y, progress

    def _damage_dragon_targets(self, game):
        x, y, progress = self._dragon_position()
        if progress >= 1.0:
            return
        for enemy in tuple(game.enemies):
            if id(enemy) in self.dragon_hits or not enemy.alive:
                continue
            if math.hypot(enemy.posX - x, enemy.posY - y) <= enemy.hit_radius + 54:
                self.dragon_hits.add(id(enemy))
                if enemy.damage(6):
                    game._kill_enemy(enemy, award=True, drop=False)

    def _collect_envelopes(self, game):
        collected = []
        for envelope in self.envelopes:
            for player in game.players:
                if (player.alive and math.hypot(
                        player.centerx - envelope["x"],
                        player.centery - envelope["y"]) < player.hit_radius + 18):
                    game._add_score(100)
                    game.effects.text("+100", envelope["x"], envelope["y"],
                                      (255, 222, 102), 17, .9)
                    game.audio.play("meme_pickup", .35, throttle_ms=90)
                    collected.append(envelope)
                    break
        self.envelopes[:] = [envelope for envelope in self.envelopes
                             if envelope not in collected and envelope["y"] < VH + 40]

    def absorbs_bullet(self, bullet):
        if self.kind != "straw_boat":
            return False
        cx, cy, _progress = self._boat_position()
        if abs(bullet.posX - cx) > 248 or abs(bullet.posY - cy) > 92:
            return False
        self.arrow_count = min(self.BOAT_MAX_ARROWS, self.arrow_count + 1)
        return True

    def draw_arrow(self, surface, bullet):
        if self.kind != "straw_boat":
            return
        vx, vy = bullet.vx, bullet.vy
        length = max(1.0, math.hypot(vx, vy))
        ux, uy = vx / length, vy / length
        tail = (bullet.posX - ux * 20, bullet.posY - uy * 20)
        tip = (bullet.posX + ux * 8, bullet.posY + uy * 8)
        pygame.draw.line(surface, (83, 50, 28), tail, tip, 3)
        px, py = -uy * 4, ux * 4
        pygame.draw.polygon(surface, (244, 194, 99),
                            (tip, (tip[0] - ux * 9 + px,
                                   tip[1] - uy * 9 + py),
                             (tip[0] - ux * 9 - px,
                              tip[1] - uy * 9 - py)))

    def draw(self, surface, resources):
        if self.kind == "straw_boat":
            self._draw_straw_boat(surface, resources)
        elif self.kind == "vacuum_hurricane":
            self._draw_vortex(surface, resources)
        elif self.kind == "golden_dragon":
            self._draw_dragon(surface, resources)
        elif self.kind == "red_envelopes":
            self._draw_envelopes(surface, resources)
        elif self.kind == "coffin_dance":
            self._draw_coffin_dance(surface, resources)

    @staticmethod
    def _text(surface, resources, text, size, color, center):
        glyph = resources.text(text, size, color, kind="chinese")
        surface.blit(glyph, glyph.get_rect(center=(int(center[0]), int(center[1]))))

    @staticmethod
    def _arrow(surface, start, end, color=(61, 39, 26)):
        pygame.draw.line(surface, color, start, end, 4)
        angle = math.atan2(end[1] - start[1], end[0] - start[0])
        points = [end]
        for offset in (-2.5, 2.5):
            points.append((end[0] - math.cos(angle + offset) * 12,
                           end[1] - math.sin(angle + offset) * 12))
        pygame.draw.polygon(surface, (68, 43, 26), points)

    def _draw_straw_boat(self, surface, resources):
        layer = pygame.Surface((VW, VH), pygame.SRCALPHA)
        cx, boat_y, progress = self._boat_position()
        deck = int(boat_y)
        wave_y = deck + 62
        for index in range(5):
            x = (index * 173 + int(self.time * 95)) % (VW + 160) - 80
            pygame.draw.arc(layer, (73, 193, 241, 125),
                            (x - 65, wave_y + index * 12, 130, 26), 0, math.pi, 3)
        pygame.draw.polygon(layer, (145, 76, 42, 245),
                            ((cx - 250, deck), (cx + 250, deck),
                             (cx + 186, deck + 102), (cx - 177, deck + 102)))
        pygame.draw.polygon(layer, (209, 145, 77, 245),
                            ((cx - 226, deck - 8), (cx + 228, deck - 8),
                             (cx + 250, deck), (cx - 250, deck)))
        pygame.draw.polygon(layer, (187, 136, 71, 245),
                            ((cx - 194, deck - 61), (cx + 194, deck - 61),
                             (cx + 217, deck - 8), (cx - 216, deck - 8)))
        for index in range(9):
            x = cx - 176 + index * 44
            y = deck - 59 + (index % 2) * 7
            pygame.draw.ellipse(layer, (228, 184, 109, 245),
                                (x - 24, y - 20, 48, 32))
            pygame.draw.line(layer, (166, 119, 61, 190), (x - 17, y),
                             (x + 17, y - 5), 2)
        for index in range(8):
            x = cx - 163 + index * 46
            y = deck - 73 + (index % 2) * 5
            pygame.draw.polygon(layer, (243, 207, 132, 255),
                                ((x - 22, y + 8), (x, y - 21), (x + 22, y + 8)))
            pygame.draw.ellipse(layer, (173, 122, 65, 255),
                                (x - 25, y + 5, 50, 12))
            pygame.draw.line(layer, (255, 233, 173, 190),
                             (x - 11, y + 5), (x + 2, y - 13), 2)
        for index in range(self.arrow_count):
            fraction = index / max(1, self.arrow_count)
            x = cx - 206 + (index * 71 % 412)
            y = deck - 133 + (index * 37 % 118)
            end = (x + math.sin(index * 4.7) * 28,
                   y + 42 + fraction * 18)
            self._arrow(layer, (x, y), end)
        pygame.draw.rect(layer, (160, 35, 51, 255),
                         (cx + 108, deck - 151, 6, 91))
        pygame.draw.polygon(layer, (221, 52, 62, 255),
                            ((cx + 111, deck - 151), (cx + 177, deck - 135),
                             (cx + 111, deck - 116)))
        self._text(layer, resources, "草船借箭", 36, (255, 238, 189),
                   (cx, deck - 190))
        self._text(layer, resources, "咚", 38, (255, 224, 110),
                   (cx, deck - 133))
        if progress < .05:
            layer.set_alpha(int(255 * progress / .05))
        elif progress > .95:
            layer.set_alpha(int(255 * (1.0 - progress) / .05))
        surface.blit(layer, (0, 0))

    def _draw_coffin_dance(self, surface, resources):
        layer = pygame.Surface((VW, VH), pygame.SRCALPHA)
        progress = clamp(self.time / self.DURATIONS["coffin_dance"], 0.0, 1.0)
        x = -170 + (VW + 340) * progress
        bob = math.sin(self.time * 12.0) * 9
        y = int(VH * .50 + bob)
        coffin = pygame.Rect(int(x - 96), y - 26, 192, 55)
        pygame.draw.rect(layer, (115, 25, 39, 255), coffin, border_radius=12)
        pygame.draw.rect(layer, (255, 198, 88, 255), coffin, 4, border_radius=12)
        pygame.draw.line(layer, (255, 223, 138, 255),
                         (coffin.centerx, coffin.top + 8),
                         (coffin.centerx, coffin.bottom - 8), 3)
        self._text(layer, resources, "福", 24, (255, 224, 134), coffin.center)
        for index in range(6):
            px = x - 132 + index * 53
            phase = self.time * 9 + index * .8
            lift = math.sin(phase) * 13
            py = y + 37 + lift
            pygame.draw.circle(layer, (237, 184, 135, 255),
                               (int(px), int(py - 13)), 10)
            pygame.draw.polygon(layer, (24, 35, 54, 255),
                                ((px - 12, py - 3), (px + 12, py - 3),
                                 (px + 17, py + 27), (px - 17, py + 27)))
            swing = math.sin(phase) * 17
            pygame.draw.line(layer, (237, 184, 135, 255),
                             (px - 7, py + 2), (px - 20, py - 18 + swing), 5)
            pygame.draw.line(layer, (237, 184, 135, 255),
                             (px + 7, py + 2), (px + 20, py - 18 - swing), 5)
            pygame.draw.line(layer, (20, 26, 42, 255),
                             (px - 8, py + 24), (px - 16, py + 45), 6)
            pygame.draw.line(layer, (20, 26, 42, 255),
                             (px + 8, py + 24), (px + 16, py + 45), 6)
        self._text(layer, resources, "抬棺", 31, (255, 224, 134),
                   (x, y - 70))
        surface.blit(layer, (0, 0))

    def _draw_vortex(self, surface, resources):
        layer = pygame.Surface((VW, VH), pygame.SRCALPHA)
        cx, cy = VW * .5, VH * .48
        radius = 66 + 18 * math.sin(self.time * 7)
        pygame.draw.circle(layer, (130, 71, 255, 48),
                           (int(cx), int(cy)), int(radius * 2.3))
        for arm in range(4):
            points = []
            for step in range(80):
                progress = step / 79
                r = 25 + progress * 282
                angle = self.time * 3.6 + arm * math.tau / 4 + progress * math.tau * 1.8
                points.append((cx + math.cos(angle) * r,
                               cy + math.sin(angle) * r * .66))
            pygame.draw.lines(layer, (146, 117, 255, 185), False, points, 5)
            pygame.draw.lines(layer, (245, 232, 255, 185), False, points, 2)
        pygame.draw.circle(layer, (37, 15, 83, 170), (int(cx), int(cy)), 40)
        self._text(layer, resources, "吸", 42, (249, 232, 255), (cx, cy))
        surface.blit(layer, (0, 0))

    def _draw_dragon(self, surface, resources):
        layer = pygame.Surface((VW, VH), pygame.SRCALPHA)
        head_x, head_y, progress = self._dragon_position()
        body = []
        for index in range(25):
            back = index / 24 * 300
            px = head_x - back
            ratio = clamp((px + 180) / (VW + 360), 0.0, 1.0)
            py = VH * .48 + math.sin(ratio * math.tau * 2.2) * VH * .13
            py += math.sin(index * .52 + self.time * 6) * 16
            body.append((px, py))
        pygame.draw.lines(layer, (185, 35, 48, 105), False, body, 34)
        pygame.draw.lines(layer, (229, 60, 55, 225), False, body, 22)
        pygame.draw.lines(layer, (255, 180, 65, 235), False, body, 9)
        pygame.draw.circle(layer, (245, 81, 50, 255),
                           (int(head_x), int(head_y)), 24)
        pygame.draw.circle(layer, (255, 227, 112, 255),
                           (int(head_x + 6), int(head_y - 5)), 4)
        pygame.draw.polygon(layer, (255, 220, 126, 240),
                            ((head_x - 13, head_y - 18),
                             (head_x - 29, head_y - 37),
                             (head_x - 20, head_y - 7)))
        if progress < .87:
            self._text(layer, resources, "龍來了", 30,
                       (255, 224, 137), (VW * .5, 102))
        surface.blit(layer, (0, 0))

    def _draw_envelopes(self, surface, resources):
        layer = pygame.Surface((VW, VH), pygame.SRCALPHA)
        for envelope in self.envelopes:
            x, y = int(envelope["x"]), int(envelope["y"])
            rect = pygame.Rect(x - 13, y - 17, 26, 34)
            pygame.draw.rect(layer, (185, 28, 45, 245), rect, border_radius=4)
            pygame.draw.rect(layer, (255, 208, 98, 255), rect, 2, border_radius=4)
            pygame.draw.polygon(layer, (225, 60, 59, 255),
                                ((x - 11, y - 8), (x, y + 2), (x + 11, y - 8)))
            self._text(layer, resources, "福", 15, (255, 225, 137), (x, y + 8))
        surface.blit(layer, (0, 0))
