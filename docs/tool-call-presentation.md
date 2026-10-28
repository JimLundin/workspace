# Time, tools and replies

`get_current_time` samples the local clock once per call and returns local time
with its UTC offset, the system timezone label, UTC time and Unix timestamp.
The prompt's date/time is a starting observation; the agent uses the tool for
fresh time-sensitive decisions. Prepared meeting tasks can read time too.
The durable action classifier treats this as an observation, without an effect
approval. Existing `wait` and `run_powershell` remain callable tools.

Every call follows the existing SDK dispatch and publishes identified
`ToolActivity` events. Each call has a dedicated native `ToolCall` widget with
a header, status label, exact tool name, selectable argument and result views,
and a copy button. `StepsView` retains these widgets by invocation identity and
owns their scrolling and lifetime; status changes update the existing element.
A compact bubble shows the latest call and a bounded argument preview. Time
observations remain visible there. Expansion shows the full call history and
bounded results; PowerShell commands and outputs retain literal text with
monospace styling. Copy uses the retained argument observation, including when
the compact display is shortened. No prose is interpreted as an executed tool.
The same bubble and attached reply survive status changes, disclosure and finish.
Qt owns scroll state; the card preserves the full history's position while its
view shows a different compact document.

Final and earlier replies, feed replies, console questions and expanded solution
details use the existing MarkdownIt-to-Span adapter and native Qt document.
Possible replies are readable in the expanded proposal, above its source evidence.
User input remains an editable text field. No additional Markdown dependency or
custom parser is needed. Tool metadata uses literal spans instead of Markdown.

Regression tests exercise Workspace's registration, fresh observation routing,
literal command/result adaptation, solution/history rendering, native status
updates and bubble/scroll ownership. They do not test datetime, Python's lazy
imports, MarkdownIt's parser or Qt's own functionality.
