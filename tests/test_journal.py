"""The journal module through real SQLite files: transactions, schema versions and absence."""

from pathlib import Path
from unittest import TestCase

from automation import journal

_CREATE = ("CREATE TABLE notes (id INTEGER PRIMARY KEY, text TEXT NOT NULL)",)


def _rows(path: Path) -> list[tuple[object, ...]]:
    with journal.reading(path) as connection:
        return connection.execute("SELECT id, text FROM notes ORDER BY id").fetchall()


def _dropped(connection: journal.Connection) -> None:
    connection.execute("DROP TABLE notes")


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


def test_schema_creation_and_migration_run_each_step_once_in_order(tmp_path: Path) -> None:
    # Defect: an older journal skips or repeats a migration step, or a new journal is not created at its version.
    steps: list[int] = []
    schema = journal.Schema(
        3,
        (*_CREATE, "CREATE TABLE tags (note INTEGER NOT NULL)"),
        {1: lambda connection: steps.append(1), 2: lambda connection: steps.append(2)},
    )
    fresh = tmp_path / "fresh.sqlite3"
    with journal.writing(fresh) as connection:
        journal.prepare(connection, schema)
    with journal.reading(fresh) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (3,)
        assert connection.execute("SELECT COUNT(*) FROM tags").fetchone() == (0,)
    older = tmp_path / "older.sqlite3"
    with journal.writing(older) as connection:
        connection.execute(_CREATE[0])
        connection.execute("PRAGMA user_version=1")
    for _ in range(2):
        with journal.writing(older) as connection:
            journal.prepare(connection, schema)
    assert steps == [1, 2]
    with journal.reading(older) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (3,)


def test_unknown_or_unversioned_journals_are_refused_without_changing_them(tmp_path: Path) -> None:
    # Defect: a newer, unmigratable or foreign journal is opened, partly migrated or rewritten.
    schema = journal.Schema(3, _CREATE, {2: _dropped})
    for name, version in (("newer", 4), ("unmigratable", 1), ("unversioned", 0)):
        path = tmp_path / f"{name}.sqlite3"
        with journal.writing(path) as connection:
            connection.execute(_CREATE[0])
            connection.execute("INSERT INTO notes VALUES (1, 'existing')")
            connection.execute(f"PRAGMA user_version={version}")
        before = path.read_bytes()
        with TestCase().assertRaises(journal.SchemaVersionError), journal.writing(path) as connection:
            journal.prepare(connection, schema)
        assert path.read_bytes() == before, name


def test_reading_an_absent_journal_creates_nothing(tmp_path: Path) -> None:
    # Defect: a read creates an empty journal or directory, or a rolled-back first write looks like a journal.
    missing = tmp_path / "missing" / "edits.sqlite3"
    with journal.reading_existing(missing) as connection:
        assert connection is journal.Absent.JOURNAL
    assert not missing.parent.exists()
    abandoned = tmp_path / "abandoned.sqlite3"
    with TestCase().assertRaisesRegex(RuntimeError, "fixture"), journal.writing(abandoned) as connection:
        connection.execute(_CREATE[0])
        raise RuntimeError("fixture failure before the first commit")
    with journal.reading_existing(abandoned) as connection:
        assert connection is journal.Absent.JOURNAL
    with journal.writing(abandoned) as connection:
        connection.execute(_CREATE[0])
    with journal.reading_existing(abandoned) as connection:
        assert connection is not journal.Absent.JOURNAL
        assert connection.execute("SELECT COUNT(*) FROM notes").fetchone() == (0,)
