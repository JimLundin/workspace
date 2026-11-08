(() => {
    const item=document.querySelector('[data-tid="toggleActivityRead"]');
    if(item?.innerText!=='Mark as read')return false;item.click();return true;
})()
