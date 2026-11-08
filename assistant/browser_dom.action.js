(options => {
    const e = globalThis.__workspaceControls?.get(options.id);
    if (!e || !e.isConnected) throw new Error('Control is stale. Take a fresh browser snapshot.');
    if (e.disabled || e.getAttribute('aria-disabled') === 'true') throw new Error('The control is disabled.');
    const send = type => e.dispatchEvent(new Event(type, {bubbles: true, composed: true}));
    if (options.action === 'click') {
        e.scrollIntoView({block: 'center', inline: 'center', behavior: 'instant'});
        const r = e.getBoundingClientRect();
        const x = r.left + r.width / 2, y = r.top + r.height / 2;
        const root = e.getRootNode();
        const hit = root.elementFromPoint ? root.elementFromPoint(x, y) : document.elementFromPoint(x, y);
        if (!hit || !(e === hit || e.contains(hit))) throw new Error('Another element covers this control. Inspect the page again.');
        if (options.dom_click) { e.click(); return {clicked: true}; }
        return {x, y};
    }
    if (options.action === 'fill') {
        if (e.readOnly) throw new Error('The field is read-only.');
        if (e.isContentEditable) e.textContent = options.value;
        else {
            const prototype = e.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
            const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
            if (!setter || !['INPUT', 'TEXTAREA'].includes(e.tagName) || ['file', 'checkbox', 'radio'].includes(e.type))
                throw new Error('This control is not a text field.');
            setter.call(e, options.value);
        }
        send('input'); send('change');
        return {filled: true};
    }
    if (options.action === 'select') {
        if (e.tagName !== 'SELECT' || !Array.from(e.options).some(o => o.value === options.value))
            throw new Error('Choose a value present in a native select control. Inspect custom menus instead.');
        Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(e, options.value);
        send('input'); send('change');
        return {selected: e.value};
    }
    if (options.action === 'check') {
        if (!['checkbox', 'radio'].includes(e.type)) throw new Error('This is not a native checkbox or radio control.');
        if (e.checked !== options.checked) e.click();
        if (e.checked !== options.checked) throw new Error('The control did not accept the requested state.');
        return {checked: e.checked};
    }
    throw new Error('Unknown browser action.');
})