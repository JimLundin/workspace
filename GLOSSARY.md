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

**Work item**:
A pending source update to deal with. Messages in one followed chat share a
ticket; activity and Windows notifications retain their exact source identities.
Handling a ticket records the observed revisions, so a later arrival or edit can
remain pending. A ticket is independent of any agent task requested from it.
_Avoid_: Teams unread badge, agent task

**Agent request**:
A question or approval that an agent needs the person to answer before work can
continue. Its answer belongs to the originating request and session.
_Avoid_: Notification, task, chat message

**Notification filter**:
A personal choice about which sources appear in the pending feed and interrupt
the person. Filtering a source does not mean its work was handled.
_Avoid_: Dismissal, completed work

**Feed review**:
An explicit request for the agent to summarize a captured set of feed items
and suggest what to do next. A review is independent of acting on those items.
_Avoid_: Automatic reply, completed ticket

**Task**:
A requested outcome with its constraints, progress, and result. A task has a
lifetime independent of the conversation in which it was requested.
_Avoid_: Chat turn, command

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
