import sqlite3
from collections.abc import Callable, Generator, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Protocol, assert_never

BUSY_SECONDS = 5


class Durability(Enum):
    FULL = auto()
    """Rollback journal, synchronous=FULL: every commit survives power loss; a reader blocks a writer's commit."""
    WAL = auto()
    """Write-ahead log, synchronous=NORMAL: readers and the writer never block each other and commits do
    not wait for the disk. A crash keeps every commit; power loss may lose the latest commits, never consistency."""


class Cursor(Protocol):
    @property
    def rowcount(self) -> int: ...
    def fetchone(self) -> tuple[object, ...] | None: ...
    def fetchall(self) -> list[tuple[object, ...]]: ...
    def __iter__(self) -> Iterator[tuple[object, ...]]: ...


class Connection(Protocol):
    def execute(
        self, _sql: str, parameters: Sequence[object] = (), /
    ) -> Cursor: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


type Connect = Callable[[Path], Connection]


def open_journal(path: Path) -> Connection:
    return sqlite3.connect(path, timeout=BUSY_SECONDS, isolation_level=None)


class SchemaVersionError(ValueError): ...


@contextmanager
def _transaction(
    connection: Connection, begin: str, durability: Durability
) -> Generator[Connection]:
    try:
        connection.execute(f"PRAGMA busy_timeout={BUSY_SECONDS * 1000}")
        match durability:
            case Durability.FULL:
                connection.execute("PRAGMA synchronous=FULL")
            case Durability.WAL:
                connection.execute("PRAGMA synchronous=NORMAL")
            case _:
                assert_never(durability)
        connection.execute("PRAGMA secure_delete=ON")
        connection.execute("PRAGMA foreign_keys=ON")
        if connection.execute("PRAGMA page_count").fetchone() == (0,):
            connection.execute("PRAGMA auto_vacuum=FULL")
        if durability is Durability.WAL:
            connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(begin)
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


@contextmanager
def writing(
    path: Path,
    connect: Connect = open_journal,
    durability: Durability = Durability.FULL,
) -> Generator[Connection]:
    with _transaction(
        connect(path), "BEGIN IMMEDIATE", durability
    ) as connection:
        yield connection


@contextmanager
def reading(
    path: Path, connect: Connect = open_journal
) -> Generator[Connection]:
    with _transaction(connect(path), "BEGIN", Durability.FULL) as connection:
        yield connection


@dataclass(frozen=True, slots=True)
class Schema:
    version: int
    create: tuple[str, ...]


def prepare(connection: Connection, schema: Schema) -> None:
    match connection.execute("PRAGMA user_version").fetchone():
        case (int() as observed,):
            pass
        case _:
            raise SchemaVersionError(
                "The journal has no readable schema version."
            )
    if observed == schema.version:
        return
    if observed == 0:
        if (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchone()
            is not None
        ):
            raise SchemaVersionError(
                "The unversioned journal already contains tables."
            )
        for statement in schema.create:
            connection.execute(statement)
    else:
        raise SchemaVersionError(
            f"The journal has schema version {observed}; this Workspace reads only version {schema.version} and does not migrate."
        )
    connection.execute(f"PRAGMA user_version={schema.version}")
