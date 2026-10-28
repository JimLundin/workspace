# Calendar context in the work feed

Workspace supplies the current local ISO date/time on every classification and
voice-agent feed read. Each source carries its original UTC creation time when
the provider exposes one. Relative phrases such as “tomorrow” belong to that
source's date. Recommendations use absolute dates and describe past events as
past.

Teams Activity has separate creation evidence and collection time. An absolute
provider timestamp becomes a `SourceDate`; a displayed label such as “Yesterday”
becomes a `SourceDateHint` anchored to its observation date. Missing evidence is
explicitly unknown. Collection time remains useful for stable arrival ordering;
it cannot establish when an event or message was created. Undated chat messages
also retain an unknown source date.

Open recommendations carry a saved local `reviewed_on` date. The triage owner
checks the local day while idle and reconsiders unchanged open work on a new day.
A restart on the same day retains completed reviews. Quiet, completed, dismissed
and rejected work retains its disposition. A corrected source date invalidates
only affected open recommendations and fences out model results using the old
date. Temporal metadata changes leave content revisions and handling identities
unchanged.

An expired one-off reminder can become quiet. An old request can remain useful
unfinished work; age alone does not complete it. Unknown dates call for checking
the timing rather than inventing urgency. Feed reads prioritize source evidence
referenced by the visible recommendations within the bounded source snapshot.

The 2026-10-27 diagnosis reproduced two defects: source dates were dropped from
the voice feed, and cached recommendations survived an October 20 to October 27
clock advance. Provider probing found that Teams Activity also substituted its
collection time for creation time. Main agent instructions already received a
fresh date on each invocation.

`tests/test_feed_dates.py` covers the model request, voice snapshot, provider
adapter, idle-day rollover, saved-review policy and date corrections.
`tests/test_windows_communications_browser.py` verifies timestamp extraction and
relative labels in an isolated fictional native Edge page. A synthetic check
against the configured model kept an expired reminder quiet while retaining an
unfinished request and an upcoming deadline. It used no personal message text.
