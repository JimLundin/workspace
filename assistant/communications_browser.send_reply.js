(identity, text) => {
    const send=document.querySelector('[data-tid="sendMessageCommands-send"]');
    const editor=document.querySelector('[data-tid="ckeditor"][contenteditable="true"]');
    if(send?.getAttribute('data-track-thread-id')!==identity || !editor ||
       editor.innerText.replace(/\u00a0/g,' ').trim()!==text.trim() || send.disabled ||
       send.getAttribute('aria-disabled')==='true') return false;
    send.click(); return true;
}
