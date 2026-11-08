(() => {
    if(document.querySelector('[role="treeitem"][data-fui-tree-item-value]'))return false;
    const chat=document.querySelector('[data-tid="app-layout-area--nav"] button[aria-label="Chat"]');
    if(!chat)return false;
    chat.click();return true;
})()
