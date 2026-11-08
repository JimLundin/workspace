
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
