import assert from 'node:assert/strict';
import test from 'node:test';
import { createMapController } from '../frontend/src/map.js';

// A minimal DOM fixture keeps the input regression tests dependency-free.
function viewer() {
  class Element {
    constructor() {
      this.style = {};
      this.listeners = {};
      this.classList = { add() {}, remove() {}, toggle() {} };
    }
    addEventListener(type, fn) { this.listeners[type] = fn; }
    contains(target) { return target === this; }
    setPointerCapture() {}
    fire(type, values = {}) {
      const event = {
        type, target: this, button: 0, pointerId: 1, pointerType: 'mouse',
        clientX: 270, clientY: 280, deltaX: 0, deltaY: 0, deltaMode: 0,
        preventDefault() { this.defaultPrevented = true; },
        ...values,
      };
      this.listeners[type]?.(event);
      return event;
    }
  }
  let now = 0;
  let nextFrame = 0;
  const frames = new Map();
  globalThis.Element = Element;
  globalThis.window = new Element();
  Object.defineProperty(globalThis, 'performance', { configurable: true, value: { now: () => now } });
  globalThis.requestAnimationFrame = fn => { frames.set(++nextFrame, fn); return nextFrame; };
  globalThis.cancelAnimationFrame = id => frames.delete(id);
  const image = new Element();
  Object.assign(image, { complete: true, naturalWidth: 1000, naturalHeight: 1000 });
  const sizer = new Element();
  const content = new Element();
  const container = new Element();
  Object.assign(container, { clientWidth: 500, clientHeight: 500, scrollLeft: 0, scrollTop: 0 });
  container.getBoundingClientRect = () => ({ left: 20, top: 30, right: 520, bottom: 530, width: 500, height: 500 });
  container.querySelector = selector => ({ '#map': image, '#map-sizer': sizer, '#map-content': content })[selector];
  const guesses = [];
  const controller = createMapController(container, {}, (lat, lon) => guesses.push({ lat, lon }));
  return {
    container, guesses, controller, window: globalThis.window,
    scale: () => Number(content.style.transform.match(/scale\(([^)]+)\)/)[1]),
    advance: ms => { now += ms; },
    flush() {
      const pending = [...frames.values()];
      frames.clear();
      pending.forEach(fn => fn());
    },
  };
}

function near(actual, expected) {
  assert(Math.abs(actual - expected) < 0.0001, `${actual} != ${expected}`);
}

function pointer(v, type, pointerId, x, y, extra = {}) {
  return v.container.fire(type, { pointerId, pointerType: 'touch', clientX: 20 + x, clientY: 30 + y, ...extra });
}

function safari(v, type, scale, inside = true) {
  return v.window.fire(type, { scale, target: inside ? v.container : {}, clientX: inside ? 270 : 700, clientY: inside ? 280 : 700 });
}

test('mouse wheel and Ctrl+wheel zoom around the cursor with bounded scale', () => {
  const v = viewer();
  assert(v.container.fire('wheel', { deltaY: -100 }).defaultPrevented);
  assert(v.scale() > 1);
  near((v.container.scrollLeft + 250) / (500 * v.scale()), 0.5);
  near((v.container.scrollTop + 250) / (500 * v.scale()), 0.5);
  const previous = v.scale();
  v.container.fire('wheel', { deltaY: -20, ctrlKey: true });
  assert(v.scale() > previous);
  v.container.fire('wheel', { deltaY: -10000, ctrlKey: true });
  assert.equal(v.scale(), 5);
  v.container.fire('wheel', { deltaY: 10000, ctrlKey: true });
  assert.equal(v.scale(), 1);
  assert.equal(v.guesses.length, 0);
});

test('smooth trackpad scrolling pans in both axes without changing zoom', () => {
  const v = viewer();
  v.container.fire('wheel', { deltaY: -100, ctrlKey: true });
  const scale = v.scale();
  const left = v.container.scrollLeft, top = v.container.scrollTop;
  v.container.fire('wheel', { deltaX: 8.5, deltaY: 12.5 });
  v.flush();
  assert.equal(v.scale(), scale);
  near(v.container.scrollLeft, left + 8.5);
  near(v.container.scrollTop, top + 12.5);
});

