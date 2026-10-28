"""Protocol, co-op session, rendering and menu tests (headless SDL)."""

import json
import math
import os
import shutil
import socket
import struct
import tempfile
import time
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault(
    "SPACEGAME_CONFIG_DIR",
    tempfile.mkdtemp(prefix="spacegame-net-tests-"),
)

import pygame

from AppClass import App
from CampaignData import mission_by_id
from CampaignProgress import CampaignProgress
from CoopClientScene import CoopClientScene
from CoopGame import REVIVE_TIME, CoopHostGame, build_snapshot
from GameData import SHIPS
from GameProcessClass import GameProcess
from MenuClass import Menu
from NetCode import (MAX_FRAME_BYTES, ClientSession, HostSession, MessageBuffer,
                     ProtocolError, encode_message, validate_client_message,
                     validate_host_message)
from SettingsClass import DEFAULT_SETTINGS, Settings


def wait_until(predicate, timeout=6.0, interval=0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class ProtocolTests(unittest.TestCase):
    def test_roundtrip_and_partial_frames(self):
        first = encode_message({"t": "ping", "ts": 1.5})
        second = encode_message({"t": "leave", "reason": "bye"})
        buffer = MessageBuffer()
        decoded = []
        for byte in first + second:
            decoded.extend(buffer.feed(bytes([byte])))
        self.assertEqual(decoded, [{"t": "ping", "ts": 1.5},
                                   {"t": "leave", "reason": "bye"}])

    def test_bad_frames_are_rejected(self):
        with self.assertRaises(ProtocolError):
            encode_message(["not", "a", "dict"])
        with self.assertRaises(ProtocolError):
            encode_message({"t": "input", "x": float("nan")})
        buffer = MessageBuffer()
        with self.assertRaises(ProtocolError):
            buffer.feed(struct.pack("!I", MAX_FRAME_BYTES + 1))
        with self.assertRaises(ProtocolError):
            MessageBuffer().feed(b"\x00\x00\x00\x00")

    def test_client_messages_are_normalised(self):
        hello = validate_client_message({
            "t": "hello", "v": 1, "name": "  A\u0000ce  ", "ship": "tank",
        })
        self.assertEqual(hello["name"], "Ace")
        self.assertEqual(hello["ship"], "tank")
        with self.assertRaises(ProtocolError):
            validate_client_message({"t": "hello", "v": 99})
        with self.assertRaises(ProtocolError):
            validate_client_message({"t": "nope"})
        with self.assertRaises(ProtocolError):
            validate_client_message({"t": "input", "seq": True})
        with self.assertRaises(ProtocolError):
            validate_client_message({"t": "input", "x": float("inf")})
        move = validate_client_message({
            "t": "input", "seq": 7, "x": 4.5, "y": -9, "fire": 1,
        })
        self.assertEqual((move["seq"], move["x"], move["y"], move["fire"]),
                         (7, 1.0, -1.0, True))
        self.assertEqual(validate_client_message({"t": "story_skip"}),
                         {"t": "story_skip"})

    def test_host_messages_are_normalised(self):
        start = validate_host_message({
            "t": "start", "mode": "meme", "difficulty": "hard",
            "mission": "m02", "host_name": "H", "client_name": "C",
            "host_ship": "tank", "client_ship": "bad",
        })
        self.assertEqual(start["mode"], "meme")
        self.assertEqual(start["client_ship"], "fighter")
        self.assertEqual(start["mission"], "m02")
        with self.assertRaises(ProtocolError):
            validate_host_message({"t": "state", "state": []})
        with self.assertRaises(ProtocolError):
            validate_host_message({"t": "bogus"})
        error = validate_host_message({
            "t": "error", "code": "busy", "message": "full",
        })
        self.assertEqual(error["code"], "busy")


class LoopbackSessionTests(unittest.TestCase):
    def setUp(self):
        self.host = HostSession(0, "HostPilot")
        port = self.host.start()
        self.assertGreater(port, 0)
        self.client = ClientSession("127.0.0.1", port, "ClientPilot",
                                    "interceptor")
        self.client.connect()
        self.assertTrue(wait_until(
            lambda: self.host.connected and self.client.connected))
        self.addCleanup(self.client.close)
        self.addCleanup(self.host.close)

    @staticmethod
    def drain(session, kind=None, timeout=4.0):
        found = []
        def poll():
            for message in session.poll():
                found.append(message)
                if kind is None or message.get("t") == kind:
                    return True
            return False
        wait_until(poll, timeout)
        return found

    def test_handshake_and_names(self):
        self.assertEqual(self.host.client_name, "ClientPilot")
        self.assertEqual(self.host.client_ship, "interceptor")

    def test_input_and_state_exchange(self):
        self.client.send_input(0.5, -0.25, True, force=True)
        self.assertTrue(wait_until(lambda: self.host.input()[2]))
        x, y, fire = self.host.input()
        self.assertAlmostEqual(x, 0.5)
        self.assertAlmostEqual(y, -0.25)
        self.assertTrue(fire)

        self.host.send_state({"score": 42, "state": "playing"})
        messages = self.drain(self.client, "state")
        states = [m for m in messages if m.get("t") == "state"]
        self.assertTrue(states)
        self.assertEqual(states[-1]["state"]["score"], 42)

        self.host.send_start(mode="normal", difficulty="hard",
                             host_name="HostPilot", client_name="ClientPilot",
                             host_ship="fighter", client_ship="interceptor")
        messages = self.drain(self.client, "start")
        starts = [m for m in messages if m.get("t") == "start"]
        self.assertTrue(starts)
        self.assertEqual(starts[-1]["difficulty"], "hard")

    def test_leave_notifies_host(self):
        self.client.send_leave("done")
        messages = self.drain(self.host, "peer_left")
        left = [m for m in messages if m.get("t") == "peer_left"]
        self.assertTrue(left)
        self.assertEqual(left[-1]["reason"], "done")


class FakeHostSession:
    host_name = "HostPilot"
    client_name = "ClientPilot"
    client_ship = "tank"
    connected = True

    def __init__(self, messages=None):
        self.messages = list(messages or [])
        self.sent = []
        self._input = (0.25, -0.5, True)
        self.closed = False

    def poll(self):
        messages = self.messages
        self.messages = []
        return messages

    def input(self):
        return self._input

    def reset_input(self):
        self._input = (0.0, 0.0, False)

    def send_state(self, state):
        self.sent.append(("state", state))

    def send_start(self, **info):
        self.sent.append(("start", info))

    def send_result(self, result):
        self.sent.append(("result", result))

    def send(self, message):
        self.sent.append((message.get("t"), message))

    def send_leave(self, reason="host left"):
        self.sent.append(("leave", {"reason": reason}))
        self.closed = True

    def close(self):
        self.closed = True


class FakeClientSession:
    connected = True

    def __init__(self, messages=None):
        self.messages = list(messages or [])
        self.sent = []
        self.closed = False

    def poll(self):
        messages = self.messages
        self.messages = []
        return messages

    def send_input(self, x, y, fire, force=False):
        self.sent.append(("input", (x, y, fire)))
        return True

    def send_pause_request(self):
        self.sent.append(("pause", None))

    def send_story_skip(self):
        self.sent.append(("story_skip", None))

    def send_leave(self, reason="left"):
        self.sent.append(("leave", reason))
        self.closed = True

    def heartbeat(self):
        pass

    def close(self):
        self.closed = True


class CoopTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.app = App(force_windowed=True)
        cls.app.settings.ship = "fighter"
        cls.app.resources.select_ship("fighter")

    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="spacegame-coop-")
        self.addCleanup(shutil.rmtree, self.tempdir, True)

    def make_coop(self, session=None, **kwargs):
        session = session or FakeHostSession()
        game = CoopHostGame(self.app, session, **kwargs)
        self.addCleanup(game.on_exit)
        return game

    def make_campaign_coop(self, mission_id="m01"):
        progress = CampaignProgress(path=os.path.join(self.tempdir,
                                                      "campaign.json"))
        mission = mission_by_id(mission_id)
        game = self.make_coop(mission=mission, progress=progress)
        return game, progress, mission


