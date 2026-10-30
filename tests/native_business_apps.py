"""Business DOM policies against local apps in an existing disposable browser."""

import hashlib
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from assistant.browser import Browser
from assistant.browser_values import BrowserError
from assistant.web_apps import (
    KANBAN_BOARD,
    KANBAN_COMMENT,
    KANBAN_MOVE_TASK,
    KANBAN_READ_TASK,
    KANBAN_UPDATE_TASK,
    OUTLOOK_DOCUMENTS,
    OUTLOOK_DOWNLOAD_DOCUMENT,
    OUTLOOK_DRAFT_REPLY,
    OUTLOOK_OPEN_DOCUMENT,
    OUTLOOK_OPEN_MAIL,
    OUTLOOK_READ,
    OUTLOOK_SEARCH,
    TEAMS_DRAFT_REPLY,
    TEAMS_OPEN_CHAT,
    TEAMS_READ,
    BoardQuery,
    ChatDraft,
    ChatQuery,
    CollectedDocument,
    MailDocument,
    MailDownload,
    MailDraft,
    MailList,
    MailMessage,
    MailQuery,
    MailSearch,
    Origins,
    PreviewOpened,
    TaskComment,
    TaskEdit,
    TaskMove,
    TaskQuery,
    TeamsQuery,
    WebApps,
)
from automation.work_documents import LocalDocument
from tests import native_communications_browser
from tests.browser_fixture import Attachment, fixture
from tests.native_browser_fixture import request
from tests.test_browser import decoded

KANBAN_PAGE = """<!doctype html><meta charset="utf-8"><title>AIP Kanban fixture</title>
<button aria-label="Assignee filter: Jim">Jim</button>
<input placeholder="Search tasks..." value="">
<div data-tour="board-column"><div class="kanban-column-header"><span>Ready</span></div>
<div class="kanban-column-scroll"><div role="button" draggable="true" data-task-id="task-1"><p>Same title</p></div>
<div role="button" draggable="true" data-task-id="task-2"><p>Same title</p></div></div></div>
<div data-tour="board-column"><div class="kanban-column-header"><span>In Progress</span></div>
<div class="kanban-column-scroll"></div></div>
<script>
const records={'task-1':{title:'Same title',description:'First task',labels:'alpha',comments:[]},
 'task-2':{title:'Same title',description:'Second task',labels:'beta',comments:[]}};
let dragged=null;
for(const card of document.querySelectorAll('[data-task-id]')){
 card.addEventListener('dragstart',()=>dragged=card);
 card.addEventListener('dragend',()=>dragged=null);
 card.onclick=()=>{
  const id=card.dataset.taskId,record=records[id],root=document.createElement('div');
  root.setAttribute('role','dialog');root.setAttribute('aria-label',record.title);
  for(const [field,key] of [['title','detail-title'],['labels','detail-labels']]){
   const input=document.createElement('input');input.id=key;input.value=record[field];root.append(input);
  }
  const edit=document.createElement('button');edit.textContent='EDIT';
  edit.onclick=()=>{if(root.querySelector('[placeholder="Add description"]'))return;
   const body=document.createElement('textarea');body.placeholder='Add description';body.value=record.description;root.append(body);};
  root.append(edit);
  const comments=document.createElement('div');comments.textContent=record.comments.join('\\n');root.append(comments);
  const editor=document.createElement('textarea');editor.placeholder='Add a comment... type @ to mention someone';root.append(editor);
  const post=document.createElement('button');post.textContent='POST';post.disabled=true;
  editor.oninput=()=>post.disabled=!editor.value.trim();
  post.onclick=()=>{record.comments.push(editor.value);comments.textContent=record.comments.join('\\n');editor.value='';post.disabled=true;};root.append(post);
  const close=document.createElement('button');close.setAttribute('aria-label','Close task details');
  close.onclick=()=>{record.title=root.querySelector('#detail-title').value;record.labels=root.querySelector('#detail-labels').value;
   const body=root.querySelector('[placeholder="Add description"]');if(body)record.description=body.value;
   card.querySelector('p').textContent=record.title;root.remove();};root.append(close);document.body.append(root);
 };
}
for(const column of document.querySelectorAll('[data-tour="board-column"]')){
 column.ondragover=e=>e.preventDefault();column.ondrop=e=>{e.preventDefault();if(dragged)column.querySelector('.kanban-column-scroll').append(dragged);};
}
</script>"""


