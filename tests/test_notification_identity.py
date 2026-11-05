"""Replayed notifications keep the prompt their saved task was created with."""

import hashlib

from assistant.feed_sources import Excerpt
from assistant.notification_agent import notification_task
from tests.feed_source_fixture import captured


def test_notification_prompt_is_frozen_for_its_saved_identity() -> None:
    # Defect: editing the notification prompt makes every replay after a restart
    # claim an existing task identity with different text, so it is refused.
    item = captured("frozen", Excerpt("Supplier", "The invoice is attached.", 1_700_000_000))
    identity, prompt, _profile = notification_task(item)
    assert identity == "workspace-notification:" + hashlib.sha256((item.identity + ":" + item.revision).encode()).hexdigest()[:32]
    assert hashlib.sha256(prompt.encode()).hexdigest() == "a519cbff85de5abd04ef5017da519354804f1177f0645ccdd6d6593c219eafdd", (
        "Saved notification tasks bind this prompt; keep it byte-identical."
    )
