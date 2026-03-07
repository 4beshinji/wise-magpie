"""Swarm advertising via heartbeat frames over Unix datagram sockets.

Each wise-magpie daemon instance periodically broadcasts a HEARTBEAT frame
containing its current state (running tasks, quota, capacity) to a shared
Unix datagram socket.  Peers listening on the same socket receive these
frames and maintain a registry of live swarm members, enabling distributed
coordination and load balancing.
"""

from __future__ import annotations

import logging
import os
import socket
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock, Thread

from wise_magpie.swarm.frame import DecodeError, Frame, FrameType, decode, encode

from wise_magpie import config, constants, db
from wise_magpie.models import TaskStatus

logger = logging.getLogger("wise-magpie")


@dataclass
class PeerInfo:
    """State advertised by a swarm peer."""

    instance_id: str
    hostname: str = ""
    pid: int = 0
    running_tasks: int = 0
    pending_tasks: int = 0
    parallel_limit: int = 0
    quota_remaining_pct: float = 0.0
    model: str = ""
    last_seen: float = 0.0  # monotonic timestamp


@dataclass
class SwarmAdvertiser:
    """Broadcasts heartbeat frames and tracks peer state.

    Call :meth:`start` to begin advertising in a background thread,
    and :meth:`stop` to shut it down.
    """

    instance_id: str = ""
    socket_path: str = ""
    advertise_interval: float = constants.SWARM_ADVERTISE_INTERVAL_SECONDS
    peer_timeout: float = constants.SWARM_PEER_TIMEOUT_SECONDS
    _peers: dict[str, PeerInfo] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)
    _thread: Thread | None = None
    _stop: bool = False
    _sock: socket.socket | None = None

    def start(self) -> None:
        """Start the advertiser background thread."""
        if self._thread is not None:
            return

        if not self.instance_id:
            self.instance_id = _generate_instance_id()

        if not self.socket_path:
            self.socket_path = str(config.data_dir() / constants.SWARM_SOCKET_NAME)

        self._stop = False
        self._sock = _create_socket(self.socket_path, self.instance_id)
        if self._sock is None:
            logger.warning("Swarm advertiser: failed to create socket, running without peers")
            return

        self._thread = Thread(
            target=self._loop,
            daemon=True,
            name="swarm-advertiser",
        )
        self._thread.start()
        logger.info(
            "Swarm advertiser started (id=%s, socket=%s, interval=%ds)",
            self.instance_id,
            self.socket_path,
            self.advertise_interval,
        )

    def stop(self) -> None:
        """Stop the advertiser and clean up."""
        self._stop = True
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        # Clean up our per-instance socket file
        inst_path = self.socket_path + "." + self.instance_id
        try:
            os.unlink(inst_path)
        except OSError:
            pass

    @property
    def peers(self) -> dict[str, PeerInfo]:
        """Return a snapshot of currently known peers (excluding self)."""
        now = time.monotonic()
        with self._lock:
            return {
                k: v
                for k, v in self._peers.items()
                if k != self.instance_id and now - v.last_seen < self.peer_timeout
            }

    @property
    def peer_count(self) -> int:
        """Number of live peers (excluding self)."""
        return len(self.peers)

    def _loop(self) -> None:
        """Background loop: send heartbeats and receive peer frames."""
        while not self._stop:
            try:
                self._send_heartbeat()
            except Exception:
                logger.debug("Swarm heartbeat send failed", exc_info=True)

            try:
                self._receive_frames()
            except Exception:
                logger.debug("Swarm frame receive failed", exc_info=True)

            self._expire_peers()

            # Sleep in small increments so stop is responsive
            deadline = time.monotonic() + self.advertise_interval
            while not self._stop and time.monotonic() < deadline:
                time.sleep(0.5)

    def _send_heartbeat(self) -> None:
        """Broadcast a HEARTBEAT frame to all peers."""
        if self._sock is None:
            return

        payload = self._collect_state()
        frame = Frame(frame_type=FrameType.HEARTBEAT, payload=payload)
        data = encode(frame)

        # Send to the shared socket — all listeners on per-instance sockets
        # under the same directory will receive the frame via the shared address.
        _broadcast_to_peers(self._sock, data, self.socket_path, self.instance_id)

    def _receive_frames(self) -> None:
        """Read any pending frames from the socket (non-blocking)."""
        if self._sock is None:
            return

        while True:
            try:
                data, _addr = self._sock.recvfrom(65535)
            except (BlockingIOError, OSError):
                break

            try:
                frame = decode(data)
            except DecodeError:
                logger.debug("Swarm: received malformed frame")
                continue

            if frame.frame_type == FrameType.HEARTBEAT:
                self._handle_heartbeat(frame.payload)

    def _handle_heartbeat(self, payload: dict) -> None:
        """Update the peer registry from a HEARTBEAT payload."""
        peer_id = payload.get("instance_id", "")
        if not peer_id:
            return

        peer = PeerInfo(
            instance_id=peer_id,
            hostname=payload.get("hostname", ""),
            pid=payload.get("pid", 0),
            running_tasks=payload.get("running_tasks", 0),
            pending_tasks=payload.get("pending_tasks", 0),
            parallel_limit=payload.get("parallel_limit", 0),
            quota_remaining_pct=payload.get("quota_remaining_pct", 0.0),
            model=payload.get("model", ""),
            last_seen=time.monotonic(),
        )

        with self._lock:
            self._peers[peer_id] = peer

    def _expire_peers(self) -> None:
        """Remove peers that have not sent a heartbeat recently."""
        now = time.monotonic()
        with self._lock:
            expired = [
                k for k, v in self._peers.items()
                if now - v.last_seen >= self.peer_timeout
            ]
            for k in expired:
                del self._peers[k]
                logger.info("Swarm peer expired: %s", k)

    def _collect_state(self) -> dict:
        """Gather the current daemon state for the heartbeat payload."""
        running = len(db.get_tasks_by_status(TaskStatus.RUNNING))
        pending = len(db.get_tasks_by_status(TaskStatus.PENDING))

        quota_pct = 0.0
        try:
            from wise_magpie.quota.estimator import estimate_remaining

            est = estimate_remaining()
            quota_pct = est.get("remaining_pct", 0.0)
        except Exception:
            pass

        parallel_limit = 0
        try:
            from wise_magpie.daemon.scheduler import get_parallel_limit

            parallel_limit = get_parallel_limit()
        except Exception:
            pass

        cfg = config.load_config()
        model = cfg.get("claude", {}).get("model", constants.DEFAULT_MODEL)

        return {
            "instance_id": self.instance_id,
            "hostname": socket.gethostname(),
            "pid": os.getpid(),
            "running_tasks": running,
            "pending_tasks": pending,
            "parallel_limit": parallel_limit,
            "quota_remaining_pct": quota_pct,
            "model": model,
        }


