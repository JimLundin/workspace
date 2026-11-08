
if(mailEditor())throw new Error('Outlook already has an open draft. Close it before searching; its text is preserved.');
if(!options.query.trim())throw new Error('A search must contain text.');
const input=document.querySelector('#topSearchInput');
const results=()=>!!list.querySelector('[aria-label="Results"]');
if(input.value===options.query && results())return mailRead();
const oldRows=mailRows(),oldText=clean(list.innerText);
input.focus();fill(input,options.query);
await wait(()=>!!document.querySelector('button[aria-label="Search"]'));
document.querySelector('button[aria-label="Search"]').click();
await wait(()=>results() && (clean(list.innerText)!==oldText || oldRows.some(e=>!e.isConnected)) &&
 !list.querySelector('[role="progressbar"],[aria-busy="true"],.ms-Spinner') &&
 (mailRows().length || /no results|didn't find|couldn't find|no matches/i.test(list.innerText)));
if(input.value!==options.query)throw new Error('The search changed while it was running. Read the page before continuing.');
return mailRead();
