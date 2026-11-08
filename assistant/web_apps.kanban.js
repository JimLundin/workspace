
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
