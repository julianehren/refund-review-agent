"""Shared test fixtures: every test run gets its own fresh copy of the shop database."""

import pytest

from refund_agent import db, seed


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "test_shop.db"
    seed.build_database(path)
    connection = db.connect(path)
    yield connection
    connection.close()
