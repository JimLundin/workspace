(options => {
    const short = (value, limit = 200) => String(value ?? '').replace(/\s+/g, ' ').trim().slice(0, limit);
    const visible = e => {
        const r = e.getBoundingClientRect();
        const style = getComputedStyle(e);
        return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
    };
    const labelText = label => {
        const walker = document.createTreeWalker(label, NodeFilter.SHOW_TEXT);
        const parts = [];
        while (walker.nextNode()) {
            const node = walker.currentNode;
            if (!node.parentElement?.closest('input,textarea,select,button,[contenteditable]')) parts.push(node.textContent);
        }
        return parts.join(' ');
    };
    const selector = 'a[href],button,input,textarea,select,[contenteditable="true"],[role="button"],'
        + '[role="link"],[role="checkbox"],[role="radio"],[role="combobox"],[role="tab"],[role="menuitem"]';
    const elements = [];
    const roots = [document];
    let scanned = 0;
    while (roots.length && scanned < 20000) {
        const root = roots.shift();
        for (const e of root.querySelectorAll('*')) {
            if (++scanned > 20000) break;
            if (e.shadowRoot) roots.push(e.shadowRoot);
            if (e.matches(selector) && visible(e)) elements.push(e);
        }
    }
    const refs = new Map();
    const controls = elements.slice(options.offset, options.offset + options.limit).map((e, index) => {
        const id = options.prefix + '-' + index;
        refs.set(id, e);
        const labelled = (e.getAttribute('aria-labelledby') || '').split(/\s+/)
            .map(id => document.getElementById(id)?.textContent || '').join(' ');
        const labels = e.labels ? Array.from(e.labels).map(labelText).join(' ') : '';
        const secret = e.type === 'password' || e.autocomplete === 'one-time-code';
        return {
            id, tag: e.tagName.toLowerCase(), role: e.getAttribute('role') || '', type: e.type || '',
            name: short(e.getAttribute('aria-label') || labelled || labels || e.innerText || e.placeholder || e.title),
            value: secret ? '[private]' : short(e.value ?? (e.isContentEditable ? e.textContent : ''), 300),
            disabled: !!e.disabled || e.getAttribute('aria-disabled') === 'true',
            checked: !!e.checked || e.getAttribute('aria-checked') === 'true',
            href: e.tagName === 'A' ? short(e.href, 500) : '',
        };
    });
    globalThis.__workspaceControls = refs;
    const text = document.body?.innerText || '';
    return {
        title: short(document.title, 300), url: short(location.href, 1500),
        text: text.slice(options.text_offset, options.text_offset + 6000),
        text_offset: options.text_offset, text_total: text.length,
        controls, offset: options.offset, total: elements.length,
        more_controls: options.offset + options.limit < elements.length, scan_limited: scanned >= 20000,
    };
})