import assert from 'node:assert/strict';
import test from 'node:test';
import { randomUUID } from 'node:crypto';

const windowEvents = new EventTarget();
const documentEvents = new EventTarget();
Object.assign(globalThis, {
  window: windowEvents,
  document: Object.assign(documentEvents, { hidden: false, readyState: 'complete' }),
  crypto: { randomUUID },
});
const storage = new Map();
globalThis.sessionStorage = { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, String(value)) };
const intervals = new Map();
let timerId = 0;
const nativeSetInterval = globalThis.setInterval;
const nativeClearInterval = globalThis.clearInterval;
globalThis.setInterval = (fn, delay) => { intervals.set(++timerId, { fn, delay }); return timerId; };
globalThis.clearInterval = id => intervals.delete(id);

class Source {
  static instances = [];
  constructor(url) { this.url = url; this.listeners = {}; Source.instances.push(this); }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  close() { this.closed = true; }
}
globalThis.EventSource = Source;
const { createSyncScheduler } = await import('../frontend/src/sync.js');
const response = data => new Response(JSON.stringify(data), { status: 200 });
const baseState = () => ({ state_version: 1, round: 1, phase: 'guess', players: [] });
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

function scheduler(t, handler) {
  storage.clear();
  Source.instances.length = 0;
  document.hidden = false;
  globalThis.fetch = handler;
  const sync = createSyncScheduler();
  t.after(() => sync.destroy());
  return sync;
}

test('safety reconciliation runs every two seconds without adding a second poller on SSE errors', async t => {
  let reads = 0;
  const sync = scheduler(t, async () => { reads++; return response(baseState()); });
  await sync.connect('room', 'alice');
  assert.equal(intervals.size, 1);
  const poll = [...intervals.values()][0];
  assert.equal(poll.delay, 2000);
  poll.fn();
  await wait(5);
  assert.equal(reads, 2);
  Source.instances[0].onerror();
  assert.equal(intervals.size, 1);
});

test('an event arriving during a state fetch is reconciled after that request completes', async t => {
  let resolveRead;
  let reads = 0;
  const sync = scheduler(t, () => {
    reads++;
    if (reads === 1) return new Promise(resolve => { resolveRead = resolve; });
    return Promise.resolve(response({ ...baseState(), state_version: 2 }));
  });
  const initial = sync.connect('room', 'alice');
  const duplicate = sync.fetchState();
  assert.equal(reads, 1);
  resolveRead(response(baseState()));
  await Promise.all([initial, duplicate]);
  await wait(60);
  assert.equal(reads, 2);
});

test('a lost action response retries the same action id and requires its acknowledgement', async t => {
  const writes = [];
  const sync = scheduler(t, async (url, options) => {
    if (!options.method) return response(baseState());
    const body = JSON.parse(options.body);
    writes.push(body);
    if (writes.length === 1) throw new TypeError('Response lost after server accepted action');
    return response({ ...baseState(), state_version: 2, ack: body });
  });
  await sync.connect('room', 'alice');
  await sync.postAction('/api/place_guess', { lat: 0.2, lon: 0.3 });
  assert.equal(writes.length, 2);
  assert.equal(writes[0].action_id, writes[1].action_id);
  assert.equal(writes[0].round, 1);
});

test('guesses are delivered in order before Submit', async t => {
  const writes = [];
  const sync = scheduler(t, async (url, options) => {
    if (!options.method) return response(baseState());
    const body = JSON.parse(options.body);
    writes.push({ url, body });
    await wait(5);
    return response({ ...baseState(), state_version: writes.length + 1, ack: body });
  });
  await sync.connect('room', 'alice');
  await Promise.all([
    sync.postAction('/api/place_guess', { lat: 0.1, lon: 0.2 }),
    sync.postAction('/api/place_guess', { lat: 0.3, lon: 0.4 }),
    sync.postAction('/api/submit'),
  ]);
  assert.deepEqual(writes.map(item => item.url.split('?')[0]), ['/api/place_guess', '/api/place_guess', '/api/submit']);
  assert.equal(writes[1].body.lat, 0.3);
  assert(writes[0].body.sequence < writes[1].body.sequence && writes[1].body.sequence < writes[2].body.sequence);
});

