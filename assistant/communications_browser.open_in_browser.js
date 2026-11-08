(() => {
    if(location.pathname!=='/dl/launcher/launcher.html')return false;
    const web=document.querySelector('#openTeamsClientInBrowser');
    if(!web || web.disabled)return false;
    web.click();return true;
})()
