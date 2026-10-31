"""Teams, Outlook and AIP Kanban operations in an opted-in browser's signed-in pages.

Each web-app operation is declared once: its typed query, page script,
application and typed result. The browser owns CDP, page wakeup and
cancellation. These adapters own exact selection and DOM contracts observed in
the applications. No credentials leave the page. Kanban's filters remain in
effect; missing cards are never guessed.
"""

import contextlib
import threading
from dataclasses import KW_ONLY, dataclass, field
from enum import Enum, auto
from typing import Annotated, Final, Literal, Protocol, assert_never

from pydantic import Field, TypeAdapter, ValidationError

from assistant.browser_documents import Download, Downloaded
from assistant.browser_requests import BrowserRequest, Evaluate
from assistant.browser_values import BrowserError
from automation.work_documents import LocalDocument
lazy from assistant.browser import BrowserResult

KANBAN_ORIGIN = "https://dev-team-kanban.fcg.palantirfoundry.com"
OUTLOOK_ORIGINS = ("https://outlook.office.com", "https://outlook.office365.com", "https://outlook.cloud.microsoft")
TEAMS_ORIGINS = ("https://teams.cloud.microsoft", "https://teams.microsoft.com")
type Identity = Annotated[str, Field(min_length=1, max_length=500)]
type Text = Annotated[str, Field(max_length=10000)]

_ORIGINS = TypeAdapter(tuple[str, ...])


class App(Enum):
    """The application whose pages an operation's script expects."""

    KANBAN = auto()
    TEAMS = auto()
    OUTLOOK = auto()


class Browser(Protocol):
    def request(self, request: BrowserRequest, cancel: threading.Event) -> BrowserResult: ...
    def awake(self, target: str, cancel: threading.Event) -> contextlib.AbstractContextManager[None]: ...
    def download_document(self, request: Download, cancel: threading.Event) -> Downloaded: ...


class Located(Protocol):
    """A query names the exact browser page it reads or changes."""

    @property
    def target_id(self) -> str: ...


@dataclass(frozen=True, slots=True)
class Origins:
    kanban: str = KANBAN_ORIGIN
    teams: tuple[str, ...] = TEAMS_ORIGINS
    outlook: tuple[str, ...] = OUTLOOK_ORIGINS

    def of(self, app: App) -> tuple[str, ...]:
        match app:
            case App.KANBAN:
                return (self.kanban,)
            case App.TEAMS:
                return self.teams
            case App.OUTLOOK:
                return self.outlook
            case _:
                assert_never(app)


@dataclass(frozen=True, slots=True)
class BoardQuery:
    target_id: Identity
    query: Annotated[str, Field(max_length=500)] = ""
    offset: Annotated[int, Field(strict=True, ge=0, le=20000)] = 0
    limit: Annotated[int, Field(strict=True, ge=1, le=30)] = 20


@dataclass(frozen=True, slots=True)
class TaskQuery:
    target_id: Identity
    task_id: Identity


@dataclass(frozen=True, slots=True)
class TaskEdit:
    target_id: Identity
    task_id: Identity
    field: Literal["title", "description", "dueDate", "estimate", "labels", "acceptanceCriteria"]
    expected_value: Text
    value: Text


@dataclass(frozen=True, slots=True)
class TaskMove:
    target_id: Identity
    task_id: Identity
    expected_column: Annotated[str, Field(min_length=1, max_length=100)]
    column: Annotated[str, Field(min_length=1, max_length=100)]


@dataclass(frozen=True, slots=True)
class TaskComment:
    target_id: Identity
    task_id: Identity
    text: Annotated[str, Field(min_length=1, max_length=4000)]


@dataclass(frozen=True, slots=True)
class TeamsQuery:
    target_id: Identity


@dataclass(frozen=True, slots=True)
class ChatQuery:
    target_id: Identity
    chat_id: Identity


@dataclass(frozen=True, slots=True)
class ChatDraft:
    target_id: Identity
    chat_id: Identity
    text: Annotated[str, Field(min_length=1, max_length=10000)]


@dataclass(frozen=True, slots=True)
class MailList:
    target_id: Identity
    offset: Annotated[int, Field(strict=True, ge=0, le=20000)] = 0
    limit: Annotated[int, Field(strict=True, ge=1, le=30)] = 20


@dataclass(frozen=True, slots=True)
class MailSearch:
    target_id: Identity
    query: Annotated[str, Field(min_length=1, max_length=500)]


@dataclass(frozen=True, slots=True)
class MailQuery:
    target_id: Identity
    conversation_id: Identity


@dataclass(frozen=True, slots=True)
class MailDraft:
    target_id: Identity
    conversation_id: Identity
    text: Annotated[str, Field(min_length=1, max_length=10000)]


@dataclass(frozen=True, slots=True)
class MailDocument:
    target_id: Identity
    conversation_id: Identity
    attachment_id: Identity


@dataclass(frozen=True, slots=True)
class MailDownload:
    target_id: Identity
    conversation_id: Identity
    attachment_id: Identity
    expected_url: Annotated[str, Field(min_length=1, max_length=4000)]
    destination: LocalDocument


# Results are the scripts' external contracts. Literal fields are the page's
# own confirmation; a script that cannot confirm its effect throws instead.


@dataclass(frozen=True, slots=True)
class Card:
    task_id: str
    title: str
    column: str
    text: str


@dataclass(frozen=True, slots=True)
class Board:
    tasks: tuple[Card, ...]
    total: int
    columns: tuple[str, ...]
    filters: tuple[str, ...]
    search: str
    scope: str
    next_offset: int | None


