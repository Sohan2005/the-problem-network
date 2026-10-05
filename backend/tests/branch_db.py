"""Test-branch database access for tests. Every test runs in a transaction that is rolled back."""
import os
import unittest

from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_engine = None

def branch_engine():
    """Engine for the Neon test branch in DATABASE_URL. Skips unless it is distinct from backend/.env and has test_branch_marker."""
    global _engine
    if _engine is not None:
        return _engine
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise unittest.SkipTest("DATABASE_URL not set to the test branch")
    production = dotenv_values(os.path.join(BACKEND_DIR, ".env")).get("DATABASE_URL")
    if not production or url == production or make_url(url).host == make_url(production).host:
        raise unittest.SkipTest("DATABASE_URL is not distinct from production")
    engine = create_engine(url)
    with engine.connect() as conn:
        if conn.execute(text("select to_regclass('public.test_branch_marker')")).scalar() is None:
            engine.dispose()
            raise unittest.SkipTest("test_branch_marker table missing")
    _engine = engine
    return _engine

class RolledBackTestCase(unittest.TestCase):
    """Gives each test self.conn and self.db (a Session whose commits become savepoints), all rolled back afterwards."""

    def setUp(self):
        self.conn = branch_engine().connect()
        self.trans = self.conn.begin()
        self.db = Session(bind=self.conn, join_transaction_mode="create_savepoint")

    def tearDown(self):
        self.db.close()
        self.trans.rollback()
        self.conn.close()