OUTLOOK_PAGE = """<!doctype html><meta charset="utf-8"><title>Outlook mail fixture</title>
<input id="topSearchInput" aria-label="Search for email, meetings, files and more.">
<button aria-label="Search">Search</button>
<div data-app-section="Ribbon"></div>
<div data-app-section="MessageList"><div role="listbox"></div></div>
<div data-app-section="MailReadCompose"></div>
<script>
document.cookie='workspace_attachment=verified; path=/';
const records=[{id:'conversation-mail-one',title:'Same subject',preview:'Alpha',body:'First mail'},
 {id:'conversation-mail-two',title:'Same subject',preview:'Beta',body:'Second mail Åäö'}];
const list=document.querySelector('[role="listbox"]'),pane=document.querySelector('[data-app-section="MailReadCompose"]');
function render(records){list.replaceChildren();
 for(const mail of records){const row=document.createElement('div');row.setAttribute('role','option');
  row.setAttribute('data-convid',mail.id);row.setAttribute('aria-selected','false');row.setAttribute('aria-label',mail.preview);
  row.textContent=mail.title+' '+mail.preview;list.append(row);
  row.onclick=()=>{for(const e of list.children)e.setAttribute('aria-selected',String(e===row));
   pane.replaceChildren();const heading=document.createElement('span');heading.id='CONV_'+mail.id+'_SUBJECT';
   heading.textContent=mail.title;const body=document.createElement('div');body.setAttribute('aria-label','Message body');
   const message=document.createElement('div');message.setAttribute('data-itemid',mail.id+'-message-1');message.append(body);
   const sender=document.createElement('span');sender.setAttribute('data-testid','message-sender');sender.textContent='Anna';
   message.prepend(sender);pane.append(heading,message);
   const earlier=document.createElement('div');earlier.setAttribute('data-itemid',mail.id+'-message-0');
   const earlierBody=document.createElement('div');earlierBody.setAttribute('aria-label','Message body');earlierBody.textContent='Earlier discussion';
   earlier.append(earlierBody);pane.append(earlier);
   const attachment=document.createElement('button');attachment.setAttribute('data-attachment-id',mail.id+'-attachment');
   attachment.setAttribute('aria-label','Atlas-v2.txt, attachment, version two, 24 bytes');
   const link=document.createElement('a');link.href='/attachment';attachment.append(link);pane.append(attachment);
   attachment.onclick=()=>{const preview=document.createElement('div');preview.setAttribute('role','dialog');
    preview.textContent='Atlas document version two. Approved by Anna.';const close=document.createElement('button');
    close.textContent='Close preview';close.onclick=()=>preview.remove();preview.append(close);document.body.append(preview);};
   // The pane mounts before mail text arrives, just as it does in Outlook.
   setTimeout(()=>body.textContent=mail.body,150);
   const reply=document.createElement('div');reply.setAttribute('role','menuitem');reply.setAttribute('aria-label','Reply');pane.append(reply);
   reply.onclick=()=>{pane.replaceChildren();
    const subject=document.createElement('input');subject.setAttribute('aria-label','Subject');subject.value='Re: '+mail.title;pane.append(subject);
    const to=document.createElement('div');to.setAttribute('contenteditable','true');to.setAttribute('aria-label','To');
    const recipient=document.createElement('span');recipient.setAttribute('contenteditable','false');
    recipient.setAttribute('aria-label','Colleague <colleague@example.test>');recipient.textContent='Colleague';to.append(recipient);pane.append(to);
    const editor=document.createElement('div');editor.setAttribute('role','textbox');editor.setAttribute('aria-label','Message body');
    editor.setAttribute('contenteditable','true');const blank=document.createElement('div');blank.append(document.createElement('br'));
    editor.append(blank);pane.append(editor);
    editor.oninput=()=>document.body.dataset.saved=editor.innerText;
    setTimeout(()=>{const signature=document.createElement('div');signature.id='Signature';
     signature.textContent='Local signature';editor.append(signature);},150);
    const send=document.createElement('button');send.setAttribute('aria-label','Send');send.textContent='Send';
    send.onclick=()=>document.body.dataset.sent=editor.innerText;pane.append(send);
   };
  };
 }
}
render(records);
document.querySelector('button[aria-label="Search"]').onclick=()=>{
 const query=document.querySelector('#topSearchInput').value.toLowerCase();
 pane.replaceChildren();list.replaceChildren();list.setAttribute('aria-busy','true');
 setTimeout(()=>{render(records.filter(e=>e.preview.toLowerCase().includes(query)));list.removeAttribute('aria-busy');
  const heading=document.createElement('span');heading.setAttribute('aria-label','Results');heading.textContent='Results';list.prepend(heading);
  if(!list.querySelector('[role="option"]'))list.append(document.createTextNode("We didn't find anything"));},250);
};
</script>"""


