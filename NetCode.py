"""Host-authoritative two-player networking for SpaceGame 2.1.

The transport is plain TCP with length-prefixed UTF-8 JSON frames.  No pickle
is used anywhere.  The host owns the simulation; the client sends small input
messages and renders snapshots.  All socket work happens on background daemon
threads so the pygame main loop never blocks.

Security posture (LAN / trusted VPN co-op):
* every frame has a hard size limit and the receive buffer is bounded;
* every message is parsed as a JSON object and validated by type;
* names and free-form strings are length-limited and control characters are
  stripped;
* numeric input is clamped and non-finite numbers are rejected;
* a peer that floods, stalls or stays silent is disconnected.
"""

from __future__ import annotations

import json
import math
import queue
import socket
import struct
import threading
import time

from GameData import SHIP_ORDER

PROTOCOL_VERSION = 1
DEFAULT_PORT = 47521
MAX_FRAME_BYTES = 96 * 1024
MAX_BUFFER_BYTES = 512 * 1024
MAX_SEND_QUEUE = 12
MAX_INBOX = 256
CONNECT_TIMEOUT = 6.0
HANDSHAKE_TIMEOUT = 8.0
IDLE_TIMEOUT = 15.0
SOCKET_POLL = 0.25
MAX_NAME_LEN = 24
MAX_REASON_LEN = 80
MAX_MESSAGES_PER_SECOND = 240

CLIENT_MESSAGE_TYPES = frozenset(
    {"hello", "input", "ping", "pong", "leave", "pause_request",
     "story_skip", "superpower"}
)
HOST_MESSAGE_TYPES = frozenset(
    {"welcome", "start", "state", "result", "ping", "pong", "error", "leave"}
)


class ProtocolError(ValueError):
    """Raised for malformed, oversized or disallowed network messages."""


