"""Reusable immediate-mode UI helpers: panels, buttons, sliders, toggles."""

from __future__ import annotations

import pygame

from utils import clamp

_PANEL_CACHE = {}


def draw_text(surface, resources, text, size, color, pos, anchor="topleft",
              kind="body", shadow=None, alpha=255):
    image = resources.text(text, size, color, kind)
    if alpha < 255:
        image.set_alpha(alpha)
    rect = image.get_rect(**{anchor: pos})
    if shadow is not None:
        shadow_image = resources.text(text, size, shadow, kind)
        if alpha < 255:
            shadow_image.set_alpha(alpha)
        surface.blit(shadow_image, rect.move(2, 2))
        if alpha < 255:
            shadow_image.set_alpha(255)
    surface.blit(image, rect)
    if alpha < 255:
        image.set_alpha(255)
    return rect


def measure(resources, text, size, kind="body"):
    return resources.font(size, kind).size(str(text))


def draw_panel(surface, rect, fill=(8, 15, 32, 205), border=None, radius=12, width=1):
    rect = pygame.Rect(rect)
    if rect.width <= 0 or rect.height <= 0:
        return
    key = (rect.width, rect.height, tuple(fill), tuple(border) if border else None, radius, width)
    panel = _PANEL_CACHE.get(key)
    if panel is None:
        panel = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        pygame.draw.rect(panel, fill, panel.get_rect(), border_radius=radius)
        if border:
            pygame.draw.rect(panel, border, panel.get_rect(), width=width, border_radius=radius)
        if len(_PANEL_CACHE) > 120:
            _PANEL_CACHE.clear()
        _PANEL_CACHE[key] = panel
    surface.blit(panel, rect.topleft)


def draw_bar(surface, rect, ratio, fill_color, back_color=(20, 28, 48), border=None,
             radius=4):
    rect = pygame.Rect(rect)
    pygame.draw.rect(surface, back_color, rect, border_radius=radius)
    inner = rect.inflate(-4, -4)
    ratio = clamp(ratio, 0.0, 1.0)
    if ratio > 0:
        filled = pygame.Rect(inner.x, inner.y, int(inner.width * ratio), inner.height)
        pygame.draw.rect(surface, fill_color, filled, border_radius=max(1, radius - 1))
    if border:
        pygame.draw.rect(surface, border, rect, width=1, border_radius=radius)


def _text_of(value):
    return value() if callable(value) else value


class Button:
    def __init__(self, rect, text, action, size=23, accent=None, subtitle=None):
        self.rect = pygame.Rect(rect)
        self.text = text
        self.action = action
        self.size = size
        self.accent = accent
        self.subtitle = subtitle
        self.hovered = False
        self.pressed = False

    def label(self):
        return _text_of(self.text)

    def draw(self, surface, resources, palette, focused):
        accent = self.accent or palette["accent"]
        hovered = self.hovered or focused
        fill = (16, 28, 52, 220) if not hovered else (24, 44, 74, 235)
        if palette is not None and palette.get("panel") == (42, 14, 46):
            fill = (52, 18, 58, 228) if not hovered else (76, 28, 82, 240)
        rect = self.rect.move(0, 2 if self.pressed else 0)
        draw_panel(surface, self.rect.move(3, 5), (0, 0, 0, 90), radius=10)
        draw_panel(surface, rect, fill, accent if hovered else palette["border"],
                   radius=10, width=2 if hovered else 1)
        if hovered:
            pygame.draw.rect(surface, accent, (rect.x + 8, rect.y + 10, 4, rect.height - 20),
                             border_radius=2)
        color = accent if hovered else palette["text"]
        draw_text(surface, resources, self.label(), self.size, color,
                  rect.center, anchor="center", shadow=(2, 6, 14))
        if self.subtitle:
            draw_text(surface, resources, _text_of(self.subtitle), 13, palette["muted"],
                      (rect.centerx, rect.bottom - 12), anchor="center")


