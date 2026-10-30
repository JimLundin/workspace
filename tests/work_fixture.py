"""Large task catalogs without repeating transaction overhead during test setup."""

import sqlite3
from collections.abc import Sequence
from contextlib import closing

from automation.store import TaskStore
from automation.task import Action, ActionVerified, RequestSource


def seed_tasks(store: TaskStore, identities: Sequence[str], source: RequestSource, *, at: float) -> None:
    """Clone one publicly submitted, validated ready task in a single transaction."""
    if not identities:
        return
    first = store.submit(identities[0], "Fixture work", "Fixture work", source, at=at)
    with closing(sqlite3.connect(store.path)) as database, database:
        database.executemany(
            "INSERT INTO tasks (id, title, prompt, source, priority, created_at, updated_at, revision, state, checkpoint, "
            "goal_revision, phase, routine_id, routine_revision, occurrence_id, wake_at) "
            "SELECT ?, title, prompt, source, priority, ?, ?, revision, state, checkpoint, "
            "goal_revision, phase, routine_id, routine_revision, occurrence_id, wake_at FROM tasks WHERE id=?",
            ((identity, at + index, at + index, first.id) for index, identity in enumerate(identities[1:], 1)),
        )


def seed_verified_actions(store: TaskStore, sample: Action, identities: Sequence[str]) -> None:
    """Clone a publicly recorded verified action; only identity and ordering vary.

    These later rows exist only to push the important earlier action off the
    display page. Verification, rejection and commit-failure cases still use
    the public write boundary and independent durable connections.
    """
    assert isinstance(sample.outcome, ActionVerified)
    with closing(sqlite3.connect(store.path)) as database, database:
        database.execute("PRAGMA foreign_keys=ON")
        database.execute("PRAGMA synchronous=FULL")
        database.executemany(
            "INSERT INTO actions(id,task_id,run_id,specification,started_at,updated_at,outcome,outcome_kind,fingerprint) "
            "SELECT ?,task_id,run_id,specification,?,?,outcome,outcome_kind,fingerprint FROM actions WHERE id=?",
            ((identity, sample.started_at + index * 2, sample.updated_at + index * 2, sample.id) for index, identity in enumerate(identities, 1)),
        )