def _finite(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ProtocolError("expected a number")
    if not math.isfinite(number):
        raise ProtocolError("non-finite number")
    return number


def _clean_text(value, limit, default=""):
    if not isinstance(value, str):
        return default
    cleaned = "".join(ch for ch in value if ch.isprintable()).strip()
    return cleaned[:limit] or default


def _clamp(value, low, high):
    return max(low, min(high, value))


def encode_message(message):
    """Serialize one message with a four-byte big-endian length prefix."""
    if not isinstance(message, dict):
        raise ProtocolError("message must be an object")
    try:
        payload = json.dumps(
            message, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProtocolError("message is not JSON serialisable") from exc
    if not payload or len(payload) > MAX_FRAME_BYTES:
        raise ProtocolError("frame is too large")
    return struct.pack("!I", len(payload)) + payload


class MessageBuffer:
    """Incremental decoder for length-prefixed frames."""

    def __init__(self, max_frame=MAX_FRAME_BYTES, max_buffer=MAX_BUFFER_BYTES):
        self.max_frame = max_frame
        self.max_buffer = max_buffer
        self._buffer = bytearray()

    def feed(self, chunk):
        if not isinstance(chunk, (bytes, bytearray)):
            raise ProtocolError("chunk must be bytes")
        self._buffer.extend(chunk)
        if len(self._buffer) > self.max_buffer:
            raise ProtocolError("receive buffer overflow")
        messages = []
        while len(self._buffer) >= 4:
            length = struct.unpack("!I", self._buffer[:4])[0]
            if length == 0 or length > self.max_frame:
                raise ProtocolError("bad frame length")
            if len(self._buffer) < 4 + length:
                break
            payload = bytes(self._buffer[4:4 + length])
            del self._buffer[:4 + length]
            try:
                message = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise ProtocolError("invalid JSON frame") from exc
            if not isinstance(message, dict):
                raise ProtocolError("frame must be a JSON object")
            messages.append(message)
        return messages

    def reset(self):
        self._buffer.clear()


def validate_client_message(message):
    """Validate a client -> host message and return a normalised copy."""
    if not isinstance(message, dict):
        raise ProtocolError("message must be an object")
    kind = message.get("t")
    if kind not in CLIENT_MESSAGE_TYPES:
        raise ProtocolError("unknown client message")
    if kind == "hello":
        if message.get("v") != PROTOCOL_VERSION:
            raise ProtocolError("protocol mismatch")
        return {
            "t": "hello",
            "v": PROTOCOL_VERSION,
            "name": _clean_text(message.get("name"), MAX_NAME_LEN, "Pilot"),
            "ship": (message.get("ship") if message.get("ship") in SHIP_ORDER
                     else "fighter"),
        }
    if kind == "input":
        sequence = message.get("seq", 0)
        if isinstance(sequence, bool) or not isinstance(sequence, int):
            raise ProtocolError("bad input sequence")
        sequence = _clamp(sequence, 0, 2 ** 31 - 1)
        x = _clamp(_finite(message.get("x", 0.0)), -1.0, 1.0)
        y = _clamp(_finite(message.get("y", 0.0)), -1.0, 1.0)
        return {
            "t": "input",
            "seq": sequence,
            "x": x,
            "y": y,
            "fire": bool(message.get("fire", False)),
        }
    if kind in ("ping", "pong"):
        return {"t": kind, "ts": _finite(message.get("ts", 0.0))}
    if kind == "leave":
        return {"t": "leave",
                "reason": _clean_text(message.get("reason"), MAX_REASON_LEN,
                                      "left")}
    if kind == "story_skip":
        return {"t": "story_skip"}
    if kind == "superpower":
        power = message.get("kind")
        if power not in ("tiger", "chainsaw"):
            raise ProtocolError("unknown superpower")
        return {"t": "superpower", "kind": power}
    return {"t": "pause_request"}


def validate_host_message(message):
    """Validate a host -> client message; state payloads are kept intact."""
    if not isinstance(message, dict):
        raise ProtocolError("message must be an object")
    kind = message.get("t")
    if kind not in HOST_MESSAGE_TYPES:
        raise ProtocolError("unknown host message")
    if kind == "welcome":
        return {
            "t": "welcome",
            "v": PROTOCOL_VERSION,
            "you": 1,
            "host_name": _clean_text(message.get("host_name"), MAX_NAME_LEN,
                                     "Host"),
        }
    if kind == "start":
        return {
            "t": "start",
            "mode": ("meme" if message.get("mode") == "meme" else "normal"),
            "difficulty": _clean_text(message.get("difficulty"), 16, "normal"),
            "mission": (message.get("mission")
                        if isinstance(message.get("mission"), str) else None),
            "host_name": _clean_text(message.get("host_name"), MAX_NAME_LEN,
                                     "Host"),
            "client_name": _clean_text(message.get("client_name"),
                                       MAX_NAME_LEN, "Pilot"),
            "host_ship": (message.get("host_ship")
                          if message.get("host_ship") in SHIP_ORDER
                          else "fighter"),
            "client_ship": (message.get("client_ship")
                            if message.get("client_ship") in SHIP_ORDER
                            else "fighter"),
        }
    if kind == "state":
        state = message.get("state")
        if not isinstance(state, dict):
            raise ProtocolError("state must be an object")
        return {"t": "state", "state": state}
    if kind == "result":
        result = message.get("result")
        if not isinstance(result, dict):
            raise ProtocolError("result must be an object")
        return {"t": "result", "result": result}
    if kind in ("ping", "pong"):
        return {"t": kind, "ts": _finite(message.get("ts", 0.0))}
    if kind == "error":
        return {"t": "error",
                "code": _clean_text(message.get("code"), 24, "error"),
                "message": _clean_text(message.get("message"), 120,
                                       "Connection error")}
    return {"t": "leave",
            "reason": _clean_text(message.get("reason"), MAX_REASON_LEN,
                                  "host closed the session")}


def local_ip():
    """Best-effort LAN address for the host screen (no packets are sent)."""
    probe = None
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    finally:
        if probe is not None:
            probe.close()


class _BaseSession:
    """Shared queues, polling and shutdown behaviour for both roles."""

    role = "base"

    def __init__(self):
        self._inbox = queue.Queue(maxsize=MAX_INBOX)
        self._send_queue = queue.Queue(maxsize=MAX_SEND_QUEUE)
        self._stop = threading.Event()
        self._threads = []
        self._send_thread = None
        self._state_lock = threading.Lock()
        self._state = "idle"
        self._error = ""
        self._last_rx = time.monotonic()
        self._closed = False

    # ------------------------------------------------------------------ state
    @property
    def state(self):
        with self._state_lock:
            return self._state

    @property
    def error(self):
        with self._state_lock:
            return self._error

    @property
    def connected(self):
        return self.state == "connected"

    def _set_state(self, state, error=""):
        with self._state_lock:
            self._state = state
            if error:
                self._error = error
        if state in ("error", "closed"):
            self._closed = True

    def _post(self, message):
        try:
            self._inbox.put_nowait(message)
        except queue.Full:
            try:
                self._inbox.get_nowait()
            except queue.Empty:
                pass
            try:
                self._inbox.put_nowait(message)
            except queue.Full:
                pass

    def poll(self):
        """Return queued events/messages without blocking."""
        messages = []
        while True:
            try:
                messages.append(self._inbox.get_nowait())
            except queue.Empty:
                break
        return messages

    # ------------------------------------------------------------------- send
    def _queue_message(self, message):
        try:
            encoded = encode_message(message)
        except ProtocolError as exc:
            self._set_state("error", str(exc))
            self._post({"t": "error", "code": "protocol",
                        "message": str(exc)})
            return False
        try:
            self._send_queue.put_nowait(encoded)
        except queue.Full:
            # Never let a slow peer stall the simulation: drop the oldest
            # snapshot and keep the newest one.
            try:
                self._send_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._send_queue.put_nowait(encoded)
            except queue.Full:
                pass
        return True

    def _sender_loop(self, sock):
        while not self._stop.is_set():
            try:
                payload = self._send_queue.get(timeout=SOCKET_POLL)
            except queue.Empty:
                continue
            try:
                sock.sendall(payload)
            except OSError as exc:
                self._fail("send failed: %s" % exc)
                return

    # --------------------------------------------------------------- shutdown
    def _fail(self, reason):
        if self._closed:
            return
        self._set_state("error", reason)
        self._post({"t": "error", "code": "connection",
                    "message": reason})
        self.close()

    def _close_sockets(self):
        raise NotImplementedError

    def close(self):
        if self._stop.is_set() and self._closed:
            self._close_sockets()
            return
        self._stop.set()
        try:
            self._close_sockets()
        except OSError:
            pass
        for thread in list(self._threads):
            if thread is not threading.current_thread():
                thread.join(timeout=0.6)
        self._threads.clear()
        if self.state != "error":
            self._set_state("closed")

    def _start_sender(self, sock):
        self._send_thread = threading.Thread(
            target=self._sender_loop, args=(sock,),
            name="spacegame-%s-sender" % self.role, daemon=True,
        )
        self._threads.append(self._send_thread)
        self._send_thread.start()

    def _idle_expired(self):
        return time.monotonic() - self._last_rx > IDLE_TIMEOUT

    def heartbeat(self):
        """Keep an idle lobby connection alive (called from the UI loop)."""
        now = time.monotonic()
        if not hasattr(self, "_last_heartbeat"):
            self._last_heartbeat = 0.0
        if now - self._last_heartbeat < 3.0:
            return
        self._last_heartbeat = now
        self.send({"t": "ping", "ts": now})


class HostSession(_BaseSession):
    """Listens for exactly one client and exposes the latest input."""

    role = "host"

    def __init__(self, port=DEFAULT_PORT, host_name="Host"):
        super().__init__()
        self.port = int(port)
        self.host_name = _clean_text(host_name, MAX_NAME_LEN, "Host")
        self._listener = None
        self._client = None
        self._input_lock = threading.Lock()
        self._latest_input = (0.0, 0.0, False, -1)
        self._hello_deadline = 0.0
        self._authenticated = False
        self.client_name = ""
        self.client_ship = "fighter"

    # ------------------------------------------------------------------ setup
    def start(self):
        if self._listener is not None:
            return self.port
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(("0.0.0.0", self.port))
            listener.listen(2)
            listener.setblocking(False)
        except OSError as exc:
            listener.close()
            self._set_state("error", "cannot listen: %s" % exc)
            return 0
        self.port = listener.getsockname()[1]
        self._listener = listener
        self._set_state("listening")
        thread = threading.Thread(target=self._accept_loop,
                                  name="spacegame-host-accept", daemon=True)
        self._threads.append(thread)
        thread.start()
        return self.port

    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                client, address = self._listener.accept()
            except BlockingIOError:
                time.sleep(0.05)
                continue
            except OSError as exc:
                if not self._stop.is_set():
                    self._fail("accept failed: %s" % exc)
                return
            except Exception:
                time.sleep(0.05)
                continue
            if self._client is not None:
                try:
                    client.settimeout(SOCKET_POLL)
                    client.sendall(encode_message({
                        "t": "error", "code": "busy",
                        "message": "This host already has a partner.",
                    }))
                    client.shutdown(socket.SHUT_WR)
                    # Consume the joining client's hello before closing. If
                    # unread client data remains, some TCP stacks reset the
                    # connection and discard our useful busy response.
                    while client.recv(4096):
                        pass
                except (OSError, socket.timeout):
                    pass
                client.close()
                continue
            self._client = client
            try:
                client.settimeout(SOCKET_POLL)
            except OSError:
                pass
            self._last_rx = time.monotonic()
            self._hello_deadline = self._last_rx + HANDSHAKE_TIMEOUT
            self._start_sender(client)
            reader = threading.Thread(target=self._reader_loop, args=(client,),
                                      name="spacegame-host-reader", daemon=True)
            self._threads.append(reader)
            reader.start()

    def _reader_loop(self, client):
        decoder = MessageBuffer()
        seen = 0
        window_start = time.monotonic()
        try:
            while not self._stop.is_set():
                try:
                    chunk = client.recv(8192)
                except socket.timeout:
                    if (not self._authenticated
                            and time.monotonic() > self._hello_deadline):
                        self._fail("client handshake timed out")
                        return
                    if self._authenticated and self._idle_expired():
                        self._fail("client timed out")
                        return
                    continue
                except OSError as exc:
                    if not self._stop.is_set():
                        self._fail("receive failed: %s" % exc)
                    return
                if not chunk:
                    self._fail("client disconnected")
                    return
                self._last_rx = time.monotonic()
                try:
                    messages = decoder.feed(chunk)
                except ProtocolError as exc:
                    self._fail("bad frame: %s" % exc)
                    return
                for raw in messages:
                    try:
                        message = validate_client_message(raw)
                    except ProtocolError as exc:
                        self._fail("invalid message: %s" % exc)
                        return
                    seen += 1
                    now = time.monotonic()
                    if now - window_start >= 1.0:
                        if seen > MAX_MESSAGES_PER_SECOND:
                            self._fail("client message flood")
                            return
                        seen = 0
                        window_start = now
                    if message["t"] == "hello":
                        if self._authenticated:
                            continue
                        self._authenticated = True
                        self.client_name = message["name"]
                        self.client_ship = message["ship"]
                        self._set_state("connected")
                        self._queue_message({
                            "t": "welcome", "v": PROTOCOL_VERSION, "you": 1,
                            "host_name": self.host_name,
                        })
                        self._post({"t": "peer_joined",
                                    "name": self.client_name,
                                    "ship": self.client_ship})
                    elif not self._authenticated:
                        self._fail("expected hello")
                        return
                    elif message["t"] == "input":
                        with self._input_lock:
                            if message["seq"] >= self._latest_input[3]:
                                self._latest_input = (
                                    message["x"], message["y"],
                                    message["fire"], message["seq"],
                                )
                    elif message["t"] == "leave":
                        self._post({"t": "peer_left",
                                    "reason": message["reason"]})
                        self._fail("client left")
                        return
                    elif message["t"] == "ping":
                        self._queue_message({"t": "pong", "ts": message["ts"]})
                    elif message["t"] == "pause_request":
                        self._post({"t": "pause_request"})
                    elif message["t"] == "story_skip":
                        self._post({"t": "peer_story_skip"})
                    elif message["t"] == "superpower":
                        self._post({"t": "superpower",
                                    "kind": message["kind"]})
        finally:
            if not self._closed and not self._stop.is_set():
                self._fail("connection closed")

    # ----------------------------------------------------------------- public
    def input(self):
        with self._input_lock:
            x, y, fire, _ = self._latest_input
        return x, y, fire

    def reset_input(self):
        with self._input_lock:
            self._latest_input = (0.0, 0.0, False, -1)

    def send(self, message):
        if not self.connected:
            return False
        return self._queue_message(message)

    def send_state(self, state):
        return self.send({"t": "state", "state": state})

    def send_start(self, **info):
        return self.send({"t": "start", **info})

    def send_result(self, result):
        return self.send({"t": "result", "result": result})

    def send_leave(self, reason="host left"):
        try:
            if self.connected:
                self.send({"t": "leave",
                           "reason": _clean_text(reason, MAX_REASON_LEN,
                                                 "host left")})
                time.sleep(0.05)
        finally:
            self.close()

    def _close_sockets(self):
        for sock in (self._client, self._listener):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        self._client = None
        self._listener = None


class ClientSession(_BaseSession):
    """Connects to one host, sends inputs and receives snapshots."""

    role = "client"

    def __init__(self, host, port=DEFAULT_PORT, name="Pilot",
                 ship="fighter"):
        super().__init__()
        self.host = _clean_text(host, 64, "127.0.0.1")
        self.port = int(port)
        self.name = _clean_text(name, MAX_NAME_LEN, "Pilot")
        self.ship = ship if ship in SHIP_ORDER else "fighter"
        self._socket = None
        self._input_seq = 0
        self._last_input = 0.0
        self._connect_thread = None
        self._handshake_deadline = 0.0

    # ------------------------------------------------------------------ setup
    def connect(self):
        if self._connect_thread is not None:
            return
        self._set_state("connecting")
        self._connect_thread = threading.Thread(
            target=self._connect_loop, name="spacegame-client-connect",
            daemon=True,
        )
        self._threads.append(self._connect_thread)
        self._connect_thread.start()

    def _connect_loop(self):
        try:
            sock = socket.create_connection((self.host, self.port),
                                            timeout=CONNECT_TIMEOUT)
            sock.settimeout(SOCKET_POLL)
        except OSError as exc:
            self._set_state("error", "cannot connect: %s" % exc)
            self._post({"t": "error", "code": "connect",
                        "message": "Cannot connect to %s:%s" % (self.host,
                                                               self.port)})
            return
        if self._stop.is_set():
            sock.close()
            return
        self._socket = sock
        self._last_rx = time.monotonic()
        self._handshake_deadline = self._last_rx + HANDSHAKE_TIMEOUT
        self._start_sender(sock)
        self._queue_message({"t": "hello", "v": PROTOCOL_VERSION,
                             "name": self.name, "ship": self.ship})
        reader = threading.Thread(target=self._reader_loop, args=(sock,),
                                  name="spacegame-client-reader", daemon=True)
        self._threads.append(reader)
        reader.start()

    def _reader_loop(self, sock):
        decoder = MessageBuffer()
        seen = 0
        window_start = time.monotonic()
        try:
            while not self._stop.is_set():
                try:
                    chunk = sock.recv(8192)
                except socket.timeout:
                    if self.state == "connecting":
                        if time.monotonic() > self._handshake_deadline:
                            self._fail("host handshake timed out")
                            return
                        continue
                    if self._idle_expired():
                        self._fail("host timed out")
                        return
                    continue
                except OSError as exc:
                    if not self._stop.is_set():
                        self._fail("receive failed: %s" % exc)
                    return
                if not chunk:
                    self._fail("host closed the connection")
                    return
                self._last_rx = time.monotonic()
                try:
                    messages = decoder.feed(chunk)
                except ProtocolError as exc:
                    self._fail("bad frame: %s" % exc)
                    return
                for raw in messages:
                    try:
                        message = validate_host_message(raw)
                    except ProtocolError as exc:
                        self._fail("invalid message: %s" % exc)
                        return
                    seen += 1
                    now = time.monotonic()
                    if now - window_start >= 1.0:
                        if seen > MAX_MESSAGES_PER_SECOND:
                            self._fail("host message flood")
                            return
                        seen = 0
                        window_start = now
                    if message["t"] == "welcome":
                        self._set_state("connected")
                        self._post({"t": "welcome",
                                    "host_name": message["host_name"]})
                    elif message["t"] == "ping":
                        self._queue_message({"t": "pong", "ts": message["ts"]})
                        self._post(message)
                    elif message["t"] == "leave":
                        self._post({"t": "peer_left",
                                    "reason": message["reason"]})
                        self._fail("host left")
                        return
                    elif message["t"] == "error":
                        self._post(message)
                        self._set_state("error", message["message"])
                        self.close()
                        return
                    else:
                        self._post(message)
        finally:
            if not self._closed and not self._stop.is_set():
                self._fail("connection closed")

    # ----------------------------------------------------------------- public
    def send(self, message):
        return self._queue_message(message)

    def send_input(self, x, y, fire, force=False):
        now = time.monotonic()
        if not force and now - self._last_input < 1.0 / 45.0:
            return False
        if not self.connected:
            return False
        self._last_input = now
        self._input_seq = (self._input_seq + 1) & 0x7FFFFFFF
        return self._queue_message({
            "t": "input", "seq": self._input_seq,
            "x": _clamp(_finite(x), -1.0, 1.0),
            "y": _clamp(_finite(y), -1.0, 1.0),
            "fire": bool(fire),
        })

    def send_pause_request(self):
        return self._queue_message({"t": "pause_request"})

    def send_story_skip(self):
        return self._queue_message({"t": "story_skip"})

    def send_superpower(self, kind):
        if kind not in ("tiger", "chainsaw") or not self.connected:
            return False
        return self._queue_message({"t": "superpower", "kind": kind})

    def send_leave(self, reason="left"):
        try:
            self._queue_message({"t": "leave",
                                 "reason": _clean_text(reason,
                                                       MAX_REASON_LEN,
                                                       "left")})
            time.sleep(0.05)
        finally:
            self.close()

    def _close_sockets(self):
        if self._socket is not None:
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None