class Slider:
    def __init__(self, rect, label, get_value, set_value, on_change=None):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.get_value = get_value
        self.set_value = set_value
        self.on_change = on_change
        self.dragging = False
        self.hovered = False
        self.track_rect = pygame.Rect(self.rect.x + 235, self.rect.y + 21,
                                      self.rect.width - 315, 8)
        self.knob_x = self.track_rect.x

    def value(self):
        try:
            return clamp(float(self.get_value()), 0.0, 1.0)
        except (TypeError, ValueError):
            return 0.0

    def _apply_value(self, value):
        value = clamp(value, 0.0, 1.0)
        self.set_value(round(value, 2))
        if self.on_change:
            self.on_change()

    def _position_to_value(self, mouse_x):
        ratio = (mouse_x - self.track_rect.x) / max(1, self.track_rect.width)
        self._apply_value(ratio)

    def begin_drag(self, mouse):
        self.dragging = True
        self._position_to_value(mouse[0])

    def drag(self, mouse):
        if self.dragging:
            self._position_to_value(mouse[0])

    def adjust(self, step):
        self._apply_value(self.value() + step * 0.05)

    def activate(self):
        return None

    def draw(self, surface, resources, palette, focused):
        value = self.value()
        label_color = palette["accent"] if focused else palette["text"]
        draw_text(surface, resources, _text_of(self.label), 20, label_color,
                  (self.rect.x + 14, self.rect.centery), anchor="midleft")
        # Track
        pygame.draw.rect(surface, (18, 26, 44), self.track_rect, border_radius=4)
        filled = self.track_rect.copy()
        filled.width = int(self.track_rect.width * value)
        if filled.width > 0:
            pygame.draw.rect(surface, palette["accent"], filled, border_radius=4)
        knob_x = self.track_rect.x + int(self.track_rect.width * value)
        glow = resources.glow(14, palette["accent"], 90)
        surface.blit(glow, glow.get_rect(center=(knob_x, self.track_rect.centery)))
        pygame.draw.circle(surface, (240, 250, 255), (knob_x, self.track_rect.centery), 7)
        pygame.draw.circle(surface, palette["accent"], (knob_x, self.track_rect.centery), 7, 2)
        draw_text(surface, resources, f"{int(value * 100)}%", 17, palette["muted"],
                  (self.rect.right - 14, self.rect.centery), anchor="midright")


class Toggle:
    def __init__(self, rect, label, get_value, set_value, on_change=None):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.get_value = get_value
        self.set_value = set_value
        self.on_change = on_change
        self.hovered = False

    def value(self):
        return bool(self.get_value())

    def toggle(self):
        self.set_value(not self.value())
        if self.on_change:
            self.on_change()

    def adjust(self, step):
        self.toggle()

    def activate(self):
        self.toggle()
        return None

    def draw(self, surface, resources, palette, focused):
        active = self.value()
        color = palette["success"] if active else palette["muted"]
        label_color = palette["accent"] if focused else palette["text"]
        draw_text(surface, resources, _text_of(self.label), 20, label_color,
                  (self.rect.x + 14, self.rect.centery), anchor="midleft")
        knob_rect = pygame.Rect(self.rect.right - 86, self.rect.centery - 13, 58, 26)
        pygame.draw.rect(surface, (18, 26, 44) if not active else (30, 90, 70),
                         knob_rect, border_radius=13)
        pygame.draw.rect(surface, color, knob_rect, width=2, border_radius=13)
        cx = knob_rect.right - 13 if active else knob_rect.x + 13
        pygame.draw.circle(surface, color, (cx, knob_rect.centery), 8)
        draw_text(surface, resources, "ON" if active else "OFF", 14, color,
                  (knob_rect.x - 12, self.rect.centery), anchor="midright")