class CoopHostTests(CoopTestCase):
    def test_snapshot_is_json_safe_and_has_two_players(self):
        game = self.make_coop()
        game.state = "playing"
        game.score = 123
        snapshot = build_snapshot(game, ("HostPilot", "ClientPilot"))
        self.assertEqual(len(snapshot["players"]), 2)
        self.assertEqual(snapshot["players"][0]["name"], "HostPilot")
        self.assertEqual(snapshot["players"][1]["ship"], "tank")
        self.assertTrue(snapshot["players"][1]["alive"])
        payload = encode_message({"t": "state", "state": snapshot})
        self.assertGreater(len(payload), 4)
        decoded = MessageBuffer().feed(payload)
        self.assertEqual(decoded[0]["state"]["score"], 123)

    def test_snapshot_limits_lists(self):
        game = self.make_coop()
        game.state = "playing"
        snapshot = build_snapshot(game, ("H", "C"))
        self.assertLessEqual(len(snapshot["enemies"]), 24)
        self.assertLessEqual(len(snapshot["player_bullets"]), 110)
        self.assertLessEqual(len(snapshot["enemy_bullets"]), 220)

    def test_upgrades_apply_to_both_ships(self):
        game = self.make_coop()
        game.salvage = 5000
        game.upgrade_choices = [("damage", 100)]
        game.state = "upgrade"
        before = game.player.upgrade_level("damage")
        game._apply_upgrade(0)
        self.assertEqual(game.player.upgrade_level("damage"), before + 1)
        self.assertEqual(game.player2.upgrade_level("damage"), before + 1)
        self.assertLess(game.salvage, 5000)

    def test_partner_revives_when_close(self):
        game = self.make_coop()
        game.state = "playing"
        game.player2.life = 0
        game.player2.alive = False
        game.player2.downed = True
        game.player2.revive_progress = 0.0
        game.player.posX = game.player2.posX
        game.player.posY = game.player2.posY
        game._update_revives(REVIVE_TIME + 0.2)
        self.assertFalse(game.player2.downed)
        self.assertTrue(game.player2.alive)
        self.assertGreater(game.player2.invulnerable_timer, 0)

    def test_partner_does_not_revive_from_far_away(self):
        game = self.make_coop()
        game.state = "playing"
        game.player2.life = 0
        game.player2.alive = False
        game.player2.downed = True
        game.player.posX = 80
        game.player.posY = 100
        game.player2.posX = 1100
        game.player2.posY = 640
        game._update_revives(1.0)
        self.assertTrue(game.player2.downed)

    def test_wave_change_revives_down_ship(self):
        game = self.make_coop()
        game.state = "playing"
        game.player2.life = 0
        game.player2.alive = False
        game.player2.downed = True
        game._revive_at_wave()
        self.assertFalse(game.player2.downed)
        self.assertEqual(game.player2.life, 1)

    def test_one_respawning_ship_does_not_end_run(self):
        game = self.make_coop()
        game.state = "playing"
        game.player.life = 0
        game.player.alive = False
        game.player.downed = True
        game.player2.life = 2
        game.player2.alive = False
        game.player2.downed = False
        game._check_run_end()
        self.assertEqual(game.state, "playing")

    def test_both_downed_ends_run(self):
        game = self.make_coop()
        game.state = "playing"
        for player in game.players:
            player.life = 0
            player.alive = False
            player.downed = True
        game._check_run_end()
        self.assertEqual(game.state, "dying")

    def test_client_input_drives_second_ship(self):
        game = self.make_coop()
        self.assertEqual(game._input_for(game.player2), (0.25, -0.5, True))
        game.net._input = (0.0, 0.0, False)
        self.assertEqual(game._input_for(game.player2), (0.0, 0.0, False))

    def test_disconnect_can_continue_solo(self):
        game = self.make_coop()
        game.state = "playing"
        game._peer_disconnected("gone")
        self.assertEqual(game.state, "disconnected")
        self.assertTrue(game.peer_left)
        game._continue_solo()
        self.assertEqual(game.state, "playing")
        self.assertEqual(game.players, [game.player])
        self.assertFalse(game.coop)
        self.assertIsNone(game.net)
        self.assertFalse(game.peer_left)

    def test_result_is_sent_to_client(self):
        game = self.make_coop()
        game.state = "gameover"
        game.result = {"score": 90, "kills": 4, "time": 12.0, "wave": 3}
        game._send_result()
        kinds = [kind for kind, _payload in game.net.sent]
        self.assertIn("result", kinds)
        result = [payload for kind, payload in game.net.sent
                  if kind == "result"][-1]
        self.assertEqual(result["score"], 90)
        self.assertTrue(result["campaign"] is False)

    def test_story_skip_from_client_advances_host(self):
        game, _progress, mission = self.make_campaign_coop()
        game.state = "story"
        game.story_index = 0
        self.assertGreater(len(game.story_keys), 1)
        game.net.messages = [{"t": "peer_story_skip"}]
        game._poll_network()
        self.assertGreaterEqual(game.story_index, 1)

    def test_campaign_snapshot_reports_mission(self):
        game, _progress, mission = self.make_campaign_coop()
        game.state = "playing"
        snapshot = build_snapshot(game, ("H", "C"))
        self.assertTrue(snapshot["campaign"])
        self.assertEqual(snapshot["mission"], mission["id"])
        self.assertEqual(snapshot["mission_name"], mission["name_key"])

    def test_host_completes_campaign_and_sends_summary(self):
        game, progress, mission = self.make_campaign_coop()
        game.score = 4321
        game.kills = 12
        game.game_time = 30.0
        game._complete_mission()
        self.assertEqual(game.state, "victory")
        self.assertTrue(progress.is_completed(mission["id"]))
        self.assertEqual(progress.best_for(mission["id"])["score"], 4321)
        game._send_result()
        result = [payload for kind, payload in game.net.sent
                  if kind == "result"][-1]
        self.assertTrue(result["campaign"])
        self.assertEqual(result["mission"], mission["name_key"])
        self.assertFalse(result["campaign_complete"])
        self.assertIsInstance(result["summary"], dict)
        self.assertTrue(result["summary"]["first_completion"])

    def test_campaign_game_over_uses_shared_progress(self):
        game, progress, mission = self.make_campaign_coop()
        game.player.life = 0
        game.player.alive = False
        game._finalize_game_over()
        self.assertEqual(game.state, "gameover")
        self.assertFalse(progress.is_completed(mission["id"]))



