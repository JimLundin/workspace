
const {root,close}=await open(options.task_id);
try {
 const result={task_id:options.task_id,fields:fields(root),text:clean(root.innerText).slice(0,12000)};
 const edit=[...root.querySelectorAll('button')].find(e=>clean(e.textContent)==='EDIT');
 if(edit){edit.click(); await wait(()=>!!fieldOf(root,'description'));}
 result.fields.description=fieldOf(root,'description')?.value??'';
 return result;
}finally{close.click();await wait(()=>!root.isConnected);}
