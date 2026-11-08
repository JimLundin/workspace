(() => {
 const clean = value => (value || '').replace(/\u00a0/g,' ').trim();
 const items = [];
 for (const row of document.querySelectorAll('[data-tid="activity-feed-list-item"]')) {
   const wrap = row.closest('[data-tid="activity-feed-list-item-wrap"]');
   const identity = wrap?.id;
   if (!identity || !/^\d{1,32}$/.test(identity)) continue;
   const title = clean(row.querySelector('[data-tid="activity-feed-item-title"]')?.innerText);
   if (!title) continue;
   const reactionIcon = row.querySelector('[data-tid^="activity-feed-item-activity-icon-"]');
   const reaction = !!reactionIcon;
   const reactionLabel = clean(reactionIcon?.getAttribute('aria-label') || reactionIcon?.getAttribute('title') ||
     reactionIcon?.querySelector('img')?.getAttribute('alt') || '');
   const preview = clean(row.querySelector('[id^="activity-feed-item-message-preview-"]')?.innerText);
   const place = clean(row.querySelector('[id^="activity-feed-item-location-"]')?.innerText);
   const text = [reaction?reactionLabel:'',preview,place].filter(Boolean).join('\n').slice(0,4000) || title;
   const activity = /\b(invited|invitation|meeting invite)\b/i.test(title+' '+text)?'invitation':
     /\bmentioned\b/i.test(title)?'mention':reaction?'reaction':'update';
   const clock = row.querySelector('[id^="activity-feed-item-timestamp-"]');
   const raw = clock?.getAttribute('datetime') || clock?.querySelector('time[datetime]')?.getAttribute('datetime') ||
     clock?.getAttribute('title') || '';
   const parsed = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:/.test(raw) ? Date.parse(raw) : NaN;
   const date_hint = [...new Set([clean(raw),clean(clock?.innerText)].filter(Boolean))].join(' · ').slice(0,256);
   items.push({identity,title:title.slice(0,512),text,activity,created_at:Number.isFinite(parsed)?parsed/1000:0,date_hint});
 }
 const result = {ready:!!document.querySelector('[data-tid="activity-list-container"]'),items:items.slice(0,80)};
 while(JSON.stringify(result).length>18500 && result.items.length>1)result.items.pop();
 return result;
})()