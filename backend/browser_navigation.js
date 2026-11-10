(() => {
  // Installed in every frame before site scripts. A popup proposal is data, not
  // a real Window: the browser process creates a tab only after explicit Go.
  const propose = (value, kind) => {
    let target;
    try { target = new URL(String(value || ''), location.href); } catch { return; }
    if (!['http:', 'https:'].includes(target.protocol)) return;
    window.__uvdRequestNavigation({ url: target.href, kind }).catch(() => {});
  };
  Object.defineProperty(window, 'open', {
    configurable: false, writable: false,
    value: (url, target = '_blank') => {
      if (url) propose(url, ['_self', '_top', '_parent'].includes(String(target).toLowerCase()) ? 'navigate' : 'popup');
      return null;
    },
  });
  document.addEventListener('click', event => {
    const anchor = event.target?.closest?.('a[href]');
    if (!anchor || anchor.hasAttribute('download')) return;
    const target = (anchor.getAttribute('target') || document.querySelector('base[target]')?.getAttribute('target') || '').toLowerCase();
    if (!target || ['_self', '_top', '_parent'].includes(target)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    propose(anchor.href, 'popup');
  }, true);
})();