class CoopClientTests(CoopTestCase):
    def make_scene(self, messages=None):
        session = FakeClientSession(messages)
        scene = CoopClientScene(self.app, session, {
            "mode": "normal", "difficulty": "normal",
            "host_name": "HostPilot", "client_name": "ClientPilot",
            "host_ship": "fighter", "client_ship": "tank",
        })
        self.addCleanup(scene.on_exit)
        return scene, session

    def build_live_snapshot(self):
        host = self.make_coop()
        host.state = "playing"
        host.score = 77
        return build_snapshot(host, ("HostPilot", "ClientPilot"))

    def test_renders_snapshot_and_hud(self):
        scene, _session = self.make_scene()
        scene._apply_snapshot(self.build_live_snapshot())
        self.assertEqual(scene.state, "playing")
        self.assertEqual(scene.snapshot["score"], 77)
        scene.update(1 / 60)
        scene.draw(self.app.canvas)
        self.assertEqual(len(scene.snapshot["players"]), 2)

    def test_result_overlay_and_local_menu_draw(self):
        scene, _session = self.make_scene()
        scene._apply_snapshot(self.build_live_snapshot())
        scene._apply_result({
            "state": "gameover", "score": 10, "kills": 2, "time": 5.0,
            "wave": 2, "campaign": False,
        })
        self.assertEqual(scene.state, "gameover")
        scene.draw(self.app.canvas)
        self.assertTrue(scene._overlay_buttons)
        scene._set_state("playing")
        scene.local_menu = True
        scene.draw(self.app.canvas)
        self.assertTrue(scene.local_menu)

    def test_start_message_updates_identity(self):
        scene, _session = self.make_scene()
        scene._poll_network()
        scene.net.messages = [{
            "t": "start", "mode": "meme", "difficulty": "hard",
            "host_name": "NewHost", "client_name": "NewClient",
            "host_ship": "tank", "client_ship": "fighter", "mission": "m03",
        }]
        scene._poll_network()
        self.assertEqual(scene.mode, "meme")
        self.assertEqual(scene.host_name, "NewHost")
        self.assertEqual(scene.mission_id, "m03")

    def test_story_skip_and_pause_requests_are_sent(self):
        scene, session = self.make_scene()
        scene._set_state("story")
        scene.handle_event(pygame.event.Event(
            pygame.KEYDOWN, key=pygame.K_RETURN, mod=0))
        self.assertIn("story_skip", [kind for kind, _ in session.sent])
        scene._set_state("playing")
        scene.handle_event(pygame.event.Event(
            pygame.KEYDOWN, key=pygame.K_p, mod=0))
        self.assertIn("pause", [kind for kind, _ in session.sent])

    def test_client_is_not_a_simulation(self):
        scene, _session = self.make_scene()
        self.assertNotIsInstance(scene, GameProcess)