def verify_business_apps(browser: Browser) -> None:
    # Defects: selectors hit a same-title task/chat, a stale comparison still
    # edits, save readback fails, filters change, or a reply sends immediately.
    # Every operation decodes its script's real output with its result type.
    with fixture(
        pages={
            "/kanban": KANBAN_PAGE,
            "/teams": native_communications_browser.PAGE,
            "/outlook": OUTLOOK_PAGE,
            "/attachment": Attachment(b"Atlas approved version two\x00\xff", "application/octet-stream", "workspace_attachment=verified"),
        }
    ) as origin:
        app = WebApps(browser, Origins(origin.rstrip("/"), (origin.rstrip("/"),), (origin.rstrip("/"),)))
        target = request(browser, "open", url=origin + "kanban")["target_id"]
        assert isinstance(target, str)
        kanban_target = target
        cancel = threading.Event()

        board = app.run(KANBAN_BOARD, BoardQuery(target, limit=1), cancel)
        assert board.next_offset == 1 and "Jim" in str(board.filters)
        assert "task-2" in str(app.run(KANBAN_BOARD, BoardQuery(target, offset=1), cancel))
        detail = app.run(KANBAN_READ_TASK, TaskQuery(target, "task-2"), cancel)
        assert detail.fields["description"] == "Second task" and "First task" not in str(detail)
        with TestCase().assertRaisesRegex(BrowserError, "changed"):
            app.run(KANBAN_UPDATE_TASK, TaskEdit(target, "task-2", "labels", "alpha", "wrong"), cancel)
        assert app.run(KANBAN_READ_TASK, TaskQuery(target, "task-2"), cancel).fields["labels"] == "beta"
        edited = app.run(KANBAN_UPDATE_TASK, TaskEdit(target, "task-2", "description", "Second task", "Updated Åäö"), cancel)
        assert edited.value == "Updated Åäö"
        assert app.run(KANBAN_MOVE_TASK, TaskMove(target, "task-2", "Ready", "In Progress"), cancel).changed
        with TestCase().assertRaisesRegex(BrowserError, "moved"):
            app.run(KANBAN_MOVE_TASK, TaskMove(target, "task-2", "Ready", "In Progress"), cancel)
        assert app.run(KANBAN_COMMENT, TaskComment(target, "task-2", "Reviewed once"), cancel).text == "Reviewed once"
        assert "Reviewed once" in app.run(KANBAN_READ_TASK, TaskQuery(target, "task-2"), cancel).text
        with TestCase().assertRaisesRegex(BrowserError, "different application"):
            browser.web_app(KANBAN_BOARD, BoardQuery(target), cancel)
        teams_target = request(browser, "open", url=origin + "teams")["target_id"]
        assert isinstance(teams_target, str)
        chats = app.run(TEAMS_READ, TeamsQuery(teams_target), cancel)
        assert {"19:one@thread.v2", "19:two@thread.v2"} <= {chat.identity for chat in chats.conversations}
        app.run(TEAMS_OPEN_CHAT, ChatQuery(teams_target, "19:two@thread.v2"), cancel)
        assert "Second chat" in str(app.run(TEAMS_READ, TeamsQuery(teams_target), cancel))
        draft = app.run(TEAMS_DRAFT_REPLY, ChatDraft(teams_target, "19:two@thread.v2", "Unsent draft Åäö"), cancel)
        assert draft.text == "Unsent draft Åäö"
        with TestCase().assertRaisesRegex(BrowserError, "contains a draft"):
            app.run(TEAMS_DRAFT_REPLY, ChatDraft(teams_target, "19:two@thread.v2", "Replacement"), cancel)
        with TestCase().assertRaisesRegex(BrowserError, "contains a draft"):
            app.run(TEAMS_OPEN_CHAT, ChatQuery(teams_target, "19:one@thread.v2"), cancel)
        received = browser.request(
            "evaluate",
            {
                "target_id": teams_target,
                "expression": "({draft:document.querySelector('[contenteditable]').innerText,sent:document.body.dataset.sent||''})",
            },
            cancel,
        )
        assert "Unsent draft Åäö" in received.text and decoded(received.text)["sent"] == ""
        mail_target = request(browser, "open", url=origin + "outlook")["target_id"]
        assert isinstance(mail_target, str)
        verify_outlook(browser, app, mail_target)
        cancel.set()
        with TestCase().assertRaisesRegex(BrowserError, "Stopped"):
            app.run(KANBAN_COMMENT, TaskComment(kanban_target, "task-1", "Never"), cancel)
        # Explicitly close only the pages owned by this fixture.
        for page in (kanban_target, teams_target, mail_target):
            request(browser, "close", target_id=page)