@dataclass(frozen=True, slots=True)
class TaskDetail:
    task_id: str
    fields: frozendict[str, str]
    text: str


@dataclass(frozen=True, slots=True)
class TaskEdited:
    task_id: str
    field: str
    value: str
    _: KW_ONLY
    verified: Literal[True]


@dataclass(frozen=True, slots=True)
class TaskMoved:
    task_id: str
    column: str
    verified: Literal[True] = field(kw_only=True)
    changed: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class CommentPosted:
    task_id: str
    text: str
    posted: Literal[True] = field(kw_only=True)


# Teams' exact conversation identity, which routes every chat operation.
type ChatIdentity = Annotated[str, Field(max_length=512, pattern=r"^19:\S*@\S*$")]


@dataclass(frozen=True, slots=True)
class TeamsChat:
    identity: ChatIdentity
    title: Annotated[str, Field(max_length=300, pattern=r"\S")]
    kind: Literal["chat", "meeting"]


@dataclass(frozen=True, slots=True)
class TeamsPost:
    identity: Annotated[str, Field(max_length=512, pattern=r"\S")]
    sender: Annotated[str, Field(max_length=300, pattern=r"\S")]
    text: Annotated[str, Field(max_length=16_000, pattern=r"\S")]
    created_at: Annotated[float, Field(strict=True, ge=0, lt=100_000_000_000)]
    reactions: Annotated[tuple[Annotated[str, Field(max_length=1000)], ...], Field(max_length=20)]
    own: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class TeamsPage:
    """The rendered chat list and, once its editor is ready, the selected chat's messages."""

    current: Annotated[str, Field(max_length=512, pattern=r"^(19:\S*@\S*)?$")]
    title: Annotated[str, Field(max_length=300)]
    conversations: Annotated[tuple[TeamsChat, ...], Field(max_length=150)]
    messages: Annotated[tuple[TeamsPost, ...], Field(max_length=80)]
    editor_ready: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class ActivityItem:
    identity: Annotated[str, Field(max_length=32, pattern=r"^[0-9]+$")]
    title: Annotated[str, Field(max_length=512, pattern=r"\S")]
    text: Annotated[str, Field(max_length=4000, pattern=r"\S")]
    kind: Literal["reaction", "invitation", "mention", "update"]
    created_at: Annotated[float, Field(strict=True, ge=0, lt=100_000_000_000)]
    """Zero when Teams shows only a relative or partial date."""
    date_hint: Annotated[str, Field(max_length=256)] = ""


@dataclass(frozen=True, slots=True)
class ActivityPage:
    """The rendered Activity feed; `ready` once its list container exists."""

    items: Annotated[tuple[ActivityItem, ...], Field(max_length=80)]
    ready: bool = field(kw_only=True)


ACTIVITY_PAGE = TypeAdapter(ActivityPage)


@dataclass(frozen=True, slots=True)
class ChatOpened:
    chat_id: str
    opened: Literal[True] = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class ChatDrafted:
    chat_id: str
    text: str
    drafted: Literal[True] = field(kw_only=True)
    sent: Literal[False] = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class MailRow:
    conversation_id: str
    preview: str
    label: str
    selected: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class MailMessage:
    """One individually identified message rendered in the selected conversation."""

    identity: str
    sender: str
    text: str


@dataclass(frozen=True, slots=True)
class SelectedMail:
    conversation_id: str
    subject: str
    messages: tuple[MailMessage, ...]
    text: str
    headers: str
    truncated: bool = field(kw_only=True)
    loading: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class Mailbox:
    """Rendered conversation rows and the selected reading pane."""

    conversations: tuple[MailRow, ...]
    rendered_total: int
    selected: SelectedMail | None
    search: str
    scope: str
    next_offset: int | None
    editor_open: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class MailOpened:
    conversation_id: str
    mail: SelectedMail | None
    opened: Literal[True] = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class MailDrafted:
    conversation_id: str
    text: str
    subject: str
    recipients: tuple[str, ...]
    status: str
    drafted: Literal[True] = field(kw_only=True)
    sent: Literal[False] = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class Attachment:
    attachment_id: str | None
    label: str
    message_id: str | None
    url: str | None
    ambiguous: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class DocumentLink:
    title: str
    url: str


@dataclass(frozen=True, slots=True)
class MailDocuments:
    conversation_id: str
    attachments: tuple[Attachment, ...]
    links: tuple[DocumentLink, ...]
    coverage: str
    truncated: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class PreviewOpened:
    conversation_id: str
    attachment_id: str
    url: str | None
    preview: str
    status: str
    opened: Literal[True] = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class LinkFound:
    """A direct document link, which is opened or collected instead of clicked."""

    conversation_id: str
    attachment_id: str
    url: str | None
    status: str
    opened: Literal[False] = field(kw_only=True)


type DocumentOpened = PreviewOpened | LinkFound


@dataclass(frozen=True, slots=True)
class AttachmentLink:
    conversation_id: str
    attachment_id: str
    url: str


@dataclass(frozen=True, slots=True)
class CollectedDocument:
    conversation_id: str
    attachment_id: str
    path: str
    sha256: str
    size: int
    content_type: str


