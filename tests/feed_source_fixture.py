"""Fictional triage evidence for board decisions that do not depend on a source variant."""

import hashlib
from collections.abc import Iterable
from typing import Literal

from assistant.communications import SourceDate, SourceDateStatus
from assistant.feed_contracts import SCREENING, ScreenedSource, Screening
from assistant.feed_origin import App, Origin
from assistant.feed_sources import Candidate, Excerpt, SourceKind
from tests.fake_endpoint import Reply
lazy from tests.test_agent import says


def screening_reply(items: Iterable[tuple[str, Literal["action", "quiet"]]]) -> Reply:
    return says(SCREENING.dump_json(Screening(tuple(ScreenedSource(identity, disposition) for identity, disposition in items))).decode())


def captured(key: str, excerpt: Excerpt) -> Candidate:
    return Candidate(
        "chat:" + key,
        hashlib.sha256((excerpt.title + "\n" + excerpt.body).encode()).hexdigest(),
        SourceKind.CHAT,
        Origin(App.TEAMS, App.TEAMS.value),
        excerpt.title,
        excerpt.body,
        excerpt.created_at,
        source_time=SourceDate(excerpt.created_at) if excerpt.created_at > 0 else SourceDateStatus.UNKNOWN,
    )
