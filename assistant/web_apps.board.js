
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
