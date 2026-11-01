import assert from 'node:assert/strict';
import test from 'node:test';
import { randomUUID } from 'node:crypto';

const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
let page = 0;
const room = status => ({ room_id: 'r1', host_id: 'alice', revision: 1,
  min_players: 2, max_players: 10, rounds: 6, difficulty: 'N', scoring_strategy: 'ranking',
  status, players: [{ player_id: 'alice' }], spectators: [] });

async function lobby(t, heartbeatResult) {
  const elements = new Map();
  class Element extends EventTarget {
    constructor() { super(); this.value = ''; this.style = {}; this.disabled = false; }
  }
  const get = id => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  const intervals = new Map();
  const originalSet = globalThis.setInterval, originalClear = globalThis.clearInterval;
  globalThis.setInterval = (fn, delay) => { const id = {}; intervals.set(id, { fn, delay }); return id; };
  globalThis.clearInterval = id => intervals.delete(id);
  const sources = [];
  class Source {
    constructor(url) { this.url = url; this.listeners = {}; sources.push(this); }
    addEventListener(name, fn) { this.listeners[name] = fn; }
    close() { this.closed = true; }
    emit(name, data) { this.listeners[name]?.({ data: JSON.stringify(data) }); }
  }
  const calls = [];
  Object.assign(globalThis, {
    crypto: { randomUUID }, EventSource: Source,
    window: Object.assign(new EventTarget(), { location: { href: '' } }),
    document: Object.assign(new EventTarget(), { hidden: false, readyState: 'loading',
      getElementById: get, querySelectorAll: () => [] }),
    location: new URL('https://example.test/lobby'),
    localStorage: { getItem: () => 'alice', setItem() {} },
    sessionStorage: { getItem: () => null, setItem() {} },
    fetch: async (url, options) => {
      calls.push({ url, body: JSON.parse(options.body) });
      const data = url.endsWith('/heartbeat') ? heartbeatResult : {
        room_id: 'r1', is_host: true, role: 'player', sse_url: '/events/lobby/r1?player_id=alice', room: room('WAITING'),
      };
      return new Response(JSON.stringify(data));
    },
  });
  get('min-players').value = '2'; get('max-players').value = '10';
  get('rounds').value = '6'; get('difficulty').value = 'N'; get('scoring-strategy').value = 'ranking';
  await import(`../frontend/src/lobby.js?test=${++page}`);
  get('btn-join').dispatchEvent(new Event('click'));
  for (let i = 0; i < 100 && !intervals.size; i++) await wait(5);
  assert.equal(intervals.size, 1);
  const heartbeat = [...intervals.values()][0].fn;
  t.after(() => {
    document.hidden = true;
    window.dispatchEvent(new Event('pagehide'));
    globalThis.setInterval = originalSet; globalThis.clearInterval = originalClear;
  });
  return { elements, get, calls, sources, intervals, heartbeat };
}

for (const channel of ['stream', 'heartbeat']) {
  test(`replacement through ${channel} stops the old tab without rejoining`, async t => {
    const state = await lobby(t, { ok: true, present: false, replaced: true });
    assert(new URL(state.sources[0].url).searchParams.get('connection_id'));
    if (channel === 'stream') state.sources[0].emit('connection_replaced', { player_id: 'alice', connection_id: 'new-tab' });
    else await state.heartbeat();
    assert(state.sources[0].closed);
    assert.equal(state.intervals.size, 0);
    assert.equal(state.get('waiting-room').style.display, 'none');
    assert.equal(state.get('btn-join').disabled, false);
    await state.heartbeat();
    assert.equal(state.calls.filter(c => c.url.endsWith('/join')).length, 1);
  });
}

test('an expired matching lease restores the lobby without automatic rejoin', async t => {
  const state = await lobby(t, { ok: true, present: false, room: room('WAITING') });
  await state.heartbeat();
  assert.equal(state.get('status-text').textContent, 'Matching timed out.');
  assert.equal(state.intervals.size, 0);
  assert.equal(state.calls.filter(c => c.url.endsWith('/join')).length, 1);
});

test('an expired stream restores the lobby instead of entering a later game', async t => {
  const state = await lobby(t, { ok: true, present: false });
  state.sources[0].emit('membership_expired', {});
  state.sources[0].emit('match_starting', { room_id: 'r1' });
  assert.equal(window.location.href, '');
  assert.equal(state.get('status-text').textContent, 'Matching timed out.');
});

test('a missing seat in a started room cannot auto-rejoin or enter the game', async t => {
  const state = await lobby(t, { ok: true, present: false, room: room('IN_GAME') });
  await state.heartbeat();
  assert.equal(state.intervals.size, 0);
  assert.equal(window.location.href, '');
  assert.equal(state.calls.filter(c => c.url.endsWith('/join')).length, 1);
});

test('a current matching connection still recovers a missed game-start event', async t => {
  const state = await lobby(t, { ok: true, present: true, room: room('IN_GAME') });
  await state.heartbeat();
  assert.equal(window.location.href, '/index.html?room=r1&player_id=alice');
});
