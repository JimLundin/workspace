
if(mailEditor())throw new Error('Outlook already has an open draft. Close it before selecting mail; its text is preserved.');
exactMail(options.conversation_id).click();
await wait(()=>selectedMail()?.conversation_id===options.conversation_id &&
 !!clean(pane().querySelector('[aria-label="Message body"]')?.innerText));
return {opened:true,conversation_id:options.conversation_id,mail:mailRead().selected};
