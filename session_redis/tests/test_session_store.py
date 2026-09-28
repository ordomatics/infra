from unittest.mock import patch

from odoo.http import Session
from odoo.tests.common import BaseCase, tagged

from .. import session_store
from ..session_store import RedisSessionStore, _redis


@tagged('post_install', '-at_install')
class TestRedisSessionStore(BaseCase):
    """The res.device half of Odoo 18's session store interface, against the
    real Redis."""

    def setUp(self):
        super().setUp()
        if _redis("PING") != "PONG":
            self.skipTest("no Redis reachable")
        self.store = RedisSessionStore(Session)
        self.sessions = []

    def tearDown(self):
        for session in self.sessions:
            self.store.delete(session)
        super().tearDown()

    def _session(self):
        session = self.store.new()
        session['uid'] = 2
        self.store.save(session)
        self.sessions.append(session)
        return session

    def test_only_sessions_that_are_gone_are_reported_missing(self):
        live, gone = self._session(), self._session()
        self.store.delete(gone)

        missing = self.store.get_missing_session_identifiers({live.sid[:42], gone.sid[:42]})

        self.assertEqual(missing, {gone.sid[:42]})

    def test_nothing_is_reported_missing_when_redis_cannot_be_read(self):
        # Whatever comes back is revoked, so an outage must not log everyone out.
        live = self._session()
        with patch.object(session_store, '_command', side_effect=ConnectionError('down')):
            self.assertEqual(self.store.get_missing_session_identifiers({live.sid[:42]}), set())

    def test_logging_a_device_out_drops_its_session_and_no_other(self):
        target, other = self._session(), self._session()

        self.store.delete_from_identifiers({target.sid[:42]})

        self.assertFalse(self.store.get(target.sid).get('uid'))
        self.assertEqual(self.store.get(other.sid).get('uid'), 2)

    def test_an_identifier_with_glob_characters_deletes_nothing(self):
        other = self._session()

        self.store.delete_from_identifiers({'*' * 42})

        self.assertEqual(self.store.get(other.sid).get('uid'), 2)
