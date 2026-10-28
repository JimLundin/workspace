"""Source work joins the existing floating conversation without becoming agent instructions."""

from dataclasses import dataclass, replace
from enum import Enum, auto
from urllib.parse import urlencode

from .agent_session import Snapshot
from .communications import ChatTicket, Delivery, Message, Reply, Update, UpdateKind, WindowsNotice, chat_tickets
from .console_requests import Request, State
from .feed_origin import App, Origin, application
from .feed_triage import Assessment, Candidate, collect, identity
from .inbox import Query, matches
from .rich_text import Span, formatted
lazy from .action_text import readable

DEFAULT_QUERY = Query()


@dataclass(frozen=True, slots=True)
class SourceKey:
    source: str
    identity: str


class WorkState(Enum):
    PENDING = auto()
    HANDLED = auto()


@dataclass(frozen=True, slots=True)
class WorkItem:
    key: SourceKey
    item: ChatTicket | Message | Update | Reply | Request | Assessment
    title: str
    state: WorkState = WorkState.PENDING
    origins: tuple[Origin, ...] = ()
    evidence: tuple[Candidate, ...] = ()

    @property
    def created_at(self) -> float:
        return self.item.latest.created_at if isinstance(self.item, ChatTicket) else self.item.created_at

    @property
    def waiting(self) -> bool:
        return isinstance(self.item, Request) and self.item.state is State.WAITING


def origins(item: ChatTicket | Message | Update | Reply | Request | Assessment, session: Snapshot) -> tuple[Origin, ...]:
    match item:
        case ChatTicket() | Message() | Reply():
            return (Origin(App.TEAMS, App.TEAMS.value),)
        case Update(source=WindowsNotice(app_id=app_id), app_name=name):
            return (application(name, app_id),)
        case Update():
            return (Origin(App.TEAMS, App.TEAMS.value),)
        case Request(provider=provider):
            return (application(provider.value),)
        case Assessment(references=references):
            known = {identity(*update.key): origins(update, session)[0] for update in session.communications.updates}
            known.update({identity('console', request.identity): origins(request, session)[0] for request in session.console_requests})
            result: list[Origin] = []
            for ref, _revision in references:
                source = ref.partition(':')[0]
                origin = known.get(ref, Origin(App.TEAMS, App.TEAMS.value) if source in ('chat', 'activity', 'reply')
                                   else Origin(App.WINDOWS, App.WINDOWS.value) if source == 'windows'
                                   else Origin(App.WORKSPACE, App.WORKSPACE.value))
                if origin not in result:
                    result.append(origin)
            return tuple(result)


def observed(session: Snapshot, query: Query = DEFAULT_QUERY) -> tuple[WorkItem, ...]:
    if session.triage.enabled:
        proposals = tuple(proposal(session, item) for item in session.triage.actions)
        waiting = tuple(WorkItem(SourceKey('console', request.identity), request, request.provider.value)
                        for request in session.console_requests if request.state is State.WAITING)
        return (*proposals, *(replace(row, origins=origins(row.item, session)) for row in waiting))
    feed = session.communications
    rows: list[WorkItem] = []
    if query.history:
        for message in feed.messages:
            chat = feed.conversation(message.conversation)
            rows.append(WorkItem(SourceKey('chat-message', message.conversation + '/' + message.identity), message,
                                 chat.title if chat is not None else 'Teams', WorkState.PENDING if feed.unseen(message) else WorkState.HANDLED))
    else:
        for ticket in chat_tickets(feed):
            chat = feed.conversation(ticket.conversation)
            rows.append(WorkItem(SourceKey('chat', ticket.conversation), ticket, chat.title if chat is not None else 'Teams'))
    for update in feed.updates:
        hidden = isinstance(update.source, WindowsNotice) and update.source.app_id in feed.muted_apps
        if query.history or (feed.pending_update(update) and not hidden):
            rows.append(WorkItem(SourceKey(*update.key), update, update.app_name,
                                 WorkState.PENDING if feed.pending_update(update) else WorkState.HANDLED))
    for reply in feed.replies:
        rows.append(WorkItem(SourceKey('reply', reply.identity), reply, reply.title,
                             WorkState.HANDLED if reply.delivery in (Delivery.OBSERVED, Delivery.REVIEWED) else WorkState.PENDING))
    for request in session.console_requests:
        if query.history or request.state in (State.WAITING, State.INFORMATION):
            rows.append(WorkItem(SourceKey('console', request.identity), request, request.provider.value,
                                 WorkState.HANDLED if request.state in (State.ANSWERED, State.EXPIRED) else WorkState.PENDING))
    return tuple(replace(row, origins=origins(row.item, session)) for row in rows if not isinstance(row.item, Assessment)
                 and matches(row.item.latest if isinstance(row.item, ChatTicket) else row.item, query))


