# -*- coding: utf-8 -*-
"""
Redis-backed Odoo session store.

Patches ``odoo.http.Root.session_store`` at startup so every pod in a
multi-pod k8s deployment reads/writes sessions from the same Redis instance
instead of pod-local files.

Uses only Python stdlib (socket) — no redis-py required.
"""

import json
import logging
import os
import socket as _socket

_logger = logging.getLogger(__name__)

_REDIS_HOST = os.environ.get("SESSION_REDIS_HOST", "redis")
_REDIS_PORT = int(os.environ.get("SESSION_REDIS_PORT", "6379"))
_SESSION_TTL = int(os.environ.get("SESSION_REDIS_TTL", str(7 * 24 * 3600)))
_KEY_PREFIX = "odoo_sess:"


# ---------------------------------------------------------------------------
# Minimal RESP protocol client
# ---------------------------------------------------------------------------

def _resp_encode(*args):
    parts = [a.encode() if isinstance(a, str) else a for a in args]
    buf = f"*{len(parts)}\r\n".encode()
    for p in parts:
        buf += f"${len(p)}\r\n".encode() + p + b"\r\n"
    return buf


def _read_reply(f):
    line = f.readline()
    if not line.endswith(b"\r\n"):
        raise ConnectionError("truncated Redis reply")
    kind, rest = line[:1], line[1:-2]
    if kind == b"+":
        return rest.decode()
    if kind == b"-":
        raise RuntimeError(f"Redis error: {rest.decode()}")
    if kind == b":":
        return int(rest)
    if kind == b"$":
        size = int(rest)
        return None if size == -1 else f.read(size + 2)[:-2]
    if kind == b"*":
        size = int(rest)
        return None if size == -1 else [_read_reply(f) for _ in range(size)]
    raise RuntimeError(f"Unknown Redis reply type {kind!r}")


def _command(*args):
    """Execute one Redis command via a fresh socket. Raises on failure."""
    conn = _socket.create_connection((_REDIS_HOST, _REDIS_PORT), timeout=3)
    try:
        conn.sendall(_resp_encode(*args))
        with conn.makefile("rb") as f:
            return _read_reply(f)
    finally:
        conn.close()


def _redis(*args):
    """Like _command, but a failure is logged and reads as None."""
    try:
        return _command(*args)
    except Exception as exc:
        _logger.warning("session_redis: Redis %s failed: %s", args[0], exc)
        return None


def _scan(pattern):
    """Every key matching pattern. Raises on failure: a partial listing must
    never pass for a complete one."""
    keys, cursor = [], b"0"
    while True:
        cursor, batch = _command("SCAN", cursor, "MATCH", pattern, "COUNT", "1000")
        keys.extend(batch)
        if cursor == b"0":
            return keys


# ---------------------------------------------------------------------------
# RedisSessionStore
# ---------------------------------------------------------------------------

class RedisSessionStore:
    """
    Drop-in replacement for ``odoo.http.FilesystemSessionStore`` backed by Redis.

    Implements the interface Odoo expects:
        get(sid), save(session), delete(session), new(),
        rotate(session, env), generate_key(), is_valid_key(key), vacuum(),
        get_missing_session_identifiers(ids), delete_from_identifiers(ids)
    """

    def __init__(self, session_class, renew_missing=True):
        self.session_class = session_class
        self.renew_missing = renew_missing
        # Delegate generate_key / is_valid_key to FilesystemSessionStore
        # so we stay consistent with Odoo's key format.
        from odoo.http import FilesystemSessionStore as _FS
        self._fs = _FS.__new__(_FS)

    # -- key helpers ---------------------------------------------------------

    def generate_key(self, salt=None):
        return self._fs.generate_key(salt)

    def is_valid_key(self, key):
        return self._fs.is_valid_key(key)

    # -- CRUD ----------------------------------------------------------------

    def new(self):
        return self.session_class({}, self.generate_key(), True)

    def get(self, sid):
        if not self.is_valid_key(sid):
            return self.new()
        raw = _redis("GET", _KEY_PREFIX + sid)
        if raw:
            try:
                return self.session_class(json.loads(raw), sid, False)
            except Exception as exc:
                _logger.warning("session_redis: decode error for %s: %s", sid, exc)
        # Session not found or corrupt — return a blank session with the same SID
        return self.session_class({}, sid, True)

    def save(self, session):
        _redis("SET", _KEY_PREFIX + session.sid,
               json.dumps(dict(session)), "EX", str(_SESSION_TTL))

    def delete(self, session):
        _redis("DEL", _KEY_PREFIX + session.sid)

    def rotate(self, session, env):
        """Called on login: assign new SID and recompute session token."""
        self.delete(session)
        session.sid = self.generate_key()
        if session.uid and env:
            from odoo.service import security
            session.session_token = security.compute_session_token(session, env)
        session.should_rotate = False
        self.save(session)

    def vacuum(self, max_lifetime=None):
        pass  # Redis TTL handles expiry — nothing to sweep

    # -- device log (res.device) --------------------------------------------
    # An identifier is the first 42 chars of a sid, as res.device.log stores it.

    def get_missing_session_identifiers(self, identifiers):
        """The identifiers with no live session. Nothing when Redis cannot be
        read: the caller revokes whatever this returns."""
        try:
            keys = _scan(_KEY_PREFIX + "*")
        except Exception as exc:
            _logger.warning("session_redis: cannot list sessions: %s", exc)
            return set()
        present = {k.decode()[len(_KEY_PREFIX):][:42] for k in keys}
        return set(identifiers) - present

    def delete_from_identifiers(self, identifiers):
        """Logs out a device: drops every session its identifier prefixes."""
        from odoo.http import _session_identifier_re
        for identifier in identifiers:
            # Also keeps glob characters out of the SCAN pattern.
            if not _session_identifier_re.match(identifier):
                continue
            keys = _scan(_KEY_PREFIX + identifier + "*")
            if keys:
                _command("DEL", *keys)


# ---------------------------------------------------------------------------
# post_load entry point
# ---------------------------------------------------------------------------

_store: RedisSessionStore | None = None


def patch_session_store():
    """
    Called via ``post_load`` in __manifest__.py.
    Replaces ``Application.session_store`` with a Redis-backed store.

    We must patch both the class descriptor AND clear any existing instance
    attribute, because Odoo's ``lazy_property`` caches the result on the
    instance on first access — if the original ``FilesystemSessionStore``
    was already cached, a class-level patch alone would be shadowed.
    """
    from odoo.http import Application, Session, root
    from odoo.tools.func import lazy_property

    @lazy_property
    def _get_store(self):
        store = RedisSessionStore(Session, renew_missing=True)
        _logger.info(
            "session_redis: session store → Redis (%s:%s, TTL %ds)",
            _REDIS_HOST, _REDIS_PORT, _SESSION_TTL,
        )
        return store

    Application.session_store = _get_store
    # Clear any already-cached instance attribute so the new descriptor fires
    if root is not None:
        root.__dict__.pop("session_store", None)
    _logger.info("session_redis: Application.session_store patched")
