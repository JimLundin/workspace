# Meeting follow-up

Workspace can turn one completed recording, or several parts of the same meeting,
into source-linked notes, recorded decisions, action items, and complete email
drafts. Open **Meeting follow-up…** from the tray, or **Meetings** in Work,
select the completed recordings and choose **Prepare notes & follow-ups**.
Selected segments are combined in recording order.

The work continues in the background. Its status appears with the saved meeting
selection and in Work. Closing the view leaves the task and its results intact.
If the task needs input or cannot finish, Work shows the question or the reason
and provides the existing resume controls.

Each result includes:

- Notes and decisions with quotations linking back to the selected recordings.
- Actions with an owner and due wording when the transcript states them, and
  explicit **Not stated** fields otherwise.
- Complete follow-up drafts, with recipients only where the source identifies
  them. Unknown email addresses stay empty.
- A package containing the generated files and exact source snapshots.

Multiple segments keep their separate identities and capture notices. A
microphone interruption remains a gap; Workspace does not reconstruct missing
audio. For an interview, the result records the discussion and administrative
next steps without scoring candidates or making a hiring decision.

Use the action and draft editors to review the result. A save is confirmed only
after its exact edit has been stored. Concurrent changes produce a conflict and
retain the entered text. Generated files and later edits have separate saved
versions, so a retry cannot replace reviewed content. Where several generated
packages exist, select the intended version explicitly.

During preparation, Workspace saves unsent drafts to an already running classic
Outlook session when its draft store can be verified. Otherwise, it saves full
`.eml` files and reports that destination. It does not start Outlook or send
messages. Retrying a saved draft checks the same destination and content;
changes made in Outlook or a missing draft are preserved for inspection.
Local edits made after preparation remain local and do not silently update an
Outlook draft. Open the selected local draft explicitly for further mail review.

Saved work lives under `%LOCALAPPDATA%\workspace\work\meeting-followups`:

| Location | Contents |
| --- | --- |
| `preparations` | Each prepared selection's exact transcript bytes and source details, one file per content digest |
| `packages` | Notes, action CSV, draft files, source snapshots, and edit history |
| `mail` | Verified mail destination records and any fallback email files |

Folder names under `packages` are 16-character digest prefixes, so every file
stays within 58 characters of that folder and opens in ordinary programs. Each
package still verifies its full task identity and content digest when read.

The implementation uses Workspace's existing durable work controller. The
selection is saved before submission, and the task's profile names it by content
digest; a missing or changed selection blocks the task before the model runs.
Every publication and mail save passes through the action journal, and each mail
save records the exact draft revision it wrote. Follow-ups prepared before
selections were content-addressed are no longer listed; their packages and mail
files remain on disk. Packages store their recordings and follow-up claims in
package format 2; packages and edits saved in the earlier format are no longer
read. Model output is validated against the selected transcript bytes before
publication; one shape generates the offered tool schema, validates the claims
and stores them. A model reply alone cannot mark the workflow complete.
The meeting worker's tools are limited to those sources, artifacts, draft
saving, and durable questions/recovery.

Behavioral checks use real SQLite databases, files, local HTTP model fixtures,
and explicit mail transport dependencies. The validation record distinguishes
these checks, targeted mutation results, the real meeting run, and native
Outlook evidence.