# Read only. Neither a conversation title nor a notification supplies a routing key.
OBSERVE = r"""(() => {
 const clean = value => (value || '').replace(/\u00a0/g, ' ').trim();
 const source = document.querySelector('[data-tid="sendMessageCommands-send"]');
 const current = source?.getAttribute('data-track-thread-id') || '';
 const selected = document.querySelector('[role="treeitem"][data-tabster*="LeftRailSelectedItem"]');
 const selectedKey = (selected?.getAttribute('data-fui-tree-item-value')||'').match(/19:[^\s/]+@(?:thread\.v2|unq\.gbl\.spaces)/)?.[0];
 const ready = !!document.querySelector('[data-tid="ckeditor"][contenteditable="true"]') && (!selectedKey || selectedKey===current);
 const seen = new Set();
 const conversations = [];
 for (const row of document.querySelectorAll('[role="treeitem"]')) {
   const value = row.getAttribute('data-fui-tree-item-value') || '';
   const match = value.match(/19:[^\s/]+@(?:thread\.v2|unq\.gbl\.spaces)/);
   if (!match || !['chat','muted-chat'].includes(row.getAttribute('data-item-type')) || seen.has(match[0])) continue;
   const title = clean(row.innerText).split('\n').filter(Boolean)[0] || 'Teams conversation';
   conversations.push({identity:match[0], title:title.slice(0,300), kind:match[0].includes('meeting_')?'meeting':'chat'});
   seen.add(match[0]);
 }
 const title = clean(document.querySelector('[data-tid="chat-title"]')?.innerText).slice(0,300);
 if (current && !seen.has(current)) conversations.push({
   identity:current,title:title||'Teams conversation',kind:current.includes('meeting_')?'meeting':'chat'
 });
 const messages = [];
 for (const row of document.querySelectorAll('[data-mid]')) {
   const identity = row.getAttribute('data-mid');
   const body = document.getElementById('content-'+identity);
   if (!identity || !body || !row.contains(body)) continue;
   const direct = clean(row.querySelector('[data-tid="message-author-name"]')?.innerText);
   const labels = (row.getAttribute('aria-labelledby')||'').split(/\s+/).map(id=>document.getElementById(id));
   const linked = labels.find(e=>e?.getAttribute('data-tid')==='message-author-name');
   const author = direct || clean(linked?.innerText) || 'Teams participant';
   const text = clean(body.innerText);
   if (!text) continue;
   const reactions = [...row.querySelectorAll('[data-tid*="reaction"]')]
     .map(e=>clean(e.getAttribute('aria-label')||e.innerText)).filter(Boolean);
   messages.push({identity,sender:author,text:text.slice(0,16000),
     created_at:/^\d{13}$/.test(identity)?Number(identity)/1000:0,reactions:[...new Set(reactions)].slice(0,20),
     own:row.getAttribute('data-tid')==='my-message' || !!row.querySelector('[data-tid="my-message"]')});
 }
 const result = {current,title,conversations:conversations.slice(0,150),messages:ready?messages.slice(-80):[],editor_ready:ready};
 while (JSON.stringify(result).length > 18500 && result.messages.length > 1) result.messages.shift();
 while (JSON.stringify(result).length > 18500 && result.conversations.length > 1) result.conversations.pop();
 if (JSON.stringify(result).length > 18500 && result.messages.length) {
   result.messages[0].text = result.messages[0].text.slice(0,4000)+'\n[Message continues in Teams]';
 }
 return result;
})()"""


# Read only. Each activity row is identified by its numeric list-item id.
ACTIVITY_OBSERVE = r"""(() => {
 const clean = value => (value || '').replace(/\u00a0/g,' ').trim();
 const items = [];
 for (const row of document.querySelectorAll('[data-tid="activity-feed-list-item"]')) {
   const wrap = row.closest('[data-tid="activity-feed-list-item-wrap"]');
   const identity = wrap?.id;
   if (!identity || !/^\d{1,32}$/.test(identity)) continue;
   const title = clean(row.querySelector('[data-tid="activity-feed-item-title"]')?.innerText);
   if (!title) continue;
   const reactionIcon = row.querySelector('[data-tid^="activity-feed-item-activity-icon-"]');
   const reaction = !!reactionIcon;
   const reactionLabel = clean(reactionIcon?.getAttribute('aria-label') || reactionIcon?.getAttribute('title') ||
     reactionIcon?.querySelector('img')?.getAttribute('alt') || '');
   const preview = clean(row.querySelector('[id^="activity-feed-item-message-preview-"]')?.innerText);
   const place = clean(row.querySelector('[id^="activity-feed-item-location-"]')?.innerText);
   const text = [reaction?reactionLabel:'',preview,place].filter(Boolean).join('\n').slice(0,4000) || title;
   const kind = /\b(invited|invitation|meeting invite)\b/i.test(title+' '+text)?'invitation':
     /\bmentioned\b/i.test(title)?'mention':reaction?'reaction':'update';
   const clock = row.querySelector('[id^="activity-feed-item-timestamp-"]');
   const raw = clock?.getAttribute('datetime') || clock?.querySelector('time[datetime]')?.getAttribute('datetime') ||
     clock?.getAttribute('title') || '';
   const parsed = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:/.test(raw) ? Date.parse(raw) : NaN;
   const date_hint = [...new Set([clean(raw),clean(clock?.innerText)].filter(Boolean))].join(' · ').slice(0,256);
   items.push({identity,title:title.slice(0,512),text,kind,created_at:Number.isFinite(parsed)?parsed/1000:0,date_hint});
 }
 const result = {ready:!!document.querySelector('[data-tid="activity-list-container"]'),items:items.slice(0,80)};
 while(JSON.stringify(result).length>18500 && result.items.length>1)result.items.pop();
 return result;
})()"""


