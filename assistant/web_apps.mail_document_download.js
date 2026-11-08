
const file=exactAttachment();
if(!file.url || file.url!==options.expected_url)throw new Error('The attachment link is unavailable or changed. Inspect it before collecting.');
return {conversation_id:options.conversation_id,attachment_id:file.attachment_id,url:file.url};
