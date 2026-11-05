"""The journal module through real SQLite files: transactions, schema versions and absence."""

from pathlib import Path
from unittest import TestCase

from automation import journal

_CREATE = ("CREATE TABLE notes (id INTEGER PRIMARY KEY, text TEXT NOT NULL)",)


def _rows(path: Path) -> list[tuple[object, ...]]:
    with journal.reading(path) as connection:
        return connection.execute("SELECT id, text FROM notes ORDER BY id").fetchall()


def test_a_failed_write_keeps_none_of_its_statements(tmp_path: Path) -> None:
    # Defect: an exception commits the statements that ran before it, or leaves the journal locked.
    path = tmp_path / "notes.sqlite3"
    with journal.writing(path) as connection:
        connection.execute(_CREATE[0])
        connection.execute("INSERT INTO notes VALUES (1, 'kept')")
    with TestCase().assertRaisesRegex(RuntimeError, "fixture"), journal.writing(path) as connection:
        connection.execute("INSERT INTO notes VALUES (2, 'discarded')")
        connection.execute("UPDATE notes SET text='changed' WHERE id=1")
        raise RuntimeError("fixture failure after two statements")
    assert _rows(path) == [(1, "kept")]
    with journal.writing(path) as connection:
        connection.execute("INSERT INTO notes VALUES (2, 'later')")
    assert _rows(path) == [(1, "kept"), (2, "later")]


def test_only_a_journal_that_chooses_a_write_ahead_log_relaxes_its_commits(tmp_path: Path) -> None:
    # Defect: the meeting journal's WAL option weakens every other journal's
    # durability, or never reaches the meeting journal's own connections.
    for durability, mode, synchronous in ((journal.Durability.FULL, "delete", 2), (journal.Durability.WAL, "wal", 1)):
        path = tmp_path / f"{durability.name}.sqlite3"
        with journal.writing(path, durability=durability) as connection:
            connection.execute(_CREATE[0])
            assert connection.execute("PRAGMA synchronous").fetchone() == (synchronous,)
        with journal.writing(path) as connection:
            assert connection.execute("PRAGMA synchronous").fetchone() == (2,)
        with journal.reading(path) as connection:
            assert connection.execute("PRAGMA journal_mode").fetchone() == (mode,)
            assert connection.execute("PRAGMA auto_vacuum").fetchone() == (1,)


def test_a_new_journal_is_created_at_its_schema_version(tmp_path: Path) -> None:
    # Defect: a new journal is not created at its version, or reopening it recreates its tables.
    schema = journal.Schema(3, (*_CREATE, "CREATE TABLE tags (note INTEGER NOT NULL)"))
    fresh = tmp_path / "fresh.sqlite3"
    for _ in range(2):
        with journal.writing(fresh) as connection:
            journal.prepare(connection, schema)
    with journal.reading(fresh) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (3,)
        assert connection.execute("SELECT COUNT(*) FROM tags").fetchone() == (0,)


def test_other_or_unversioned_journals_are_refused_without_changing_them(tmp_path: Path) -> None:
    # Defect: an older, newer or foreign journal is opened or rewritten.
    schema = journal.Schema(3, _CREATE)
    for name, version in (("newer", 4), ("older", 2), ("unversioned", 0)):
        path = tmp_path / f"{name}.sqlite3"
        with journal.writing(path) as connection:
            connection.execute(_CREATE[0])
            connection.execute("INSERT INTO notes VALUES (1, 'existing')")
            connection.execute(f"PRAGMA user_version={version}")
        before = path.read_bytes()
        with TestCase().assertRaises(journal.SchemaVersionError), journal.writing(path) as connection:
            journal.prepare(connection, schema)
        assert path.read_bytes() == before, name
