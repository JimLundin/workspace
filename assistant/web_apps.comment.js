
if(!options.text.trim())throw new Error('A comment must contain text.');
const {root,close}=await open(options.task_id);
const editor=root.querySelector('textarea[placeholder^="Add a comment"]');
if(!editor || editor.value.trim()){close.click();throw new Error('The comment editor already contains a draft. Nothing was posted.');}
fill(editor,options.text);await new Promise(r=>setTimeout(r,0));
const post=[...root.querySelectorAll('button')].find(e=>clean(e.textContent)==='POST');
if(!post || post.disabled)throw new Error('The app did not enable comment posting. Your draft remains in its editor.');
post.click();await wait(()=>editor.value==='' && clean(root.innerText).includes(options.text.trim()));
close.click();await wait(()=>!root.isConnected);
return {task_id:options.task_id,posted:true,text:options.text};
