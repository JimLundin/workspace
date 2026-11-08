
if(!allowed.includes(location.origin))throw new Error('The selected tab belongs to a different application.');
const clean = value => String(value ?? '').replace(/\u00a0/g,' ').replace(/\r\n/g,'\n').trim();
const wait = async predicate => {
 const end=Date.now()+10000;
 while(Date.now()<end) {if(predicate())return; await new Promise(r=>setTimeout(r,100));}
 throw new Error('The app did not confirm this operation. Inspect it before retrying.');
};
const fill = (e,value) => {
 if(!e || e.disabled || e.readOnly)throw new Error('The selected task field is unavailable or read-only.');
 const proto=e.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
 Object.getOwnPropertyDescriptor(proto,'value').set.call(e,value);
 e.dispatchEvent(new Event('input',{bubbles:true}));
 e.dispatchEvent(new Event('change',{bubbles:true}));
};
