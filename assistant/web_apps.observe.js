(() => {
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
   conversations.push({identity:match[0], title:title.slice(0,300)});
   seen.add(match[0]);
 }
 const title = clean(document.querySelector('[data-tid="chat-title"]')?.innerText).slice(0,300);
 if (current && !seen.has(current)) conversations.push({
   identity:current,title:title||'Teams conversation'
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
})()