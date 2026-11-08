new Promise(resolve => {
    if (document.visibilityState !== 'visible') return resolve(false);
    setTimeout(() => resolve(false), 1000);
    requestAnimationFrame(() => requestAnimationFrame(() => resolve(true)));
})