def verify_outlook(browser: Browser, app: WebApps, target: str) -> None:
    # Defects: Outlook mail is routed by a colliding title, read before its body
    # loads, searched using stale rows, or a signature/draft is overwritten.
    cancel = threading.Event()
    assert app.run(OUTLOOK_READ, MailList(target, limit=1), cancel).next_offset == 1
    assert "conversation-mail-two" in str(app.run(OUTLOOK_READ, MailList(target, offset=1), cancel))
    opened = app.run(OUTLOOK_OPEN_MAIL, MailQuery(target, "conversation-mail-two"), cancel)
    assert "Second mail Åäö" in str(opened) and "First mail" not in str(opened)
    # Defect: aggregate text is split into invented mail, rendered pieces lose
    # their stable identities, or an unsent editor becomes conversation evidence.
    assert opened.mail is not None
    assert opened.mail.messages == (
        MailMessage("conversation-mail-two-message-1", "Anna", "Second mail Åäö"),
        MailMessage("conversation-mail-two-message-0", "", "Earlier discussion"),
    )
    verify_mail_documents(browser, app, target)
    with TestCase().assertRaisesRegex(BrowserError, "exact mail conversation"):
        app.run(OUTLOOK_DRAFT_REPLY, MailDraft(target, "conversation-mail-one", "Wrong recipient"), cancel)
    results = app.run(OUTLOOK_SEARCH, MailSearch(target, "beta"), cancel)
    assert results.rendered_total == 1 and "conversation-mail-one" not in str(results)
    assert app.run(OUTLOOK_SEARCH, MailSearch(target, "no-such-message"), cancel).rendered_total == 0
    assert app.run(OUTLOOK_SEARCH, MailSearch(target, "beta"), cancel).rendered_total == 1
    app.run(OUTLOOK_OPEN_MAIL, MailQuery(target, "conversation-mail-two"), cancel)
    reply = app.run(OUTLOOK_DRAFT_REPLY, MailDraft(target, "conversation-mail-two", "Reviewed Åäö\nSecond line"), cancel)
    assert reply.recipients == ("Colleague <colleague@example.test>",)
    assert app.run(OUTLOOK_READ, MailList(target), cancel).editor_open
    with TestCase().assertRaisesRegex(BrowserError, "open draft"):
        app.run(OUTLOOK_SEARCH, MailSearch(target, "alpha"), cancel)
    with TestCase().assertRaisesRegex(BrowserError, "open draft"):
        app.run(OUTLOOK_OPEN_MAIL, MailQuery(target, "conversation-mail-one"), cancel)
    with TestCase().assertRaisesRegex(BrowserError, "open draft"):
        app.run(OUTLOOK_DRAFT_REPLY, MailDraft(target, "conversation-mail-two", "Replacement"), cancel)
    reply_state = decoded(
        browser.request(
            "evaluate",
            {
                "target_id": target,
                "expression": "({draft:document.querySelector('[aria-label=\"Message body\"]').innerText,"
                "saved:document.body.dataset.saved,sent:document.body.dataset.sent||''})",
            },
            cancel,
        ).text
    )
    assert "Reviewed Åäö\nSecond line" in str(reply_state["draft"]) and "Local signature" in str(reply_state["draft"])
    assert "Reviewed Åäö" in str(reply_state["saved"]) and reply_state["sent"] == ""
    with TestCase().assertRaisesRegex(BrowserError, "different application"):
        browser.web_app(OUTLOOK_SEARCH, MailSearch(target, "Never"), cancel)


