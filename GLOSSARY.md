# Workspace work

Workspace carries out requested outcomes and standing instructions across
conversations and interruptions.

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
A question or approval that an agent needs the person to answer before work can
continue. An approval covers one exact operation. Its answer belongs to the
originating task and its current goal; the conversation shows that same request.
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
What a requested task is for: a general request, a feed handoff or a meeting
follow-up. It selects the agent's tools, instructions and completion check.
Work for a standing instruction runs as a general request.
_Avoid_: Task kind, agent mode

**Meeting follow-up**:
Notes, decisions, actions and unsent email drafts prepared from recordings the
person selected. Their transcripts are frozen when it is prepared. Its agent
sees only those sources and the follow-up's tools, and it completes only after
its package is published and each draft's save is verified. The person reviews
and edits the resulting actions and drafts.
_Avoid_: Meeting-notes routine, meeting summary

**Meeting-notes routine**:
A standing instruction, installed disabled, that writes notes for each
transcript completed after it is enabled. It responds to one transcript per
trigger occurrence and does not prepare a meeting follow-up.
_Avoid_: Meeting follow-up, follow-up drafts

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
One exact tool call with the arguments and targets it will act on. An approval
covers exactly one operation, and an action attempt records one.
_Avoid_: Tool name, approved tool

**Tool family**:
The owner of a group of agent tools and each tool's facts: what the model is
offered, whether a call reads or changes state, what it holds while it runs,
what proves its effect and what the visible log may show.
_Avoid_: Tool table, tool registry

**Observed outcome**:
Evidence about what an action actually did. An interrupted attempt can retain
an uncertain outcome until the affected state is inspected.
_Avoid_: Assumed success

**Checkpoint**:
A bounded account of a task's progress that helps a later run continue from
known facts.
_Avoid_: Conversation dump

**Standing instruction**:
A saved instruction that authorizes work when a specified trigger occurs.
Enabling it determines when it begins responding to those occurrences.
_Avoid_: Background prompt, permanent task

**Trigger occurrence**:
One identifiable event or scheduled time to which a standing instruction
responds. Repeated delivery of an occurrence refers to the same work.
_Avoid_: New task

**Accepted handoff**:
A standing instruction's commitment to carry out a trigger occurrence. Later
editing or disabling the instruction does not revoke work already accepted;
that task can be cancelled separately.
_Avoid_: Unobserved event, pending trigger

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

**Local bridge**:
The authenticated loopback listener through which a local client reaches
Workspace owners. The work bridge carries the agents' feed, work and canvas
tool requests; the hook bridge carries console CLI hook events. Each bridge
publishes an endpoint file with its address and token. An owner's refusal is a
typed reply, not a transport error.
_Avoid_: Feed bridge, console server

**Readiness marker**:
The file a component writes once it is up. It names its writer by process id
and creation time, so a reader accepts it only from the process it observed.
_Avoid_: Ready flag
