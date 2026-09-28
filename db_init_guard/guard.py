import logging
import time
from contextlib import closing

_logger = logging.getLogger(__name__)

# Set and cleared by the platform's init job (COMMENT ON DATABASE).
MARKER = "odoo:initialising"
_TTL = 5.0
# Longer for a yes: an initialised database stays so, except when deleted and
# recreated under the same name, which this still catches within a minute.
_INITIALISED_TTL = 60.0
_cache = {"at": float("-inf"), "names": frozenset()}
_initialised = {}


def initialising_dbs():
    """Databases marked as mid-initialisation. Cached briefly: db_filter runs
    on every request. A failed read keeps the last answer rather than hiding
    or exposing everything."""
    now = time.monotonic()
    if now - _cache["at"] < _TTL:
        return _cache["names"]
    import odoo
    try:
        with closing(odoo.sql_db.db_connect("postgres").cursor()) as cr:
            cr.execute(
                "SELECT datname FROM pg_database "
                "WHERE shobj_description(oid, 'pg_database') = %s", (MARKER,))
            names = frozenset(name for (name,) in cr.fetchall())
    except Exception as exc:
        _logger.warning("db_init_guard: cannot read database markers: %s", exc)
        names = _cache["names"]
    _cache.update(at=now, names=names)
    return names


def _is_initialised(name):
    import odoo
    try:
        with closing(odoo.sql_db.db_connect(name).cursor()) as cr:
            return odoo.modules.db.is_initialized(cr)
    except Exception as exc:
        # Unreachable is not "empty": hiding it would take a live database
        # offline on a network blip.
        _logger.warning("db_init_guard: cannot inspect %s: %s", name, exc)
        return True


def uninitialised_dbs(names):
    """Of these, the ones with no Odoo schema yet. Between a database being
    created and its init job starting, it is empty but routable, and Odoo
    answers 500 for it."""
    now = time.monotonic()
    empty = set()
    for name in names:
        at, ready = _initialised.get(name, (float("-inf"), False))
        if now - at >= (_INITIALISED_TTL if ready else _TTL):
            ready = _is_initialised(name)
            _initialised[name] = (now, ready)
        if not ready:
            empty.add(name)
    return empty


def hidden_dbs(names):
    marked = initialising_dbs()
    return marked | uninitialised_dbs([name for name in names if name not in marked])


def patch_database_listing():
    from odoo import http
    from odoo.service import db as service_db

    list_dbs = service_db.list_dbs
    db_filter = http.db_filter

    def guarded_list_dbs(force=False):
        names = list_dbs(force)
        hidden = hidden_dbs(names)
        return [name for name in names if name not in hidden]

    def guarded_db_filter(dbs, host=None):
        hidden = hidden_dbs(dbs)
        return db_filter([name for name in dbs if name not in hidden], host)

    service_db.list_dbs = guarded_list_dbs
    http.db_filter = guarded_db_filter
    _logger.info("db_init_guard: databases marked %r or not yet initialised are hidden", MARKER)
