import logging
import time
from contextlib import closing

_logger = logging.getLogger(__name__)

# Set and cleared by the platform's init job (COMMENT ON DATABASE).
MARKER = "odoo:initialising"
_TTL = 5.0
_cache = {"at": float("-inf"), "names": frozenset()}


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


def patch_database_listing():
    from odoo import http
    from odoo.service import db as service_db

    list_dbs = service_db.list_dbs
    db_filter = http.db_filter

    def guarded_list_dbs(force=False):
        hidden = initialising_dbs()
        return [name for name in list_dbs(force) if name not in hidden]

    def guarded_db_filter(dbs, host=None):
        hidden = initialising_dbs()
        return db_filter([name for name in dbs if name not in hidden], host)

    service_db.list_dbs = guarded_list_dbs
    http.db_filter = guarded_db_filter
    _logger.info("db_init_guard: databases marked %r are hidden", MARKER)