# UI predicates and event dispatch run in the browser's isolated world. They
# never invoke React internals or replace the application's handlers.
_DOM = r"""
const clean = value => String(value ?? '').replace(/\u00a0/g,' ').replace(/\r\n/g,'\n').trim();
const wait = async predicate => {
 const end=Date.now()+10000;
 while(Date.now()<end) {if(predicate())return; await new Promise(r=>setTimeout(r,100));}
 throw new Error('The app did not confirm this operation. Inspect it before retrying.');
};
const fill = (e,value) => {
 if(!e || e.disabled || e.readOnly)throw new Error('The selected task field is unavailable or read-only.');
 const proto=e.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
 Object.getOwnPropertyDescriptor(proto,'value').set.call(e,value);
 e.dispatchEvent(new Event('input',{bubbles:true}));
 e.dispatchEvent(new Event('change',{bubbles:true}));
};
"""

_KANBAN = r"""
const card = id => {
 const found = [...document.querySelectorAll('[data-task-id]')].filter(e=>e.getAttribute('data-task-id')===id);
 if(found.length!==1) throw new Error('Task is absent or ambiguous in the current board filters. Refresh the board.');
 return found[0];
};
const columnOf = e => clean(e.closest('[data-tour="board-column"]')?.querySelector('.kanban-column-header > span')?.textContent);
const fieldIds={title:'detail-title',dueDate:'detail-duedate',estimate:'detail-estimate',
 labels:'detail-labels',acceptanceCriteria:'detail-acceptance'};
const fieldOf = (root,name) => name==='description'
 ? root.querySelector('textarea[placeholder="Add description"]') : root.querySelector('#'+fieldIds[name]);
const open = async id => {
 if(document.querySelector('[role="dialog"]')) throw new Error('Close the existing task dialog first; its unsaved work is preserved.');
 const e=card(id), title=clean(e.querySelector('p')?.textContent);
 e.click();
 await wait(()=>!!document.querySelector('[role="dialog"] #detail-title'));
 const root=document.querySelector('[role="dialog"]');
 if(root.getAttribute('aria-label')!==title)throw new Error('The app opened a different task. Nothing was changed.');
 const close=root.querySelector('[aria-label="Close task details"]');
 if(!close)throw new Error('The task close control is unavailable.');
 return {root,close,title};
};
const fields = root => Object.fromEntries(Object.entries(fieldIds).map(([name,id])=>[name,root.querySelector('#'+id)?.value??'']));
"""

_BOARD = r"""
const rows=[...document.querySelectorAll('[data-task-id]')].map(e=>({
 task_id:e.getAttribute('data-task-id'),title:clean(e.querySelector('p')?.textContent),column:columnOf(e),text:clean(e.innerText).slice(0,1500)
})).filter(row=>!options.query || (row.title+' '+row.text).toLowerCase().includes(options.query.toLowerCase()));
const selected=rows.slice(options.offset,options.offset+options.limit);
const result={tasks:selected,total:rows.length,
 columns:[...document.querySelectorAll('.kanban-column-header > span:first-child')].map(e=>clean(e.textContent)),
 filters:[...document.querySelectorAll('button[aria-label*=" filter:"]')].map(e=>e.getAttribute('aria-label')),
 search:document.querySelector('input[placeholder="Search tasks..."]')?.value??'',
 scope:'Currently rendered board with its existing filters',next_offset:null};
while(JSON.stringify(result).length>18000 && selected.length>1)selected.pop();
if(options.offset+selected.length<rows.length)result.next_offset=options.offset+selected.length;
return result;
"""

_READ = r"""
const {root,close}=await open(options.task_id);
try {
 const result={task_id:options.task_id,fields:fields(root),text:clean(root.innerText).slice(0,12000)};
 const edit=[...root.querySelectorAll('button')].find(e=>clean(e.textContent)==='EDIT');
 if(edit){edit.click(); await wait(()=>!!fieldOf(root,'description'));}
 result.fields.description=fieldOf(root,'description')?.value??'';
 return result;
}finally{close.click();await wait(()=>!root.isConnected);}
"""

_EDIT = r"""
const {root,close,title}=await open(options.task_id);
if(options.field==='description'){
 const edit=[...root.querySelectorAll('button')].find(e=>clean(e.textContent)==='EDIT');
 if(edit)edit.click();
 await wait(()=>!!fieldOf(root,'description'));
}
const e=fieldOf(root,options.field);
if(!e || e.value!==options.expected_value){close.click();throw new Error('The task field changed since it was read. Nothing was edited.');}
fill(e,options.value);
// Let React commit before requesting its validated save-on-close operation.
await new Promise(r=>setTimeout(r,0));
if(!root.isConnected || root.getAttribute('aria-label')!==title)throw new Error('The selected task changed. Inspect before continuing.');
close.click();await wait(()=>!root.isConnected);
const reopened=await open(options.task_id);
try {
 if(options.field==='description'){
  const edit=[...reopened.root.querySelectorAll('button')].find(e=>clean(e.textContent)==='EDIT');
  if(edit)edit.click();await wait(()=>!!fieldOf(reopened.root,'description'));
 }
 if(fieldOf(reopened.root,options.field)?.value!==options.value)throw new Error('The saved field did not match. Inspect before retrying.');
 return {task_id:options.task_id,field:options.field,value:options.value,verified:true};
}finally{reopened.close.click();await wait(()=>!reopened.root.isConnected);}
"""

