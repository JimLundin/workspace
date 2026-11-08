(identity, text) => {
    const send=document.querySelector('[data-tid="sendMessageCommands-send"]');
    const editor=document.querySelector('[data-tid="ckeditor"][contenteditable="true"]');
    if(send?.getAttribute('data-track-thread-id')!==identity || !editor || editor.innerText.trim()) return false;
    editor.focus();
    return document.execCommand('insertText', false, text);
}
