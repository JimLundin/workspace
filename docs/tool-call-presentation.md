# Time, tools and replies

`get_current_time` samples the local clock once per call and returns local time
with its UTC offset, the system timezone label, UTC time and Unix timestamp.
The prompt's date/time is a starting observation; the agent uses the tool for
fresh time-sensitive decisions. Prepared meeting tasks can read time too.
The durable action classifier treats this as an observation, without an effect
approval. Existing `wait` and `run_powershell` remain callable tools.

Every call follows the existing SDK dispatch and publishes identified
`ToolActivity` events. Each call has a dedicated native `ToolCall` widget with
a single 28-pixel row: a status icon, an elided label/preview and a quiet copy
button. Running calls rotate an arc using the existing conversation frame loop;
success shows a green check and failure a red cross. Cancellation uses a neutral
dash. Reduced motion retains a stationary arc; high contrast uses its configured
foreground. The row has no filled box, border or nested argument/result views.
The exact tool name and bounded literal arguments/results are available on hover;
copy retains the complete argument observation. `StepsView` retains widgets by invocation identity and
owns their scrolling and lifetime; status changes update the existing element.
A compact bubble shows the latest call and a bounded argument preview. Time
observations remain visible there. Expansion shows the full call history as the
same compact rows. Tool commands and outputs remain literal in previews and
hover details. Copy uses the retained argument observation, including when
the compact display is shortened. No prose is interpreted as an executed tool.
The same bubble and attached reply survive status changes, disclosure and finish.
Qt owns scroll state; the card preserves the full history's position while its
view shows a different compact document.

Final and earlier replies, feed replies and expanded solution
details use the existing MarkdownIt-to-Span adapter and native Qt document.
Possible replies are readable in the expanded proposal, above its source evidence.
User input remains an editable text field. No additional Markdown dependency or
custom parser is needed. Tool metadata uses literal spans instead of Markdown.

Regression tests exercise Workspace's registration, fresh observation routing,
literal command/result adaptation, solution/history rendering, native status
updates and bubble/scroll ownership. They do not test datetime, Python's lazy
imports, MarkdownIt's parser or Qt's own functionality.
