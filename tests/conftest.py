import pytest


@pytest.fixture
def conn(tmp_path):
    """A fresh database file with both tables, closed after the test."""
    import db  # imported here so a missing db.py fails each test instead of the whole run

    connection = db.connect(tmp_path / "desk.db")
    db.init_db(connection)
    yield connection
    connection.close()


@pytest.fixture
def break_history(conn):
    """Call the returned function to make every later insert into history fail.

    Used by the rollback tests: set up claims first, then break history writes,
    then check that a change which needs a history row leaves the claim untouched.
    """

    def _break():
        conn.execute(
            "CREATE TRIGGER fail_history_insert BEFORE INSERT ON history "
            "BEGIN SELECT RAISE(ABORT, 'history write failed on purpose'); END"
        )

    return _break