class Choice:
    def __init__(self, rect, label, options, get_index, set_index, on_change=None):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.options = options  # list of (value, label) or callables
        self.get_index = get_index
        self.set_index = set_index
        self.on_change = on_change
        self.hovered = False

    def index(self):
        try:
            return int(self.get_index()) % max(1, len(self.options))
        except (TypeError, ValueError):
            return 0

    def _label(self):
        option = self.options[self.index()]
        return _text_of(option[1]) if len(option) > 1 else str(option[0])

    def adjust(self, step):
        new_index = (self.index() + step) % len(self.options)
        self.set_index(new_index)
        if self.on_change:
            self.on_change()

    def activate(self):
        self.adjust(1)
        return None

    def draw(self, surface, resources, palette, focused):
        draw_text(surface, resources, _text_of(self.label), 20,
                  palette["accent"] if focused else palette["text"],
                  (self.rect.x + 14, self.rect.centery), anchor="midleft")
        box = pygame.Rect(self.rect.right - 210, self.rect.centery - 16, 184, 32)
        pygame.draw.rect(surface, (18, 26, 44), box, border_radius=8)
        pygame.draw.rect(surface, palette["accent"] if focused else palette["border"],
                         box, width=1, border_radius=8)
        draw_text(surface, resources, "<  " + self._label() + "  >", 16,
                  palette["text"], box.center, anchor="center")


