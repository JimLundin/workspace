identity => {
    const wrap=document.getElementById(identity);
    if(wrap?.getAttribute('data-tid')!=='activity-feed-list-item-wrap')return false;
    const row=wrap.querySelector('[data-tid="activity-feed-list-item"]');
    if(!row)return false;row.click();return true;
}
