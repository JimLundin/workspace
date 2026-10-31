"""SQLite journals: the one owner of connection lifecycle, transactions and schema versions.

Every journal connection has the same durability, privacy and lock policy:
full synchronous commits, deleted content overwritten and new journals that
shrink as content is deleted. A write
holds `BEGIN IMMEDIATE` for its whole block and a read holds one deferred
snapshot, so a reader never pairs rows from two commits. Any exception rolls
the transaction back. Stores keep their schemas and domain codecs.
"""

import sqlite3
from collections.abc import Callable, Generator, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

# One busy wait for every journal: the work database is shared by the task,
# routine, context and personal-work owners, so their lock waits must agree.
BUSY_SECONDS = 5


class Cursor(Protocol):
    """Rows as SQLite returns them; each store validates its columns before use."""

    @property
    def rowcount(self) -> int: ...
    def fetchone(self) -> tuple[object, ...] | None: ...
    def fetchall(self) -> list[tuple[object, ...]]: ...
    def __iter__(self) -> Iterator[tuple[object, ...]]: ...


class Connection(Protocol):
    def execute(self, sql: str, parameters: Sequence[object] = (), /) -> Cursor: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


type Connect = Callable[[Path], Connection]


def open_journal(path: Path) -> Connection:
    """Autocommit mode: this module begins and ends every transaction explicitly."""
    return sqlite3.connect(path, timeout=BUSY_SECONDS, isolation_level=None)


class Absent(Enum):
    JOURNAL = "journal"


class SchemaVersionError(ValueError):
    """The journal was written by a schema this Workspace cannot open or migrate."""


@contextmanager
def _transaction(connection: Connection, begin: str) -> Generator[Connection]:
    try:
        connection.execute(f"PRAGMA busy_timeout={BUSY_SECONDS * 1000}")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA secure_delete=ON")
        connection.execute("PRAGMA foreign_keys=ON")
        if connection.execute("PRAGMA page_count").fetchone() == (0,):
            # Only a new, empty journal takes this setting, and only outside a transaction.
            # Setting it again on an existing journal would rewrite its header.
            connection.execute("PRAGMA auto_vacuum=FULL")
        connection.execute(begin)
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


@contextmanager
def writing(path: Path, connect: Connect = open_journal) -> Generator[Connection]:
    """One write transaction; it creates the journal file if needed."""
    with _transaction(connect(path), "BEGIN IMMEDIATE") as connection:
        yield connection


@contextmanager
def reading(path: Path, connect: Connect = open_journal) -> Generator[Connection]:
    """One read snapshot of a journal its owner has already created."""
    with _transaction(connect(path), "BEGIN") as connection:
        yield connection


@contextmanager
def reading_existing(path: Path, connect: Connect = open_journal) -> Generator[Connection | Absent]:
    """A read that reports a missing journal instead of creating an empty one."""
    if not path.is_file():
        yield Absent.JOURNAL
        return
    with reading(path, connect) as connection:
        # A first write that rolled back leaves an empty file: still no journal.
        empty = connection.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone() is None
        yield Absent.JOURNAL if empty else connection


type Migration = Callable[[Connection], None]


@dataclass(frozen=True, slots=True)
class Schema:
    """A versioned journal: statements that create it, and each step from an older version to the next."""

    version: int
    create: tuple[str, ...]
    migrations: Mapping[int, Migration]


def prepare(connection: Connection, schema: Schema) -> None:
    """Create an empty journal or migrate an older one inside the caller's write; refuse anything else."""
    match connection.execute("PRAGMA user_version").fetchone():
        case (int() as observed,):
            pass
        case _:
            raise SchemaVersionError("The journal has no readable schema version.")
    if observed == schema.version:
        return
    if observed == 0:
        if connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone() is not None:
            raise SchemaVersionError("The unversioned journal already contains tables.")
        for statement in schema.create:
            connection.execute(statement)
    elif observed > schema.version or any(version not in schema.migrations for version in range(observed, schema.version)):
        raise SchemaVersionError("This journal requires a different Workspace schema version.")
    else:
        for version in range(observed, schema.version):
            schema.migrations[version](connection)
    connection.execute(f"PRAGMA user_version={schema.version}")
