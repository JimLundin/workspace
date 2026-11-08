
const file=exactAttachment();
if(file.node.matches('a[href]'))return {opened:false,conversation_id:options.conversation_id,attachment_id:file.attachment_id,url:file.url,
 status:'Open this observed document link with browser_open, or collect it with outlook_web_download_document.'};
const existing=document.querySelector('[role="dialog"],[data-app-section="AttachmentPreview"]');
if(existing)throw new Error('An existing dialog/preview must be inspected first. Nothing was opened.');
file.node.click();
await wait(()=>document.querySelector('[role="dialog"],[data-app-section="AttachmentPreview"],iframe[title]'));
const preview=document.querySelector('[role="dialog"],[data-app-section="AttachmentPreview"],iframe[title]');
return {opened:true,conversation_id:options.conversation_id,attachment_id:file.attachment_id,url:file.url,
 preview:clean(preview.innerText||preview.getAttribute('title')).slice(0,8000),
 status:'Attachment preview opened. Inspect browser_snapshot for document content and available download/open links.'};
