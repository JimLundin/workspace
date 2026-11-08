
const send=document.querySelector('[data-tid="sendMessageCommands-send"]');
const editor=document.querySelector('[data-tid="ckeditor"][contenteditable="true"]');
if(send?.getAttribute('data-track-thread-id')!==options.chat_id || !editor || editor.innerText.trim())
 throw new Error('The exact Teams chat is not selected or its editor contains a draft. Nothing was changed.');
if(!options.text.trim())throw new Error('A reply must contain text.');
editor.focus();
if(!document.execCommand('insertText',false,options.text))throw new Error('Teams rejected inserting the draft. Inspect its editor.');
if(editor.innerText.replace(/\u00a0/g,' ').trim()!==options.text.trim())throw new Error('Teams did not retain the exact draft. Inspect its editor.');
return {chat_id:options.chat_id,drafted:true,sent:false,text:options.text};