_MOVE = r"""
if(document.querySelector('[role="dialog"]'))throw new Error('Close the task dialog before moving a card.');
const e=card(options.task_id);
if(columnOf(e)!==options.expected_column)throw new Error('The task moved since it was read. Nothing was changed.');
if(options.column===options.expected_column)return {task_id:options.task_id,column:options.column,verified:true,changed:false};
if(e.getAttribute('draggable')!=='true')throw new Error('This task cannot be dragged.');
const destinations=[...document.querySelectorAll('[data-tour="board-column"]')].filter(c=>
 clean(c.querySelector('.kanban-column-header > span')?.textContent)===options.column);
if(destinations.length!==1)throw new Error('The destination column is absent or ambiguous.');
const destination=destinations[0],dataTransfer=new DataTransfer();
e.dispatchEvent(new DragEvent('dragstart',{bubbles:true,dataTransfer}));
try {
 destination.dispatchEvent(new DragEvent('dragover',{bubbles:true,cancelable:true,dataTransfer}));
 destination.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer}));
 await wait(()=>columnOf(card(options.task_id))===options.column);
 return {task_id:options.task_id,column:options.column,verified:true,changed:true};
}finally{e.dispatchEvent(new DragEvent('dragend',{bubbles:true,dataTransfer}));}
"""

_COMMENT = r"""
if(!options.text.trim())throw new Error('A comment must contain text.');
const {root,close}=await open(options.task_id);
const editor=root.querySelector('textarea[placeholder^="Add a comment"]');
if(!editor || editor.value.trim()){close.click();throw new Error('The comment editor already contains a draft. Nothing was posted.');}
fill(editor,options.text);await new Promise(r=>setTimeout(r,0));
const post=[...root.querySelectorAll('button')].find(e=>clean(e.textContent)==='POST');
if(!post || post.disabled)throw new Error('The app did not enable comment posting. Your draft remains in its editor.');
post.click();await wait(()=>editor.value==='' && clean(root.innerText).includes(options.text.trim()));
close.click();await wait(()=>!root.isConnected);
return {task_id:options.task_id,posted:true,text:options.text};
"""

_CHAT_OPEN = r"""
const rows=[...document.querySelectorAll('[role="treeitem"]')].filter(e=>{
 const key=(e.getAttribute('data-fui-tree-item-value')||'').match(/19:[^\s/]+@(?:thread\.v2|unq\.gbl\.spaces)/)?.[0];
 return key===options.chat_id;
});
if(rows.length!==1)throw new Error('That exact chat is not rendered. Refresh Teams; no conversation title is used for routing.');
if(document.querySelector('[data-tid="ckeditor"]')?.innerText.trim())
 throw new Error('The current Teams editor contains a draft. Nothing was opened.');
rows[0].click();
const end=Date.now()+10000;
while(Date.now()<end){
 if(document.querySelector('[data-tid="sendMessageCommands-send"]')?.getAttribute('data-track-thread-id')===options.chat_id)
  return {chat_id:options.chat_id,opened:true};
 await new Promise(r=>setTimeout(r,100));
}
throw new Error('Teams did not confirm the selected chat. Refresh before continuing.');
"""

_CHAT_DRAFT = r"""
const send=document.querySelector('[data-tid="sendMessageCommands-send"]');
const editor=document.querySelector('[data-tid="ckeditor"][contenteditable="true"]');
if(send?.getAttribute('data-track-thread-id')!==options.chat_id || !editor || editor.innerText.trim())
 throw new Error('The exact Teams chat is not selected or its editor contains a draft. Nothing was changed.');
if(!options.text.trim())throw new Error('A reply must contain text.');
editor.focus();
if(!document.execCommand('insertText',false,options.text))throw new Error('Teams rejected inserting the draft. Inspect its editor.');
if(editor.innerText.replace(/\u00a0/g,' ').trim()!==options.text.trim())throw new Error('Teams did not retain the exact draft. Inspect its editor.');
return {chat_id:options.chat_id,drafted:true,sent:false,text:options.text};
"""


