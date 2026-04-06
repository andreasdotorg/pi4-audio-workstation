"""GraphManager JSON-over-TCP RPC client (US-061, D-040).

Thin client for the GraphManager RPC server (localhost:4002). Provides
mode switching, state queries, and measurement mode management.

Protocol: newline-delimited JSON matching the GM RPC spec (rpc.rs):
  Request:  {"cmd": "<name>", ...fields}\n
  Response: {"type": "ack"|"response", "cmd": "<name>", "ok": true|false, ...}\n

Usage::

    from graph_manager_client import GraphManagerClient

    gm = GraphManagerClient()
    gm.connect()

    gm.set_mode("measurement")   # Switch to measurement routing
    state = gm.get_state()       # {"mode": "measurement", "nodes": [...], ...}
    gm.set_mode("standby")       # Restore production routing

    gm.close()
"""

import json
import logging
import socket
import time
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4002
DEFAULT_TIMEOUT = 2.0
MAX_CMD_BYTES = 4096
MAX_RESPONSE_BYTES = 262144


class GraphManagerError(RuntimeError):
    """Error from the GraphManager RPC server."""


class GraphManagerClient:
    """TCP client for pi4audio-graph-manager.

    Follows the same connection pattern as SignalGenClient for consistency.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self._host = host
        self._port = port
        self._timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._recv_buf = b""

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open TCP connection to the GraphManager."""
        self._sock = socket.create_connection(
            (self._host, self._port), timeout=self._timeout
        )
        self._sock.settimeout(self._timeout)
        self._recv_buf = b""
        logger.info("Connected to GraphManager at %s:%d", self._host, self._port)

    def close(self) -> None:
        """Close the TCP connection."""
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self._recv_buf = b""

    def reconnect(self, max_attempts: int = 5, backoff_base: float = 1.0,
                  backoff_max: float = 30.0) -> None:
        """Reconnect with exponential backoff.

        Raises ConnectionError if all attempts fail.
        """
        self.close()
        delay = backoff_base
        for attempt in range(1, max_attempts + 1):
            try:
                self.connect()
                self.ping()
                logger.info("Reconnected on attempt %d", attempt)
                return
            except (OSError, TimeoutError, ConnectionError) as exc:
                logger.warning("Reconnect attempt %d/%d failed: %s",
                               attempt, max_attempts, exc)
                if attempt < max_attempts:
                    time.sleep(min(delay, backoff_max))
                    delay *= 2
        raise ConnectionError(
            f"Failed to reconnect to GraphManager after {max_attempts} attempts"
        )

    @property
    def is_connected(self) -> bool:
        """True if the TCP socket is open."""
        return self._sock is not None

    # ------------------------------------------------------------------
    # Low-level protocol
    # ------------------------------------------------------------------

    def _send_cmd(self, cmd: dict, *, allow_not_ok: bool = False) -> dict:
        """Send a JSON command and return the response.

        Parameters
        ----------
        allow_not_ok : bool
            If True, return the response even when ``ok`` is False instead
            of raising GraphManagerError. Used by ``await_settled`` where
            a timeout is a normal (non-exceptional) response.
        """
        if self._sock is None:
            raise ConnectionError("Not connected to GraphManager")
        line = json.dumps(cmd, separators=(",", ":")) + "\n"
        encoded = line.encode()
        if len(encoded) > MAX_CMD_BYTES:
            raise GraphManagerError(
                f"Command exceeds max line length ({len(encoded)} > {MAX_CMD_BYTES})")
        self._sock.sendall(encoded)
        return self._read_response(cmd.get("cmd", ""),
                                    allow_not_ok=allow_not_ok)

    def _read_response(self, expected_cmd: str, *,
                        allow_not_ok: bool = False) -> dict:
        """Read lines until we get an ack/response for the expected command.

        The GM may send push events interleaved with responses. Events
        are logged and discarded; only the matching ack/response is returned.
        """
        while True:
            line = self._read_line()
            msg = json.loads(line)
            msg_type = msg.get("type", "")

            if msg_type == "event":
                logger.debug("GM event: %s", msg.get("event", "?"))
                continue

            if msg_type in ("ack", "response"):
                if msg.get("cmd") == expected_cmd:
                    if not msg.get("ok", False) and not allow_not_ok:
                        error = msg.get("error", "unknown error")
                        raise GraphManagerError(
                            f"GraphManager command '{expected_cmd}' failed: {error}")
                    return msg
                logger.debug("GM response for unexpected cmd: %s", msg.get("cmd"))
                continue

            logger.debug("GM unknown message type: %s", msg_type)

    def _read_line(self) -> str:
        """Read a newline-delimited line from the socket."""
        while b"\n" not in self._recv_buf:
            try:
                chunk = self._sock.recv(65536)
            except socket.timeout:
                raise TimeoutError("Timed out waiting for GraphManager response")
            if not chunk:
                raise ConnectionError("GraphManager connection closed")
            self._recv_buf += chunk
            if len(self._recv_buf) > MAX_RESPONSE_BYTES:
                raise GraphManagerError("Response exceeds max line length")
        idx = self._recv_buf.index(b"\n")
        line = self._recv_buf[:idx].decode("utf-8")
        self._recv_buf = self._recv_buf[idx + 1:]
        return line

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def ping(self) -> None:
        """Verify the connection is alive."""
        self._send_cmd({"cmd": "ping"})

    def set_mode(self, mode: str) -> dict:
        """Switch the GraphManager to a new routing mode.

        Parameters
        ----------
        mode : str
            One of "standby", "dj", "live", "measurement".

        Returns
        -------
        dict
            Response including ``epoch`` field (US-140) for use with
            ``await_settled()``.
        """
        resp = self._send_cmd({"cmd": "set_mode", "mode": mode})
        logger.info("GraphManager mode set to: %s (epoch=%s)", mode,
                     resp.get("epoch"))
        return resp

    def get_state(self) -> dict:
        """Query the current graph state.

        Returns
        -------
        dict
            {"mode": str, "nodes": [...], "links": [...], "devices": {...}}
        """
        resp = self._send_cmd({"cmd": "get_state"})
        return {
            "mode": resp.get("mode", "unknown"),
            "nodes": resp.get("nodes", []),
            "links": resp.get("links", []),
            "devices": resp.get("devices", {}),
        }

    def get_mode(self) -> str:
        """Return the current routing mode as a string."""
        state = self.get_state()
        return state["mode"]

    def get_devices(self) -> list:
        """Query device status.

        Returns
        -------
        list[dict]
            Each dict has "name", "node_name", "status".
        """
        resp = self._send_cmd({"cmd": "get_devices"})
        return resp.get("devices", [])

    def get_links(self) -> dict:
        """Query the current link topology.

        Returns
        -------
        dict
            {"mode": str, "desired": int, "actual": int, "missing": int, "links": [...]}
        """
        resp = self._send_cmd({"cmd": "get_links"})
        return {
            "mode": resp.get("mode", "unknown"),
            "desired": resp.get("desired", 0),
            "actual": resp.get("actual", 0),
            "missing": resp.get("missing", 0),
            "links": resp.get("links", []),
        }

    def await_settled(self, since_epoch: int, timeout_ms: int = 10000) -> dict:
        """Wait for the reconciler to settle (US-140).

        Blocks until ``settled_epoch >= since_epoch`` or timeout expires.
        The server handles the wait -- no client-side polling.

        Parameters
        ----------
        since_epoch : int
            Epoch value from a prior ``set_mode()`` response.
        timeout_ms : int
            Maximum wait time in milliseconds (default 10000).

        Returns
        -------
        dict
            Response with ``ok``, ``settled_epoch``, ``desired``,
            ``actual``, ``missing`` fields. On timeout, ``ok`` is False
            and ``reason`` is ``"timeout"``.
        """
        # The server blocks for up to timeout_ms, so set socket timeout
        # generously above that.
        old_timeout = self._sock.gettimeout() if self._sock else None
        if self._sock is not None:
            self._sock.settimeout(max((timeout_ms / 1000.0) + 5.0,
                                      self._timeout))
        try:
            resp = self._send_cmd({
                "cmd": "await_settled",
                "since_epoch": since_epoch,
                "timeout_ms": timeout_ms,
            }, allow_not_ok=True)
        finally:
            if self._sock is not None and old_timeout is not None:
                self._sock.settimeout(old_timeout)
        return resp

    def enter_measurement_mode(self) -> None:
        """Switch to measurement routing mode.

        The GraphManager establishes measurement-specific link topology:
        signal-gen -> filter-chain, UMIK-1 capture active. All non-measurement
        links are torn down.
        """
        self.set_mode("measurement")

    def restore_production_mode(self) -> None:
        """Switch back to standby (idle production) mode.

        Restores the production link topology. Safe to call multiple times.
        """
        self.set_mode("standby")

    def verify_measurement_mode(self) -> None:
        """Verify that the GraphManager is in measurement mode.

        Raises
        ------
        GraphManagerError
            If the current mode is not "measurement".
        """
        mode = self.get_mode()
        if mode != "measurement":
            raise GraphManagerError(
                f"GraphManager is not in measurement mode "
                f"(current mode: {mode}). Measurement attenuation may not "
                f"be active. Aborting for safety.")
        logger.info("GraphManager measurement mode verified")

    # ------------------------------------------------------------------
    # Venue / gate commands (US-113 Phase 4)
    # ------------------------------------------------------------------

    def list_venues(self) -> list:
        """List available venue configs.

        Returns list of dicts with 'name' and 'display_name' keys.
        """
        resp = self._send_cmd({"cmd": "list_venues"})
        return resp.get("venues", [])

    def get_venue(self) -> Optional[str]:
        """Return the active venue name, or None if no venue is loaded."""
        resp = self._send_cmd({"cmd": "get_venue"})
        return resp.get("venue")

    def set_venue(self, venue: str) -> None:
        """Load a venue config by name."""
        self._send_cmd({"cmd": "set_venue", "venue": venue})
        logger.info("GraphManager venue set to: %s", venue)

    def open_gate(self) -> None:
        """Open the audio gate (D-063). Requires a venue to be loaded."""
        self._send_cmd({"cmd": "open_gate"})
        logger.info("GraphManager gate opened")

    def close_gate(self) -> None:
        """Close the audio gate (D-063). Zeroes all gains."""
        self._send_cmd({"cmd": "close_gate"})
        logger.info("GraphManager gate closed")

    def get_gate(self) -> dict:
        """Query gate status.

        Returns dict with 'gate_open', 'has_pending_gains', 'venue' keys.
        """
        resp = self._send_cmd({"cmd": "get_gate"})
        return {
            "gate_open": resp.get("gate_open", False),
            "has_pending_gains": resp.get("has_pending_gains", False),
            "venue": resp.get("venue"),
        }


