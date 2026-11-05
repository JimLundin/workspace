# Workspace work

Workspace carries out requested outcomes across conversations and
interruptions.

Device connections and distributed workspace access are defined in the
[Shared Workspace glossary](https://github.com/JimLundin/shared-workspace/blob/main/GLOSSARY.md).

## Language

**Personal work feed**:
The shared stream of colleague messages, agent exchanges and actionable updates.
Each item keeps its source and reply destination. The feed is one view across
conversations and tasks; opening it does not change their identities.
_Avoid_: One Teams chat, task list

**Feed item**:
A pending source update to deal with. Messages in one followed chat share a
ticket; activity and Windows notifications retain their exact source identities.
Handling a ticket records the observed revisions, so a later arrival or edit can
remain pending. A ticket is independent of any agent task requested from it.
_Avoid_: Teams unread badge, agent task

**Feed source**:
One kind of feed item: a chat ticket, a Teams activity or Windows notice, or a
sent reply. Each kind defines its key, origin application,
attention and triage evidence once. Attention is the single pending rule.
Triage assesses unresolved work. A reply still sending is settling. The feed
shows every source that is not resolved.
_Avoid_: Source string, identity prefix

**Card action**:
What a canvas link in agent text does: open the canvas at a target. The island
turns it into a canvas button; app arrivals never become notices. A link that is not exactly
one card action does nothing.
_Avoid_: Action URL, link string, feed card

**Work thread**:
The context for an ongoing outcome or responsibility, containing its related
sources, questions, research and actions. It organizes these contributions
without itself being another contribution.
_Avoid_: Work card, workflow card, feed item, agent task, Kanban ticket

**Canvas group**:
A named collection of related work contexts or contributions. Groups can be
nested, and a contribution can be relevant to several contexts.
_Avoid_: Execution task, copied source

**Focused canvas**:
A view of one work context, group or bubble and the contributions within it. Opening
that view retains the same sources, questions and actions shown in the overview.
_Avoid_: New task, separate copy

**Canvas bubble**:
A piece of context such as a source, document, note, question or recorded action.
A bubble may contain further pieces while remaining a reference in its own right.
_Avoid_: Work classification, duplicated source

**Work dismissal**:
A remembered decision that a work context is irrelevant or is not the person's
responsibility. Dismissed work can be restored without losing its context.
_Avoid_: Work completion, source deletion

**Web reference**:
A researched web page's original location and captured evidence within a work
context. A saved page document may accompany the reference.
_Avoid_: Browser attempt, complete archive

**Unconnected references**:
Collected evidence that has not yet been connected to a work context.
_Avoid_: Assigned work, agent finding

**Canvas relationship**:
An explicit connection between two bubbles, describing how their context relates.
It remains attached to those pieces when their containers are opened or collapsed.
_Avoid_: Containment, source assignment

**Canvas edit**:
A change the person makes on the canvas, such as moving, nesting, grouping,
expanding or relating bubbles, or editing a note. It applies to the canvas as it
is now, so changes the agent made since the canvas was last shown remain.
_Avoid_: Saved view copy, panel save

**Bubble contents**:
The pieces collected inside a bubble, such as individual emails within an email
conversation. Containment is distinct from that bubble's connections to work.
_Avoid_: Source connection, copied thread

**Document reference**:
A document's place in the work context, pointing to its local file or web location.
Its annotations and connections belong to the work alongside it.
_Avoid_: Uploaded copy, attachment preview

**Canvas investigation**:
Agent research that extends a work thread from changed source evidence. It
collects and arranges context, investigates document candidates, and asks the
user when a consequential choice remains unresolved. Its clarification resumes
the same execution within the same work context.
_Avoid_: Per-app notification, manual canvas population, duplicate work thread

**Source connection**:
A recorded relationship between a work thread and an observed email conversation,
Teams conversation, Kanban ticket, document or individual message, with the reason they belong together.
One source can contribute to several work threads.
_Avoid_: Duplicate task, copied conversation

**Agent request**:
A question that an agent needs the person to answer before work can continue.
Its answer belongs to the originating task and its current goal; the
conversation shows that same request. Typed and spoken replies become one text
answer at the input edge.
_Avoid_: Notification, task, chat message

**Notification filter**:
A personal choice about which sources appear in the pending feed and interrupt
the person. Filtering a source does not mean its work was handled. The
notification sources owner keeps it with Windows notices; every consumer asks
the feed whether an update needs attention: pending and not filtered.
_Avoid_: Dismissal, completed work

**Feed review**:
An explicit request for the agent to summarize a captured set of feed items
and suggest what to do next. A review is independent of acting on those items.
_Avoid_: Automatic reply, completed ticket

**Task**:
A requested outcome with its constraints, progress, and result. A task has a
lifetime independent of the conversation in which it was requested.
_Avoid_: Chat turn, command

**Task profile**:
What a requested task is for: a general request, a feed handoff or a
self-review. It owns the task's execution: the conversation its agent continues,
whether the agent sees the request's desktop context, its tools and
instructions, and what it recovers before a run.
_Avoid_: Task kind, agent mode

**Meeting**:
A conversation recorded as one event, with its own identity, start and observed
end, and associated transcript. The same meeting may contribute to several work threads.
_Avoid_: Transcript file, work thread, meeting notes

**Meeting transcript**:
The ordered text of a meeting's captured conversation, with time spans within
its captured audio. Transcription batches do not imply individual speaker turns.
_Avoid_: Meeting summary, attributed conversation

**Journal**:
A local SQLite file that one owner keeps durably: the work database, each
recording's journal. A write is all or
nothing and a read sees one moment. Reading a journal that does not exist
reports it absent instead of creating it.
_Avoid_: Database (for the owner's records), log

**Run**:
One period of execution of a task. A task can have several runs as it waits,
resumes, or recovers from an interruption.
_Avoid_: Task, session

**Conversation**:
The context shared by a sequence of requests and replies. Starting a new
conversation does not erase its tasks.
_Avoid_: Task history

**Action attempt**:
A recorded intention to change something outside the task itself. An attempt
does not establish that the intended effect occurred.
_Avoid_: Completed action

**Operation**:
One exact tool call with the arguments and targets it will act on. An action
attempt records one.
_Avoid_: Tool name

**Tool family**:
The owner of a group of agent tools and each tool's facts: what the model is
offered, whether a call reads or changes state, what it holds while it runs,
what proves its effect and what the visible log may show.
_Avoid_: Tool table, tool registry

**Web-app operation**:
One kind of Teams, Outlook or AIP Kanban interaction in a signed-in browser
page, declared once with its typed query, page script, application and typed
result. In-process readers perform it with typed values; the business tool
family offers it to the model. A model's call of one is an operation.
_Avoid_: App command, operation name

**Browser request**:
One typed operation on the automation browser: open, list, snapshot, act,
evaluate, capture, or close a page. The browser tool family
validates the model's arguments into one before any effect; in-process readers
construct them directly. A model's call of one is an operation.
_Avoid_: Browser command string, operation name

**Observed outcome**:
Evidence about what an action actually did. An interrupted attempt can retain
an uncertain outcome until the affected state is inspected.
_Avoid_: Assumed success

**Checkpoint**:
A bounded account of a task's progress that helps a later run continue from
known facts.
_Avoid_: Conversation dump

**Cancellation**:
The user's decision to end a task. An effect already underway can still acquire
an observed outcome without reviving the cancelled task.
_Avoid_: Shutdown, interruption

**Interruption**:
An execution break that leaves a task unfinished and recoverable. It does not
authorize blindly repeating an action with an uncertain outcome.
_Avoid_: Cancellation, failure

**Component catalogue**:
The one list of programs the keeper supervises: the layout, the assistant and
automation. Each entry names its entry module, control window, quit message,
shutdown budget and readiness marker.
_Avoid_: Program, role, miryoku (as a component name)

**Owner call**:
A work run's request to another Workspace owner, answered for that exact
invocation. The call is temporary; the owner's saved state remains the truth.
_Avoid_: Local bridge, feed bridge, console request

**Keeper request**:
A typed ask in the keeper's inbox folder: install a checked change, undo the
last install, keep the change on trial, or restart one catalogue component.
The keeper takes each once, oldest first, and refuses one it can't read with a
visible notice. Deployment pause and resume are separate component commands.
_Avoid_: Action, agent request (the user's ask of the agent)

**Readiness marker**:
The file a component writes once it is up. It names its writer by process id
and creation time, so a reader accepts it only from the process it observed.
_Avoid_: Ready flag

**Self-review**:
A task in which the agent reviews its own work. A review is queued after a run
that failed, ended blocked, left an action uncertain or not applied, or needed
an answer from the user. A daily review covers the previous
day. A review reads the task journal and keeps lessons. It may also check,
publish and install source changes. A review is never reviewed.
_Avoid_: Reflection, evaluation run

**Lesson**:
A saved preference written by the agent: one rule that every later general run
follows. Its source names the task it came from. The agent may update or remove
only its own lessons, never the user's preferences.
_Avoid_: Memory, agent note