class SettingsV6Tests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="spacegame-settings-")
        self.addCleanup(shutil.rmtree, self.tempdir, True)
        self.path = os.path.join(self.tempdir, "settings.json")

    def test_version_five_gains_multiplayer_defaults(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump({"version": 5, "music_volume": 0.3}, handle)
        settings = Settings.load(self.path)
        self.assertEqual(settings.version, 6)
        self.assertEqual(settings.player_name, DEFAULT_SETTINGS["player_name"])
        self.assertEqual(settings.last_host, DEFAULT_SETTINGS["last_host"])
        self.assertEqual(settings.last_port, DEFAULT_SETTINGS["last_port"])

    def test_multiplayer_fields_roundtrip_and_sanitize(self):
        settings = Settings({
            "player_name": "  Nova\u0000  ",
            "last_host": " 192.168.1.20 ",
            "last_port": "not a port",
        })
        self.assertEqual(settings.player_name, "Nova")
        self.assertEqual(settings.last_host, "192.168.1.20")
        self.assertEqual(settings.last_port, DEFAULT_SETTINGS["last_port"])
        settings.last_port = 50000
        settings.save(self.path)
        loaded = Settings.load(self.path)
        self.assertEqual(loaded.player_name, "Nova")
        self.assertEqual(loaded.last_host, "192.168.1.20")
        self.assertEqual(loaded.last_port, 50000)

    def test_out_of_range_port_falls_back(self):
        self.assertEqual(Settings({"last_port": 0}).last_port,
                         DEFAULT_SETTINGS["last_port"])
        self.assertEqual(Settings({"last_port": 90000}).last_port,
                         DEFAULT_SETTINGS["last_port"])
        self.assertEqual(Settings({"last_port": True}).last_port,
                         DEFAULT_SETTINGS["last_port"])

    def test_address_rejects_control_characters(self):
        settings = Settings({"last_host": "1.2.3.4\nrm -rf /"})
        self.assertNotIn("\n", settings.last_host)
        self.assertTrue(settings.last_host.startswith("1.2.3.4"))


class MenuMultiplayerTests(CoopTestCase):
    def make_menu(self):
        menu = Menu(self.app)
        self.addCleanup(menu.on_exit)
        return menu

    def test_screens_are_available(self):
        menu = self.make_menu()
        for screen in ("multiplayer", "mp_host", "mp_join"):
            menu._set_screen(screen)
            menu.update(1 / 60)
            menu.draw(self.app.canvas)
            self.assertIsNotNone(menu.widgets)

    def test_invalid_port_shows_error_without_session(self):
        menu = self.make_menu()
        menu._set_screen("mp_host")
        menu.mp_form_port = "999999"
        menu._begin_host()
        self.assertIsNone(menu.mp_session)
        self.assertTrue(menu.mp_error)
        self.assertEqual(menu.screen, "mp_host")
        menu.draw(self.app.canvas)

    def test_loopback_lobby_hands_session_to_host_scene(self):
        menu = Menu(self.app)
        original_scene = self.app.scene
        self.addCleanup(self._restore_scene, original_scene)

        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()

        menu._set_screen("mp_host")
        menu.mp_form_name = "HostPilot"
        menu.mp_form_port = str(port)
        menu._begin_host()
        self.assertEqual(menu.screen, "mp_lobby")
        self.assertIsNotNone(menu.mp_session)

        client = ClientSession("127.0.0.1", port, "ClientPilot", "engineer")
        client.connect()
        self.addCleanup(client.close)
        self.assertTrue(wait_until(lambda: (
            menu.update(1 / 60) or menu.mp_connected)))
        self.assertEqual(menu.mp_peer_name, "ClientPilot")

        menu._start_coop_run()
        self.assertTrue(menu.mp_handed_off)
        self.app.fade.update(1.0)
        self.assertIsInstance(self.app.scene, CoopHostGame)
        scene = self.app.scene
        scene.update(1 / 60)
        scene.draw(self.app.canvas)

        start_info = None
        def got_start():
            nonlocal start_info
            for message in client.poll():
                if message.get("t") == "start":
                    start_info = message
            return start_info is not None
        self.assertTrue(wait_until(got_start))
        self.assertEqual(start_info["client_name"], "ClientPilot")
        self.assertEqual(start_info["client_ship"], "engineer")

    def _restore_scene(self, scene):
        try:
            self.app.scene.on_exit()
        except (AttributeError, pygame.error):
            pass
        self.app.scene = scene

    def test_campaign_selection_starts_coop_mission(self):
        menu = self.make_menu()
        original_scene = self.app.scene
        self.addCleanup(self._restore_scene, original_scene)
        menu._set_screen("mp_host")
        menu._set_mp_run_type(1)
        self.assertEqual(menu.mp_run_type, "campaign")
        self.assertIn("m01", menu.mp_mission_ids)
        menu.draw(self.app.canvas)
        menu.mp_mission_id = "m01"
        menu.mp_session = FakeHostSession()
        menu.mp_role = "host"
        menu.mp_connected = True
        menu._start_coop_run()
        self.assertTrue(menu.mp_handed_off)
        self.app.fade.update(1.0)
        scene = self.app.scene
        self.assertIsInstance(scene, CoopHostGame)
        self.assertTrue(scene.campaign)
        self.assertEqual(scene.campaign_mission["id"], "m01")
        self.assertEqual(self.app.campaign_progress.last_mission, "m01")
        snapshot = build_snapshot(scene, ("HostPilot", "ClientPilot"))
        self.assertEqual(snapshot["mission"], "m01")

    def test_locked_campaign_mission_is_refused(self):
        menu = self.make_menu()
        original_scene = self.app.scene
        self.addCleanup(self._restore_scene, original_scene)
        menu._set_screen("mp_host")
        menu.mp_run_type = "campaign"
        menu.mp_mission_id = "m02"
        menu.mp_session = FakeHostSession()
        menu.mp_role = "host"
        menu.mp_connected = True
        menu._start_coop_run()
        self.assertFalse(menu.mp_handed_off)
        self.assertTrue(menu.mp_error)
        self.assertIs(self.app.scene, original_scene)


if __name__ == "__main__":
    unittest.main()
