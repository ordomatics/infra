import uuid
from contextlib import closing
from unittest.mock import patch

import odoo
from odoo import http
from odoo.service import db as service_db
from odoo.tests.common import BaseCase, tagged

from .. import guard


@tagged('post_install', '-at_install')
class TestDbInitGuard(BaseCase):
    """Against a real throwaway database, since the marker lives in Postgres."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # The test server does not load server-wide post_load hooks for
        # modules missing from its config.
        if service_db.list_dbs.__name__ != 'guarded_list_dbs':
            guard.patch_database_listing()
        cls.name = 'guardtest_%s' % uuid.uuid4().hex[:8]
        cls._sql('CREATE DATABASE "%s"' % cls.name)

    @classmethod
    def tearDownClass(cls):
        cls._sql('DROP DATABASE IF EXISTS "%s"' % cls.name)
        super().tearDownClass()

    @classmethod
    def _sql(cls, query):
        with closing(odoo.sql_db.db_connect('postgres').cursor()) as cr:
            cr._cnx.autocommit = True
            cr.execute(query)

    def setUp(self):
        super().setUp()
        # What a wildcard deployment routes by: the host's first label.
        self.startPatcher(patch.dict(odoo.tools.config.options, {'dbfilter': '^%d$'}))

    def _host(self):
        # First label = database, which is what a %d dbfilter matches.
        return '%s.example.com' % self.name

    def _mark(self, value):
        self._sql('COMMENT ON DATABASE "%s" IS %s' % (self.name, value))
        guard._cache['at'] = float('-inf')

    def test_a_marked_database_is_neither_listed_nor_routed(self):
        self._mark("'%s'" % guard.MARKER)

        self.assertNotIn(self.name, service_db.list_dbs(True))
        self.assertEqual(http.db_filter([self.name], host=self._host()), [])

    def test_clearing_the_mark_brings_it_back(self):
        self._mark("'%s'" % guard.MARKER)
        self._mark('NULL')

        self.assertIn(self.name, service_db.list_dbs(True))
        self.assertEqual(http.db_filter([self.name], host=self._host()), [self.name])

    def test_another_comment_does_not_hide_it(self):
        self._mark("'our demo'")

        self.assertIn(self.name, service_db.list_dbs(True))