def _generate_instance_id() -> str:
    """Generate a short unique instance identifier."""
    return f"wm-{uuid.uuid4().hex[:8]}"


def _create_socket(base_path: str, instance_id: str) -> socket.socket | None:
    """Create a Unix datagram socket bound to a per-instance address.

    Each instance binds to ``<base_path>.<instance_id>`` so it can receive
    unicast frames from peers.  The socket is set to non-blocking mode.
    """
    inst_path = base_path + "." + instance_id
    try:
        # Clean up stale socket file
        try:
            os.unlink(inst_path)
        except OSError:
            pass

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.bind(inst_path)
        sock.setblocking(False)
        return sock
    except OSError as exc:
        logger.warning("Failed to create swarm socket at %s: %s", inst_path, exc)
        return None


def _broadcast_to_peers(
    sock: socket.socket,
    data: bytes,
    base_path: str,
    self_id: str,
) -> None:
    """Send *data* to all peer sockets in the swarm directory.

    Peers are discovered by listing files matching ``<base_path>.*`` in the
    filesystem.  The sender's own socket is skipped.
    """
    base = Path(base_path)
    parent = base.parent
    prefix = base.name + "."

    try:
        entries = list(parent.iterdir())
    except OSError:
        return

    for entry in entries:
        if not entry.name.startswith(prefix):
            continue
        peer_id = entry.name[len(prefix):]
        if peer_id == self_id:
            continue
        try:
            sock.sendto(data, str(entry))
        except OSError:
            # Peer socket may be stale — ignore
            pass


def create_advertiser_from_config() -> SwarmAdvertiser | None:
    """Create a :class:`SwarmAdvertiser` from the current configuration.

    Returns ``None`` if swarm mode is disabled.
    """
    cfg = config.load_config()
    swarm_cfg = cfg.get("swarm", {})

    if not swarm_cfg.get("enabled", False):
        return None

    return SwarmAdvertiser(
        instance_id=swarm_cfg.get("instance_id", ""),
        socket_path=swarm_cfg.get("socket_path", ""),
        advertise_interval=swarm_cfg.get(
            "advertise_interval_seconds",
            constants.SWARM_ADVERTISE_INTERVAL_SECONDS,
        ),
    )
