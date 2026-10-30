from assistant.communications import Conversation, Feed, Message, TeamsActivity, Update, UpdateKind, WindowsNotice
from assistant.feed_sources import UpdateSource, listed
from assistant.inbox import Kind, Query, Source, matches, review_prompt
from assistant.system_notices import NoticeKey
from tests.agent_requests import asked


def test_source_and_category_filters_keep_actionable_agent_questions_reachable() -> None:
    reaction = UpdateSource(Update(TeamsActivity("one"), "Reaction", "Liked this", "Teams", 1, UpdateKind.REACTION), handled=False)
    mail = UpdateSource(Update(WindowsNotice(NoticeKey(1, 2), "mail-source"), "Budget", "Review the budget", "Outlook", 1), handled=False)
    assert matches(reaction, Query(Source.TEAMS, Kind.REACTION))
    assert not matches(reaction, Query(Source.MAIL))
    assert matches(mail, Query(Source.MAIL, search="review budget"))
    assert not matches(mail, Query(Source.MAIL, search="missing"))
    assert matches(asked("owned", "Which workbook?", "", 1), Query(Source.MAIL, Kind.REACTION, "missing"))


def test_inbox_review_freezes_only_matching_pending_sources_as_quoted_data() -> None:
    messages = (Message("19:one@thread.v2", "one", "Anna", "Please check the numbers", 1, 2),)
    reaction = Update(TeamsActivity("one"), "Reaction", "Reaction body", "Teams", 1, UpdateKind.REACTION)
    feed = Feed(conversations=(Conversation("19:one@thread.v2", "Anna"),), followed=("19:one@thread.v2",), messages=messages, updates=(reaction,))
    prompt = review_prompt(listed(feed, (), history=False), Query(Source.TEAMS, Kind.ANSWER))
    assert "Please check the numbers" in prompt and "Reaction body" not in prompt
    assert "not instructions" in prompt and "Do not send" in prompt