_MAIL = r"""
const list=document.querySelector('[data-app-section="MessageList"]');
if(!list || !document.querySelector('#topSearchInput'))throw new Error('Outlook mail is not ready. Complete sign-in in this tab.');
const mailRows = ()=>[...list.querySelectorAll('[role="option"][data-convid]')];
const mailEditor = ()=>document.querySelector('[contenteditable="true"][aria-label="Message body"]');
const pane = ()=>document.querySelector('[data-app-section="MailReadCompose"]');
const selectedMail = ()=>{
 const selected=mailRows().filter(e=>e.getAttribute('aria-selected')==='true');
 if(selected.length!==1)return null;
 const id=selected[0].getAttribute('data-convid');
 const subject=pane()?.querySelector('[id^="CONV_"][id$="_SUBJECT"]');
 const suffix=subject?.id.slice(5,-8);
 if(!suffix || suffix.length<10 || !id.endsWith(suffix))return null;
 return {conversation_id:id,subject:clean(subject.textContent)};
};
const mailRead = ()=>{
 const rows=mailRows().map(e=>({conversation_id:e.getAttribute('data-convid'),
  preview:clean(e.innerText).slice(0,1500),label:clean(e.getAttribute('aria-label')).slice(0,1500),
  selected:e.getAttribute('aria-selected')==='true'}));
 const offset=options.offset??0,limit=options.limit??20,selected=selectedMail();
 const body=pane()?.querySelector('[aria-label="Message body"]');
 const text=selected&&!mailEditor()?clean(body?.innerText):'';
 const candidates=selected&&!mailEditor()?Array.from(pane().querySelectorAll('[aria-label="Message body"]')).map(e=>{
  const root=e.closest('[data-itemid],[data-messageid],[data-message-id]');
  const identity=root?.getAttribute('data-itemid')||root?.getAttribute('data-messageid')||root?.getAttribute('data-message-id');
  if(!identity)return null;
  const sender=root.querySelector('[data-testid="message-sender"],[aria-label^="From:"]');
  return {identity,sender:clean(sender?.innerText||sender?.getAttribute('aria-label')||''),text:clean(e.innerText).slice(0,6000)};
 }).filter(Boolean):[];
 // Ambiguous ids and unlabelled aggregate bodies never become individual mail.
 const messages=candidates.filter(e=>e.text&&candidates.filter(other=>other.identity===e.identity).length===1).slice(0,20);
 const result={conversations:rows.slice(offset,offset+limit),rendered_total:rows.length,
  selected:selected?{...selected,messages,text:text.slice(0,10000),truncated:text.length>10000,loading:!text&&!mailEditor(),
   headers:clean(pane().innerText).slice(0,1500)}:null,
  editor_open:!!mailEditor(),search:document.querySelector('#topSearchInput').value,
  scope:document.querySelector('button[aria-label^="Search filters,"]')?.getAttribute('aria-label')||'Current folder and tab',
  next_offset:null};
 while(JSON.stringify(result).length>18000 && result.selected?.messages.length)result.selected.messages.pop();
 while(JSON.stringify(result).length>18000 && result.conversations.length)result.conversations.pop();
 if(offset+result.conversations.length<rows.length)result.next_offset=offset+result.conversations.length;
 return result;
};
const exactMail = id=>{
 const found=mailRows().filter(e=>e.getAttribute('data-convid')===id);
 if(found.length!==1)throw new Error('The exact mail conversation is absent or ambiguous. Refresh the rendered list.');
 return found[0];
};
const documentMail = ()=>{
 const selected=selectedMail();
 if(!selected || selected.conversation_id!==options.conversation_id || mailEditor())
  throw new Error('Open the exact mail conversation first; an open draft cannot supply document evidence.');
 return selected;
};
const safeDocumentLink = element=>{
 const value=element?.getAttribute('href');if(!value)return null;
 try{const url=new URL(value,location.href);
  return ['https:','http:'].includes(url.protocol)&&!url.username&&!url.password?url.href:null;
 }catch{return null;}
};
const attachmentNodes = ()=>{
 const root=pane();
 const marked=[...root.querySelectorAll('[data-attachment-id],[data-attachmentid],[data-testid*="attachment"],'
  +'[data-tid*="attachment"],[data-automationid*="ttachment"],[role="button"][aria-label],button[aria-label]')];
 const entries=marked.filter(e=>{
  const label=e.getAttribute('aria-label')||'';
  return e.hasAttribute('data-attachment-id')||e.hasAttribute('data-attachmentid')
   || /attachment|bilaga|bifogad/i.test(label)&&/\.[a-z0-9]{2,8}(?:\b|$)/i.test(label)
   || /attachment/i.test(e.getAttribute('data-testid')||e.getAttribute('data-tid')||e.getAttribute('data-automationid')||'')
      &&/\.[a-z0-9]{2,8}(?:\b|$)/i.test(e.innerText||label);
 });
 // Prefer the outer card, never its menu/download action as a second file.
 const cards=entries.filter(e=>!entries.some(parent=>parent!==e&&parent.contains(e)));
 return cards.map(node=>{
  const label=clean(node.getAttribute('aria-label')||node.innerText);
  const explicit=node.getAttribute('data-attachment-id')||node.getAttribute('data-attachmentid');
  const id=explicit||('label:'+label);
  const message=node.closest('[data-itemid],[data-messageid],[data-message-id]');
  return {node,attachment_id:id.length<=500?id:null,label:label.slice(0,1500),
   message_id:message?.getAttribute('data-itemid')||message?.getAttribute('data-messageid')||message?.getAttribute('data-message-id')||null,
   url:safeDocumentLink(node.matches('a[href]')?node:node.querySelector('a[href]'))};
 });
};
const mailDocuments = ()=>{
 const selected=documentMail(),entries=attachmentNodes();
 const attachments=entries.map(({node,...entry})=>({...entry,
  ambiguous:!entry.attachment_id||entries.filter(e=>e.attachment_id===entry.attachment_id).length!==1}));
 const links=[...pane().querySelectorAll('[aria-label="Message body"] a[href]')].map(e=>({
  title:clean(e.innerText).slice(0,500),url:safeDocumentLink(e)
 })).filter(e=>e.url);
 return {conversation_id:selected.conversation_id,attachments:attachments.slice(0,30),links:links.slice(0,50),
  truncated:attachments.length>30||links.length>50,
  coverage:'Rendered attachment controls and message links only; not a complete mailbox/file inventory.'};
};
const exactAttachment = ()=>{
 documentMail();const matches=attachmentNodes().filter(e=>e.attachment_id===options.attachment_id);
 if(matches.length!==1)throw new Error('The exact attachment is absent or ambiguous. Read outlook_web_documents again.');
 return matches[0];
};
"""

_MAIL_DOCUMENT_OPEN = r"""
const file=exactAttachment();
if(file.node.matches('a[href]'))return {opened:false,conversation_id:options.conversation_id,attachment_id:file.attachment_id,url:file.url,
 status:'Open this observed document link with browser_open, or collect it with outlook_web_download_document.'};
const existing=document.querySelector('[role="dialog"],[data-app-section="AttachmentPreview"]');
if(existing)throw new Error('An existing dialog/preview must be inspected first. Nothing was opened.');
file.node.click();
await wait(()=>document.querySelector('[role="dialog"],[data-app-section="AttachmentPreview"],iframe[title]'));
const preview=document.querySelector('[role="dialog"],[data-app-section="AttachmentPreview"],iframe[title]');
return {opened:true,conversation_id:options.conversation_id,attachment_id:file.attachment_id,url:file.url,
 preview:clean(preview.innerText||preview.getAttribute('title')).slice(0,8000),
 status:'Attachment preview opened. Inspect browser_snapshot for document content and available download/open links.'};
"""

