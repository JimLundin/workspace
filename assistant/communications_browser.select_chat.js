identity => {
    const row=[...document.querySelectorAll('[role="treeitem"]')].find(e=>{
      const match=(e.getAttribute('data-fui-tree-item-value')||'').match(/19:[^\s/]+@(?:thread\.v2|unq\.gbl\.spaces)/);
      return match?.[0]===identity;
    });
    if(!row) return false;
    row.click(); return true;
}
