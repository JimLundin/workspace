
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