_MAIL_DOCUMENT_DOWNLOAD = r"""
const file=exactAttachment();
if(!file.url || file.url!==options.expected_url)throw new Error('The attachment link is unavailable or changed. Inspect it before collecting.');
return {conversation_id:options.conversation_id,attachment_id:file.attachment_id,url:file.url};
"""

_MAIL_SEARCH = r"""
if(mailEditor())throw new Error('Outlook already has an open draft. Close it before searching; its text is preserved.');
if(!options.query.trim())throw new Error('A search must contain text.');
const input=document.querySelector('#topSearchInput');
const results=()=>!!list.querySelector('[aria-label="Results"]');
if(input.value===options.query && results())return mailRead();
const oldRows=mailRows(),oldText=clean(list.innerText);
input.focus();fill(input,options.query);
await wait(()=>!!document.querySelector('button[aria-label="Search"]'));
document.querySelector('button[aria-label="Search"]').click();
await wait(()=>results() && (clean(list.innerText)!==oldText || oldRows.some(e=>!e.isConnected)) &&
 !list.querySelector('[role="progressbar"],[aria-busy="true"],.ms-Spinner') &&
 (mailRows().length || /no results|didn't find|couldn't find|no matches/i.test(list.innerText)));
if(input.value!==options.query)throw new Error('The search changed while it was running. Read the page before continuing.');
return mailRead();
"""

_MAIL_OPEN = r"""
if(mailEditor())throw new Error('Outlook already has an open draft. Close it before selecting mail; its text is preserved.');
exactMail(options.conversation_id).click();
await wait(()=>selectedMail()?.conversation_id===options.conversation_id &&
 !!clean(pane().querySelector('[aria-label="Message body"]')?.innerText));
return {opened:true,conversation_id:options.conversation_id,mail:mailRead().selected};
"""

_MAIL_DRAFT = r"""
if(mailEditor())throw new Error('Outlook already has an open draft. Nothing was replaced.');
if(!options.text.trim())throw new Error('A reply must contain text.');
const original=selectedMail();
if(original?.conversation_id!==options.conversation_id)throw new Error('Read and select this exact mail conversation before replying.');
const ribbon=document.querySelector('[data-app-section="Ribbon"]');
const controls=[...pane().querySelectorAll('div[role="menuitem"][aria-label="Reply"]')];
const reply=ribbon?.querySelector('button[aria-label="Reply"]') || (controls.length===1?controls[0]:null);
if(!reply || reply.disabled)throw new Error('Outlook has not enabled replying to this conversation.');
reply.click();
await wait(()=>!!mailEditor() && !!document.querySelector('input[aria-label="Subject"]'));
// Outlook initializes its signature asynchronously after mounting the editor.
await new Promise(r=>setTimeout(r,2500));
const editor=mailEditor();
const selected=mailRows().filter(e=>e.getAttribute('aria-selected')==='true');
if(selected.length!==1 || selected[0].getAttribute('data-convid')!==options.conversation_id ||
 document.querySelector('input[aria-label="Subject"]').value.replace(/^re:\s*/i,'')!==original.subject)
 throw new Error('The selected conversation changed. Inspect the open draft.');
// Outlook owns the signature and quoted history. Insert above them; never
// replace the editor's contents or an existing user draft.
const contents=editor.cloneNode(true);
contents.querySelectorAll('#Signature').forEach(e=>e.remove());
if(clean(contents.textContent))throw new Error('Outlook opened a reply with existing text. Inspect it before continuing.');
editor.focus();
const range=document.createRange();range.selectNodeContents(editor);range.collapse(true);
const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);
if(!document.execCommand('insertText',false,options.text+'\n\n'))throw new Error('Outlook rejected inserting the draft. Inspect its editor.');
if(clean(editor.innerText)!==clean(options.text) && !clean(editor.innerText).startsWith(clean(options.text)+'\n'))
 throw new Error('Outlook did not retain the exact reply text. Inspect the draft before retrying.');
return {conversation_id:options.conversation_id,drafted:true,sent:false,text:options.text,
 subject:document.querySelector('input[aria-label="Subject"]')?.value??'',
 recipients:[...document.querySelectorAll('[contenteditable="true"][aria-label="To"] [contenteditable="false"][aria-label]')]
  .map(e=>e.getAttribute('aria-label')).slice(0,30),status:'Prepared in the open Outlook editor; review its autosave status in Outlook'};
"""


def decoded[R](result: TypeAdapter[R], text: str) -> R:
    """Validate a complete bounded result; browser truncation or malformed output remains a failure."""
    try:
        return result.validate_json(text)
    except ValidationError as error:
        raise BrowserError("The application returned an unexpected result. Inspect it before claiming it succeeded.") from error


class WebAppOperation[Q: Located, R](Protocol):
    """What callers need of an operation: its query and result contracts, and how it is performed."""

    @property
    def query(self) -> TypeAdapter[Q]: ...
    @property
    def result(self) -> TypeAdapter[R]: ...
    def perform(self, apps: WebApps, query: Q, cancel: threading.Event) -> R: ...


