identity => {
    const wrap=document.getElementById(identity);
    if(wrap?.getAttribute('data-tid')!=='activity-feed-list-item-wrap')return false;
    const row=wrap.querySelector('[data-tid="activity-feed-list-item"]');
    if(!row)return false;row.dispatchEvent(new MouseEvent('mouseover',{bubbles:true}));
    const button=row.querySelector('button[id^="activity-feed-item-context-menu-"]');
    if(!button)return false;button.click();return true;
}