test('mouse dragging pans without placing a guess; subsequent clicks use transformed coordinates', () => {
  const v = viewer();
  v.container.fire('wheel', { deltaY: -100, ctrlKey: true });
  const left = v.container.scrollLeft, top = v.container.scrollTop;
  v.container.fire('pointerdown');
  v.container.fire('pointermove', { clientX: 230, clientY: 250 });
  v.container.fire('pointerup');
  v.container.fire('click');
  assert.equal(v.guesses.length, 0);
  near(v.container.scrollLeft, left + 40);
  near(v.container.scrollTop, top + 30);
  v.advance(200);
  v.container.fire('click');
  assert.equal(v.guesses.length, 1);
  near(v.guesses[0].lon, (v.container.scrollLeft + 250) / (500 * v.scale()));
  near(v.guesses[0].lat, (v.container.scrollTop + 250) / (500 * v.scale()));
});

test('Safari pinch affects only the map and suppresses duplicate wheel zoom and clicks', () => {
  const v = viewer();
  assert(!safari(v, 'gesturestart', 1, false).defaultPrevented);
  assert.equal(v.scale(), 1);
  assert(safari(v, 'gesturestart', 1).defaultPrevented);
  safari(v, 'gesturechange', 2);
  v.flush();
  assert.equal(v.scale(), 2);
  v.container.fire('wheel', { deltaY: -100, ctrlKey: true });
  assert.equal(v.scale(), 2);
  safari(v, 'gestureend', 2);
  v.flush();
  v.container.fire('click');
  assert.equal(v.guesses.length, 0);
  v.advance(200);
  v.container.fire('click');
  assert.equal(v.guesses.length, 1);
});

test('mobile pinch and a delayed final finger release do not place a guess', () => {
  const v = viewer();
  pointer(v, 'pointerdown', 1, 200, 250);
  pointer(v, 'pointerdown', 2, 300, 250);
  pointer(v, 'pointermove', 1, 100, 250);
  pointer(v, 'pointermove', 2, 400, 250);
  assert.equal(v.scale(), 3);
  near((v.container.scrollLeft + 250) / (500 * v.scale()), 0.5);
  pointer(v, 'pointerup', 1, 100, 250);
  v.advance(500);
  pointer(v, 'pointerup', 2, 400, 250);
  v.container.fire('click');
  assert.equal(v.guesses.length, 0);
  v.advance(200);
  pointer(v, 'pointerdown', 3, 250, 250);
  pointer(v, 'pointerup', 3, 250, 250);
  v.container.fire('click');
  assert.equal(v.guesses.length, 1);
});

test('one-finger pan moves the map without a guess; touch cancellation releases input', () => {
  const v = viewer();
  v.container.fire('wheel', { deltaY: -100, ctrlKey: true });
  const left = v.container.scrollLeft, top = v.container.scrollTop;
  pointer(v, 'pointerdown', 1, 250, 250);
  pointer(v, 'pointermove', 1, 225, 220);
  pointer(v, 'pointercancel', 1, 225, 220);
  v.container.fire('click');
  assert.equal(v.guesses.length, 0);
  near(v.container.scrollLeft, left + 25);
  near(v.container.scrollTop, top + 30);
  v.advance(200);
  pointer(v, 'pointerdown', 2, 250, 250);
  pointer(v, 'pointerup', 2, 250, 250);
  v.container.fire('click');
  assert.equal(v.guesses.length, 1);
});

test('native gestures do not double-handle an active mobile touch pinch', () => {
  const v = viewer();
  pointer(v, 'pointerdown', 1, 200, 250);
  pointer(v, 'pointerdown', 2, 300, 250);
  safari(v, 'gesturestart', 1);
  safari(v, 'gesturechange', 2);
  v.flush();
  assert.equal(v.scale(), 1);
  pointer(v, 'pointermove', 2, 400, 250);
  assert.equal(v.scale(), 2);
});

test('spectators and non-guessing phases can navigate but cannot place guesses', () => {
  const v = viewer();
  v.controller.setObserve(true);
  v.container.fire('click');
  v.container.fire('wheel', { deltaY: -100 });
  assert(v.scale() > 1);
  assert.equal(v.guesses.length, 0);
  v.controller.setObserve(false);
  v.controller.setClickable(false);
  v.container.fire('click');
  assert.equal(v.guesses.length, 0);
});