@dataclass(frozen=True, slots=True)
class PageOperation[Q: Located, R]:
    """A script run in one application's page, which returns its confirmed result."""

    app: App
    script: str
    query: TypeAdapter[Q]
    result: TypeAdapter[R]

    def perform(self, apps: WebApps, query: Q, cancel: threading.Event) -> R:
        return decoded(self.result, apps.evaluate(self, query, cancel))


_COLLECTED = TypeAdapter(CollectedDocument)


@dataclass(frozen=True, slots=True)
class DocumentCollection:
    """Confirm an exact attachment's rendered link, then collect it using the browser's cookies."""

    link: PageOperation[MailDownload, AttachmentLink]

    @property
    def query(self) -> TypeAdapter[MailDownload]:
        return self.link.query

    @property
    def result(self) -> TypeAdapter[CollectedDocument]:
        return _COLLECTED

    def perform(self, apps: WebApps, query: MailDownload, cancel: threading.Event) -> CollectedDocument:
        link = self.link.perform(apps, query, cancel)
        if (link.url, link.attachment_id, link.conversation_id) != (query.expected_url, query.attachment_id, query.conversation_id):
            raise BrowserError("The browser did not confirm the exact attachment link.")
        saved = apps.browser.download_document(Download(query.target_id, link.url, query.destination), cancel)
        return CollectedDocument(query.conversation_id, query.attachment_id, saved.path, saved.sha256, saved.size, saved.content_type)


KANBAN_BOARD: Final = PageOperation(App.KANBAN, _BOARD, TypeAdapter(BoardQuery), TypeAdapter(Board))
KANBAN_READ_TASK: Final = PageOperation(App.KANBAN, _READ, TypeAdapter(TaskQuery), TypeAdapter(TaskDetail))
KANBAN_UPDATE_TASK: Final = PageOperation(App.KANBAN, _EDIT, TypeAdapter(TaskEdit), TypeAdapter(TaskEdited))
KANBAN_MOVE_TASK: Final = PageOperation(App.KANBAN, _MOVE, TypeAdapter(TaskMove), TypeAdapter(TaskMoved))
KANBAN_COMMENT: Final = PageOperation(App.KANBAN, _COMMENT, TypeAdapter(TaskComment), TypeAdapter(CommentPosted))
TEAMS_READ: Final = PageOperation(App.TEAMS, "return " + OBSERVE + ";", TypeAdapter(TeamsQuery), TypeAdapter(TeamsPage))
TEAMS_OPEN_CHAT: Final = PageOperation(App.TEAMS, _CHAT_OPEN, TypeAdapter(ChatQuery), TypeAdapter(ChatOpened))
TEAMS_DRAFT_REPLY: Final = PageOperation(App.TEAMS, _CHAT_DRAFT, TypeAdapter(ChatDraft), TypeAdapter(ChatDrafted))
OUTLOOK_READ: Final = PageOperation(App.OUTLOOK, "return mailRead();", TypeAdapter(MailList), TypeAdapter(Mailbox))
OUTLOOK_SEARCH: Final = PageOperation(App.OUTLOOK, _MAIL_SEARCH, TypeAdapter(MailSearch), TypeAdapter(Mailbox))
OUTLOOK_OPEN_MAIL: Final = PageOperation(App.OUTLOOK, _MAIL_OPEN, TypeAdapter(MailQuery), TypeAdapter(MailOpened))
OUTLOOK_DRAFT_REPLY: Final = PageOperation(App.OUTLOOK, _MAIL_DRAFT, TypeAdapter(MailDraft), TypeAdapter(MailDrafted))
OUTLOOK_DOCUMENTS: Final = PageOperation(App.OUTLOOK, "return mailDocuments();", TypeAdapter(MailQuery), TypeAdapter(MailDocuments))
OUTLOOK_OPEN_DOCUMENT: Final = PageOperation(App.OUTLOOK, _MAIL_DOCUMENT_OPEN, TypeAdapter(MailDocument), TypeAdapter[DocumentOpened](DocumentOpened))
OUTLOOK_DOWNLOAD_DOCUMENT: Final = DocumentCollection(
    PageOperation(App.OUTLOOK, _MAIL_DOCUMENT_DOWNLOAD, TypeAdapter(MailDownload), TypeAdapter(AttachmentLink))
)


class WebApps:
    __slots__ = ("browser", "origins")

    def __init__(self, browser: Browser, origins: Origins | None = None) -> None:
        self.browser = browser
        self.origins = Origins() if origins is None else origins

    def run[Q: Located, R](self, operation: WebAppOperation[Q, R], query: Q, cancel: threading.Event) -> R:
        if cancel.is_set():
            raise BrowserError("Stopped before interacting with the application.")
        return operation.perform(self, query, cancel)

    def evaluate[Q: Located, R](self, operation: PageOperation[Q, R], query: Q, cancel: threading.Event) -> str:
        match operation.app:
            case App.KANBAN:
                helpers = _KANBAN
            case App.OUTLOOK:
                helpers = _MAIL
            case App.TEAMS:
                helpers = ""
            case _:
                assert_never(operation.app)
        allowed = _ORIGINS.dump_json(self.origins.of(operation.app)).decode()
        options = operation.query.dump_json(query).decode()
        guard = f"if(!{allowed}.includes(location.origin))throw new Error('The selected tab belongs to a different application.');"
        expression = "(async()=>{" + guard + "const options=" + options + ";" + _DOM + helpers + operation.script + "})()"
        with self.browser.awake(query.target_id, cancel):
            return self.browser.request(Evaluate(query.target_id, expression), cancel).text
