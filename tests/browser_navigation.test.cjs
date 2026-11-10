const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const script = fs.readFileSync(require('node:path').join(__dirname, '../backend/browser_navigation.js'), 'utf8');
function setup() {
  const requests = [], handlers = {};
  let nativeCalls = 0;
  const sandbox = { URL, location: { href: 'https://example.org/watch' },
    document: { addEventListener: (type, handler) => handlers[type] = handler, querySelector: () => null },
    open: () => nativeCalls++, __uvdRequestNavigation: value => { requests.push(value); return Promise.resolve(); },
  };
  sandbox.window = sandbox;
  vm.runInNewContext(script, sandbox);
  return { sandbox, requests, handlers, nativeCalls: () => nativeCalls };
}
test('window.open queues a proposal without creating a window', () => {
  const state = setup();
  assert.equal(state.sandbox.open('https://ads.example.org/landing'), null);
  assert.equal(state.nativeCalls(), 0);
  assert.equal(state.requests[0].url, 'https://ads.example.org/landing');
  assert.equal(state.requests[0].kind, 'popup');
});
test('same-tab window.open waits for consent too', () => {
  const state = setup();
  state.sandbox.open('/next', '_self');
  assert.equal(state.requests[0].kind, 'navigate');
  assert.equal(state.nativeCalls(), 0);
});
test('blank windows and unsafe schemes never reach the native opener', () => {
  const state = setup();
  state.sandbox.open(); state.sandbox.open('javascript:alert(1)'); state.sandbox.open('file:///tmp/a');
  assert.equal(state.requests.length, 0);
  assert.equal(state.nativeCalls(), 0);
});
test('target blank anchor is stopped before native navigation', () => {
  const state = setup();
  let prevented = false, stopped = false;
  const anchor = { href: 'https://external.example.org/', hasAttribute: () => false, getAttribute: () => '_blank' };
  state.handlers.click({ target: { closest: () => anchor }, preventDefault: () => prevented = true, stopImmediatePropagation: () => stopped = true });
  assert.ok(prevented && stopped);
  assert.equal(state.requests[0].kind, 'popup');
  assert.equal(state.nativeCalls(), 0);
});