test('Submit re-delivers an unconfirmed latest guess first', async t => {
  const writes = [];
  const sync = scheduler(t, async (url, options) => {
    if (!options.method) return response(baseState());
    const body = JSON.parse(options.body);
    writes.push({ url, body });
    if (writes.length <= 2) throw new TypeError('Temporarily disconnected');
    return response({ ...baseState(), state_version: 2, ack: body });
  });
  await sync.connect('room', 'alice');
  await assert.rejects(sync.postAction('/api/place_guess', { lat: 0.3, lon: 0.4 }));
  await sync.postAction('/api/submit');
  assert.equal(writes.length, 4);
  assert.equal(writes[0].body.action_id, writes[2].body.action_id);
  assert(writes[3].url.startsWith('/api/submit?'));
});

test('stale-round rejection triggers a state refresh and does not retry the old action', async t => {
  let writes = 0, reads = 0;
  const sync = scheduler(t, async (url, options) => {
    if (!options.method) { reads++; return response({ ...baseState(), round: reads > 1 ? 2 : 1 }); }
    writes++;
    return new Response(JSON.stringify({ error: 'Round changed', code: 'STALE_ROUND' }), { status: 409 });
  });
  await sync.connect('room', 'alice');
  await assert.rejects(sync.postAction('/api/submit'), error => error.code === 'STALE_ROUND');
  assert.equal(writes, 1);
  assert.equal(reads, 2);
});

test('pageshow restores a suspended stream and fetches a fresh snapshot', async t => {
  let reads = 0;
  const sync = scheduler(t, async () => { reads++; return response(baseState()); });
  await sync.connect('room', 'alice');
  window.dispatchEvent(new Event('pagehide'));
  assert(Source.instances[0].closed);
  window.dispatchEvent(new Event('pageshow'));
  await wait(5);
  assert.equal(Source.instances.length, 2);
  assert.equal(reads, 2);
});

test.after(() => {
  globalThis.setInterval = nativeSetInterval;
  globalThis.clearInterval = nativeClearInterval;
});

test('prefetch waits for idle time, uses low priority, and never decodes an Image', async t => {
  const idle = [];
  window.requestIdleCallback = true;
  globalThis.requestIdleCallback = fn => idle.push(fn);
  globalThis.location = new URL('https://example.test/lobby');
  const transfers = [];
  globalThis.Image = class { constructor() { throw new Error('Prefetch must not decode images'); } };
  globalThis.fetch = async (url, options) => { transfers.push({ url, options }); return new Response('image'); };
  const { prefetchImages } = await import('../frontend/src/connection.js');
  const stop = prefetchImages(['/next.jpg']);
  t.after(() => { stop(); delete window.requestIdleCallback; delete globalThis.requestIdleCallback; });
  assert.equal(transfers.length, 0);
  await idle.shift()();
  assert.equal(transfers.length, 1);
  assert.equal(transfers[0].options.priority, 'low');
  assert.equal(transfers[0].options.cache, 'force-cache');
  while (idle.length) await idle.shift()();
});

test('urgent actions interrupt an active background prefetch', async t => {
  const idle = [];
  window.requestIdleCallback = true;
  globalThis.requestIdleCallback = fn => idle.push(fn);
  globalThis.location = new URL('https://example.test/lobby');
  let prefetchSignal;
  let urgentPriority;
  globalThis.fetch = (url, options) => {
    if (options.method === 'POST') {
      urgentPriority = options.priority;
      return Promise.resolve(response({ ok: true }));
    }
    prefetchSignal = options.signal;
    return new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError'))));
  };
  const { prefetchImages, requestJson } = await import('../frontend/src/connection.js');
  const stop = prefetchImages(['/background-map.jpg']);
  t.after(() => { stop(); delete window.requestIdleCallback; delete globalThis.requestIdleCallback; });
  const background = idle.shift()();
  await requestJson('/api/submit', { method: 'POST' });
  await background;
  assert(prefetchSignal.aborted);
  assert.equal(urgentPriority, 'high');
  stop();
  while (idle.length) await idle.shift()();
});

test('an unresponsive state request is aborted within the recovery budget', async () => {
  const { requestJson } = await import('../frontend/src/connection.js');
  globalThis.fetch = (url, options) => new Promise((resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new DOMException('Timed out', 'AbortError')));
  });
  const start = performance.now();
  await assert.rejects(requestJson('/api/state'), error => error.name === 'AbortError');
  assert(performance.now() - start < 3000);
});
