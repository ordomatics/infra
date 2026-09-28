{
    "name": "Database Init Guard",
    "version": "1.0.0",
    "category": "Technical",
    "summary": "Keeps a database out of routing and cron while it is being initialised",
    "description": """
Database Init Guard
===================

A database Odoo can route to is served the moment it exists. While ``-i base``
is still creating its tables, a request (or the cron worker) loads a half-built
registry and deadlocks with the init. On a wildcard host every new database is
reachable that way, whatever order the platform publishes things in.

The init job comments the database ``odoo:initialising`` before it creates a
table and clears it when setup succeeds. This hides commented databases from
``list_dbs`` (routing and cron) and ``db_filter`` (existing sessions), along
with any database that has no Odoo schema yet: between creation and the init
job starting, an empty database is routable and Odoo answers 500 for it.

Add to ``server_wide_modules`` in ``odoo.conf``.
    """,
    "author": "Ordomatics",
    "license": "LGPL-3",
    "depends": ["base"],
    "installable": True,
    "auto_install": False,
    "post_load": "patch_database_listing",
}