class TextInput:
    """Small single-line text field used by the multiplayer screens.

    Text is fed through ``pygame.TEXTINPUT`` for proper Unicode handling;
    backspace/delete are handled from ``KEYDOWN``.  Values are always
    sanitised before they reach the settings object, so a hand-edited or pasted
    string can never inject control characters into the network layer.
    """

    def __init__(self, rect, label, get_value, set_value, max_length=32,
                 numeric=False, address=False, placeholder="", on_change=None):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.get_value = get_value
        self.set_value = set_value
        self.max_length = max(1, int(max_length))
        self.numeric = numeric
        self.address = address
        self.placeholder = placeholder
        self.on_change = on_change
        self.hovered = False
        self.active = False

    def value(self):
        try:
            text = self.get_value()
        except (TypeError, ValueError):
            text = ""
        return str(text or "")[:self.max_length]

    def sanitize(self, text):
        text = str(text or "")
        if self.numeric:
            cleaned = "".join(ch for ch in text if ch.isdigit())
        elif self.address:
            allowed = set("abcdefghijklmnopqrstuvwxyz"
                          "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_:")
            cleaned = "".join(ch for ch in text if ch in allowed)
        else:
            cleaned = "".join(ch for ch in text if ch.isprintable())
        return cleaned[:self.max_length]

    def set_text(self, text):
        self.set_value(self.sanitize(text))
        if self.on_change:
            self.on_change()

    def insert(self, text):
        self.set_text(self.value() + str(text or ""))

    def backspace(self):
        self.set_text(self.value()[:-1])

    def activate(self):
        self.active = True
        return None

    def adjust(self, step):
        return None

    def draw(self, surface, resources, palette, focused):
        label_color = palette["accent"] if focused else palette["text"]
        draw_text(surface, resources, _text_of(self.label), 20, label_color,
                  (self.rect.x + 14, self.rect.centery), anchor="midleft")
        box = pygame.Rect(self.rect.x + 235, self.rect.centery - 16,
                          self.rect.width - 315, 32)
        pygame.draw.rect(surface, (18, 26, 44), box, border_radius=8)
        pygame.draw.rect(surface, palette["accent"] if focused else palette["border"],
                         box, width=2 if focused else 1, border_radius=8)
        text = self.value()
        if text:
            draw_text(surface, resources, text, 15, palette["text"],
                      (box.x + 12, box.centery), anchor="midleft")
        else:
            draw_text(surface, resources, self.placeholder, 14, palette["muted"],
                      (box.x + 12, box.centery), anchor="midleft")
        if focused and (pygame.time.get_ticks() // 450) % 2 == 0:
            width = min(box.width - 24, resources.font(15).size(text)[0])
            caret_x = box.x + 12 + width + 1
            pygame.draw.line(surface, palette["accent"],
                             (caret_x, box.y + 7), (caret_x, box.bottom - 7), 2)


class WidgetGroup:
    """Keyboard + mouse focus management for a vertical list of widgets."""

    def __init__(self, widgets=None, on_hover=None):
        self.widgets = list(widgets or [])
        self.selected = 0
        self.on_hover = on_hover

    def add(self, widget):
        self.widgets.append(widget)
        return widget

    def _select(self, index):
        if not self.widgets:
            return
        new_index = index % len(self.widgets)
        if new_index != self.selected:
            self.selected = new_index
            if self.on_hover:
                self.on_hover()

    def _hit_index(self, mouse):
        for index, widget in enumerate(self.widgets):
            if widget.rect.collidepoint(mouse):
                return index
        return None

    def handle_event(self, event, mouse):
        if event.type == pygame.MOUSEMOTION:
            hit = self._hit_index(mouse)
            if hit is not None:
                self._select(hit)
            for widget in self.widgets:
                widget.hovered = widget.rect.collidepoint(mouse)
            for widget in self.widgets:
                if isinstance(widget, Slider) and widget.dragging:
                    widget.drag(mouse)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            hit = self._hit_index(mouse)
            if hit is not None:
                self._select(hit)
                widget = self.widgets[hit]
                if isinstance(widget, Slider):
                    widget.begin_drag(mouse)
                    if self.on_hover:
                        self.on_hover()
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            for widget in self.widgets:
                if isinstance(widget, Slider):
                    widget.dragging = False
            hit = self._hit_index(mouse)
            if hit is not None:
                widget = self.widgets[hit]
                if isinstance(widget, Button):
                    if self.on_hover:
                        self.on_hover()
                    return widget.action
                if self.on_hover:
                    self.on_hover()
                return widget.activate()
        elif event.type == pygame.TEXTINPUT:
            widget = self.widgets[self.selected] if self.widgets else None
            if isinstance(widget, TextInput):
                widget.insert(event.text)
            return None
        elif event.type == pygame.KEYDOWN:
            widget = self.widgets[self.selected] if self.widgets else None
            is_text = isinstance(widget, TextInput)
            if is_text:
                if event.key == pygame.K_BACKSPACE:
                    widget.backspace()
                    return None
                if event.key == pygame.K_DELETE:
                    widget.set_text("")
                    return None
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    # Enter moves to the next field/button instead of firing
                    # the field, so forms remain keyboard-only friendly.
                    self._select(self.selected + 1)
                    return None
                if event.key == pygame.K_SPACE:
                    return None
            if event.key in (pygame.K_UP, pygame.K_w) and not is_text:
                self._select(self.selected - 1)
            elif event.key in (pygame.K_DOWN, pygame.K_s) and not is_text:
                self._select(self.selected + 1)
            elif event.key == pygame.K_TAB:
                step = -1 if event.mod & pygame.KMOD_SHIFT else 1
                self._select(self.selected + step)
            elif event.key in (pygame.K_LEFT, pygame.K_a):
                widget = self.widgets[self.selected]
                if hasattr(widget, "adjust"):
                    widget.adjust(-1)
            elif event.key in (pygame.K_RIGHT, pygame.K_d):
                widget = self.widgets[self.selected]
                if hasattr(widget, "adjust"):
                    widget.adjust(1)
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                if self.widgets:
                    widget = self.widgets[self.selected]
                    if isinstance(widget, Button):
                        if self.on_hover:
                            self.on_hover()
                        return widget.action
                    return widget.activate()
        return None

    def draw(self, surface, resources, palette):
        for index, widget in enumerate(self.widgets):
            widget.draw(surface, resources, palette, index == self.selected)
