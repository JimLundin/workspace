
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