class MockGraphManagerClient:
    """Mock GraphManagerClient for testing without a running GraphManager.

    Mirrors the real client API with in-memory state tracking.
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 timeout: float = DEFAULT_TIMEOUT):
        self._mode = "standby"
        self._connected = False

    def connect(self) -> None:
        self._connected = True
        logger.info("MockGraphManagerClient connected")

    def close(self) -> None:
        self._connected = False

    def reconnect(self, **kwargs) -> None:
        self._connected = True

    @property
    def is_connected(self) -> bool:
        return self._connected

    def ping(self) -> None:
        pass

    def set_mode(self, mode: str) -> dict:
        self._mode = mode
        logger.info("MockGraphManagerClient mode set to: %s", mode)
        return {"type": "response", "cmd": "set_mode", "ok": True, "epoch": 0}

    def get_state(self) -> dict:
        return {
            "mode": self._mode,
            "nodes": [],
            "links": [],
            "devices": {},
        }

    def get_mode(self) -> str:
        return self._mode

    def get_devices(self) -> list:
        return []

    def get_links(self) -> dict:
        return {"mode": self._mode, "desired": 0, "actual": 0,
                "missing": 0, "links": []}

    def await_settled(self, since_epoch: int, timeout_ms: int = 10000) -> dict:
        return {"type": "response", "cmd": "await_settled", "ok": True,
                "settled_epoch": 0, "desired": 0, "actual": 0, "missing": 0}

    def enter_measurement_mode(self) -> None:
        self.set_mode("measurement")

    def restore_production_mode(self) -> None:
        self.set_mode("standby")

    def verify_measurement_mode(self) -> None:
        if self._mode != "measurement":
            raise GraphManagerError(
                f"MockGraphManagerClient is not in measurement mode "
                f"(current mode: {self._mode})")
        logger.info("MockGraphManagerClient measurement mode verified")

    def list_venues(self) -> list:
        return [
            {"name": "local-demo", "display_name": "Local Demo"},
            {"name": "rehearsal-room", "display_name": "Rehearsal Room"},
        ]

    def get_venue(self) -> Optional[str]:
        return getattr(self, "_venue", None)

    def set_venue(self, venue: str) -> None:
        self._venue = venue
        self._gate_open = False
        self._has_pending = True
        logger.info("MockGraphManagerClient venue set to: %s", venue)

    def open_gate(self) -> None:
        if not getattr(self, "_venue", None):
            raise GraphManagerError("no venue loaded")
        self._gate_open = True
        self._has_pending = False
        logger.info("MockGraphManagerClient gate opened")

    def close_gate(self) -> None:
        self._gate_open = False
        logger.info("MockGraphManagerClient gate closed")

    def get_gate(self) -> dict:
        return {
            "gate_open": getattr(self, "_gate_open", False),
            "has_pending_gains": getattr(self, "_has_pending", False),
            "venue": getattr(self, "_venue", None),
        }
