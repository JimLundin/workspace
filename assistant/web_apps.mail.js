
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
