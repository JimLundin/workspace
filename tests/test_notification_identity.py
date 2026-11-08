"""Replayed notifications keep the prompt their saved task was created with."""

import hashlib

from assistant.feed_sources import Excerpt
from assistant.notification_agent import PROMPT_SCHEME, notification_task
from tests.feed_source_fixture import captured


def test_notification_prompt_is_frozen_for_its_saved_identity() -> None:
    # Defect: editing the notification prompt makes every replay after a restart
    # claim an existing task identity with different text, so it is refused.
    item = captured("frozen", Excerpt("Supplier", "The invoice is attached.", 1_700_000_000))
    identity, prompt, _profile = notification_task(item)
    key = item.identity + ":" + item.revision + ":" + PROMPT_SCHEME
    assert identity == "workspace-notification:" + hashlib.sha256(key.encode()).hexdigest()[:32]
    assert (PROMPT_SCHEME, hashlib.sha256(prompt.encode()).hexdigest()) == (
        "2",
        "2297bf34d6e5b284a736920455cd65e17c80b98afd7cb55dcd32f71b4478e407",
    ), "Saved notification tasks bind this prompt; a changed prompt needs a new PROMPT_SCHEME and this hash together."
