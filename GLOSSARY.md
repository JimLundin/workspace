# Glossary

**Task**: a requested outcome with its progress and result. It outlives the
conversation that asked for it (`contracts/task.py`).

**Run**: one period of execution of a task. A task that waits, resumes or
recovers has several runs.

**Checkpoint**: a bounded account of a task's progress that a later run
continues from.

**Action attempt**: a recorded intention to change something outside the task,
written before the effect. It does not prove the effect happened.

**Observed outcome**: evidence of what an action did. An interrupted attempt
stays uncertain until the affected state is inspected.

**Operation**: one exact tool call with its arguments and targets.

**Tool family**: the owner of a group of agent tools and each tool's schema,
effects and log text (`assistant/*_tools.py`).

**Task profile**: what a task is for (a general request, a feed handoff or a
self-review). It picks the conversation, context, tools and instructions
(`assistant/task_profiles.py`).

**Journal**: a SQLite file one owner keeps durably, such as `work.sqlite3` or a
recording's journal (`automation/journal.py`).

**Work thread**: the context for an ongoing outcome or responsibility, with its
sources, questions and actions (`contracts/personal_work.py`).

**Canvas bubble**: one piece of context on the canvas: a source, document,
note, question or action. A bubble can contain others.

**Feed item**: a pending update from a Teams chat, Teams activity or Windows
notification. Each kind of **feed source** defines its key and pending rule
(`assistant/feed_sources.py`).

**Card action**: what a `workspace://` link in agent text does: open the canvas
at a target (`contracts/card_actions.py`).

**Moment**: what takes over the bar's island: dictation, a question or a
**notice** (the agent's news). See [the island bar](docs/toolbar-design.md).

**Component**: a program the keeper runs, the layout or the assistant, listed
in the catalogue in `components.py`. It writes a **readiness marker** once it
is up.

**Keeper request**: a typed request in the keeper's inbox: install, undo or
restart (`keeper_control.py`).

**Installed version**: a commit in `%LOCALAPPDATA%\workspace\versions.git`
holding one state of the installed source. Undo checks out the version an
install replaced.

**Self-review**: a task in which the agent reviews its own runs and keeps
**lessons**, rules that later general runs follow
(`automation/self_review.py`).