def verify_mail_documents(browser: Browser, app: WebApps, target: str) -> None:
    cancel = threading.Event()
    # Defect: attachment discovery uses another conversation, anonymous fetch
    # loses cookies, or collection replaces an existing document version.
    documents = app.run(OUTLOOK_DOCUMENTS, MailQuery(target, "conversation-mail-two"), cancel)
    (file,) = documents.attachments
    assert file.attachment_id == "conversation-mail-two-attachment" and not file.ambiguous
    assert file.url is not None
    with TestCase().assertRaisesRegex(BrowserError, "exact mail conversation"):
        app.run(OUTLOOK_DOCUMENTS, MailQuery(target, "conversation-mail-one"), cancel)
    with TemporaryDirectory(prefix="workspace-attachment-") as folder:
        path = Path(folder) / "Atlas-v2.txt"

        def collect(url: str, destination: Path) -> CollectedDocument:
            query = MailDownload(target, "conversation-mail-two", "conversation-mail-two-attachment", url, LocalDocument(str(destination)))
            return app.run(OUTLOOK_DOWNLOAD_DOCUMENT, query, cancel)

        saved = collect(file.url, path)
        content = path.read_bytes()
        assert content == b"Atlas approved version two\x00\xff" and saved.sha256 == hashlib.sha256(content).hexdigest()
        with TestCase().assertRaises(FileExistsError):
            collect(file.url, path)
        assert path.read_bytes() == content
        with TestCase().assertRaisesRegex(BrowserError, "changed"):
            collect(file.url + "?stale", Path(folder) / "stale.txt")
        assert not (Path(folder) / "stale.txt").exists()
    preview = app.run(OUTLOOK_OPEN_DOCUMENT, MailDocument(target, "conversation-mail-two", "conversation-mail-two-attachment"), cancel)
    assert isinstance(preview, PreviewOpened) and "version two" in preview.preview
    browser.request(
        "evaluate", {"target_id": target, "expression": "(()=>{document.querySelector('[role=dialog] button').click();return true;})()"}, cancel
    )