def reactions(session: Snapshot) -> tuple[str, str]:
    """One quiet emoji strip; reaction arrivals never become action bubbles."""
    updates = tuple(item for item in session.communications.updates
                    if item.kind is UpdateKind.REACTION and session.communications.pending_update(item))
    counts: dict[str, int] = {}
    for item in updates:
        evidence = item.title.casefold()
        label = item.text.partition('\n')[0].strip().casefold()
        mark = '·'
        for emoji, aliases in (('👍', ('👍', 'liked', 'like reaction', 'with like', 'thumb', 'gillade', 'like')),
                               ('❤️', ('❤', 'heart', 'love reaction', 'hjärta')),
                               ('😂', ('😂', '😆', 'laugh', 'skratt')),
                               ('😊', ('😊', '🙂', 'smile', 'leende')),
                               ('😮', ('😮', 'surprised', 'wow reaction')),
                               ('🎉', ('🎉', 'celebrat'))):
            if any(alias in evidence or label == alias for alias in aliases):
                mark = emoji
                break
        counts[mark] = counts.get(mark, 0) + 1
    text = '  '.join(mark + (f' {count}' if count > 1 or mark == '·' else '') for mark, count in counts.items())
    detail = '\n'.join(item.title for item in updates[-8:])
    return text, detail


def formatted_body(value: str, *tags: str) -> tuple[Span, ...]:
    return tuple(replace(span, text='\n' if span.text == '\n\n' else span.text, tags=(*span.tags, 'feed', *tags))
                 for span in formatted(value))


def heading(row: WorkItem) -> str:
    match row.item:
        case Assessment(title=title):
            return title
        case ChatTicket() | Message():
            return row.title
        case Update(title=title):
            return title
        case Request():
            return row.title + ' · needs you' if row.waiting else row.title
        case Reply(delivery=delivery):
            return 'To ' + row.title + ' · ' + delivery.name.lower()


def text(row: WorkItem) -> str:
    match row.item:
        case Assessment(summary=summary, suggestion=suggestion):
            return summary + ("\n\n" + suggestion if suggestion else "")
        case ChatTicket(latest=message):
            return message.sender + '\n' + message.text
        case Message(sender=sender, text=body):
            return sender + '\n' + body
        case Update(title=title, text=body):
            return title + '\n' + body
        case Request(title=title, detail=detail, questions=questions):
            return '\n'.join((title, *(question.text for question in questions), detail)).strip()
        case Reply(text=body, detail=detail):
            return body + ('\n' + detail if detail else '')


def link(action: str, caption: str, values: dict[str, str]) -> Span:
    return Span(caption, ('link',), 'workspace://' + action + '?' + urlencode(values))


def spans(row: WorkItem) -> tuple[Span, ...]:
    result = [Span(text(row))]
    actions: list[Span] = []
    match row.item:
        case Assessment(title=title, summary=summary, suggestion=suggestion):
            result = [Span(title + '\n', ('bold', 'feed', 'feed_title')),
                      Span('Request\n', ('bold', 'muted', 'feed')), *formatted_body(summary)]
            if suggestion:
                result.extend((Span('\n\nSuggested approach\n', ('bold', 'muted', 'feed')), *formatted_body(suggestion, 'feed_suggestion')))
        case ChatTicket() | Message():
            message = row.item.latest if isinstance(row.item, ChatTicket) else row.item
            result = [Span(message.sender + '\n', ('bold', 'feed')), *formatted_body(message.text)]
            values = {'chat': message.conversation, 'message': message.identity}
            actions = [link('help', 'Ask Workspace', values),
                       link('done' if row.state is WorkState.PENDING else 'reopen', 'Done' if row.state is WorkState.PENDING else 'Reopen', values),
                       link('open', 'Open Teams', values)]
            if isinstance(row.item, ChatTicket) and len(row.item.messages) > 1:
                result.append(Span(f'\n{len(row.item.messages)} messages in this exchange', ('muted',)))
        case Update() as update:
            result = [Span(update.title + '\n', ('bold', 'feed', 'feed_title')), *formatted_body(update.text)]
            values = {'source': update.key[0], 'message': update.key[1]}
            actions = [link('done' if row.state is WorkState.PENDING else 'reopen', 'Done' if row.state is WorkState.PENDING else 'Reopen', values),
                       link('help', 'Ask Workspace', values), link('update', 'Open source', values)]
            if isinstance(update.source, WindowsNotice) and update.source.app_id:
                actions.append(link('filter-app', 'Hide app', {'app': update.source.app_id}))
        case Request():
            return body_spans(row)
        case Reply(identity=identity, text=body, detail=detail, delivery=delivery):
            result = [*formatted_body(body), *(formatted_body('\n\n' + detail) if detail else ())]
            if delivery is Delivery.UNKNOWN:
                actions = [link('reviewed', 'I checked this in Teams', {'message': identity})]
    if actions:
        result.append(Span('\n'))
        for index, action in enumerate(actions):
            if index:
                result.append(Span('  ·  '))
            result.append(action)
    return tuple(result)


