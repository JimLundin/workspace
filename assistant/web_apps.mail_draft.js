
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