def body_spans(row: WorkItem) -> tuple[Span, ...]:
    if isinstance(row.item, Request):
        request = row.item
        supplied = dict(request.answers)
        pending_index = next((i for i in range(len(request.questions)) if i not in supplied), None)
        chosen = tuple(enumerate(request.questions)) if pending_index is None else ((pending_index, request.questions[pending_index]),)
        body = [Span(request.title + '\n', ('bold', 'feed'))] if request.title != 'Your answer is needed' else []
        if request.detail:
            body.extend(formatted_body(readable(request.detail)))
            body.append(Span('\n'))
        for index, question in chosen:
            body.extend((*formatted_body(question.text, 'bold'), Span('\n')))
            if question.multiple and index not in supplied:
                for option in question.options:
                    body.append(Span(option.label + (' · ' + option.description if option.description else '') + '\n', ('feed',)))
            if index in supplied:
                body.append(Span('You: ' + supplied[index] + '\n', ('muted', 'feed')))
        while body and not body[-1].text.strip():
            body.pop()
        if body:
            body[-1] = replace(body[-1], text=body[-1].text.rstrip())
        return tuple(body)
    values = spans(row)
    first = next((index for index, span in enumerate(values) if span.link.startswith('workspace://')), len(values))
    if first < len(values) and first and values[first - 1].text == '\n':
        first -= 1
    body = list(values[:first])
    while body and not body[-1].text.strip():
        body.pop()
    if body:
        body[-1] = replace(body[-1], text=body[-1].text.rstrip())
    return tuple(body)


def expanded_spans(row: WorkItem) -> tuple[Span, ...]:
    result = list(body_spans(row))
    if isinstance(row.item, Assessment):
        for option in row.item.solutions:
            result.extend((Span('\n\n'), Span(option.label + '\n', ('bold', 'muted', 'feed')),
                           *formatted_body(option.detail, 'feed_suggestion')))
        for source in row.evidence:
            result.extend((Span('\n\n'), Span(source.title + '\n', ('bold', 'muted', 'feed')),
                           *formatted_body(source.body)))
        if len(row.evidence) != len(row.item.references):
            result.extend((Span('\n\n'), Span('Some original source content is no longer available.', ('muted', 'feed'))))
    return tuple(result)


def action_spans(row: WorkItem) -> tuple[Span, ...]:
    if isinstance(row.item, Request):
        request = row.item
        supplied = dict(request.answers)
        first = next((i for i in range(len(request.questions)) if i not in supplied), None)
        if request.state is not State.WAITING or first is None or request.questions[first].multiple:
            return ()
        return tuple(link('console-option', option.label, {'message': request.identity, 'question': str(first), 'answer': option.label})
                     for option in request.questions[first].options)
    values = spans(row)
    actions = [span for span in values if span.link.startswith('workspace://')]
    return tuple(value for index, action in enumerate(actions)
                 for value in ((Span('  ·  '), action) if index else (action,)))


def proposal(session: Snapshot, item: Assessment) -> WorkItem:
    evidence = {(source.identity, source.revision): source for source in collect(session.communications, session.console_requests)}
    return WorkItem(SourceKey('triage', item.identity), item, item.title, origins=origins(item, session),
                    evidence=tuple(evidence[ref] for ref in item.references if ref in evidence))
