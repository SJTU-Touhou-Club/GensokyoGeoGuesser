const STORAGE_KEY = "ggg_connection_id";
let pageConnectionId = null;

export function getConnectionId() {
  // A restored page keeps its identity; a cloned tab receives its own lease.
  if (!pageConnectionId) {
    pageConnectionId = crypto.randomUUID();
    sessionStorage.setItem(STORAGE_KEY, pageConnectionId);
  }
  return pageConnectionId;
}

export function getStoredPlayerId() {
  return localStorage.getItem("ggg_player_id") || "";
}

export function setStoredPlayerId(id) {
  localStorage.setItem("ggg_player_id", id);
}

let activeRequests = 0;
let prefetchTask = null;
let prefetchRunning = false;
const prefetchQueue = new Map();
const prefetched = new Set();

// Safari may discard large fetches from its HTTP cache. Keep only the two maps
// in disk-backed Cache Storage, without decoding them during lobby prefetch.
const MAP_CACHE = "ggg-maps-v2";
const MAP_PATHS = new Set(["/media/map_v2.jpg", "/media/ref_map_v2.jpg"]);
const mapLoads = new WeakMap();

async function openMapCache(url) {
  try {
    const parsed = new URL(url, location.href);
    if (parsed.origin === location.origin && MAP_PATHS.has(parsed.pathname) && "caches" in globalThis) {
      return await caches.open(MAP_CACHE);
    }
  } catch { /* Cache Storage can be unavailable in private browsing. */ }
  return null;
}

async function cachedMap(cache, url) {
  if (!cache) return null;
  try {
    const response = await cache.match(url);
    if (!response) return null;
    const stored = Date.parse(response.headers.get("date"));
    if (Number.isFinite(stored) && Date.now() - stored < 86400000) return response;
    await cache.delete(url);
  } catch { /* Fall back to the ordinary image request. */ }
  return null;
}

export function loadCachedMap(image, url) {
  if (mapLoads.has(image)) return mapLoads.get(image);
  const loading = (async () => {
    try {
      const absolute = new URL(url, location.href).href;
      const response = await cachedMap(await openMapCache(absolute), absolute);
      if (response) {
        const objectUrl = URL.createObjectURL(await response.blob());
        const release = () => {
          URL.revokeObjectURL(objectUrl);
          image.removeEventListener("load", release);
          image.removeEventListener("error", fallback);
        };
        const fallback = () => { release(); image.src = url; };
        image.addEventListener("load", release, { once: true });
        image.addEventListener("error", fallback, { once: true });
        image.src = objectUrl;
        return;
      }
    } catch { /* Cache failure must never prevent the map from loading. */ }
    image.src = url;
  })();
  mapLoads.set(image, loading);
  return loading;
}

export async function requestJson(url, options = {}) {
  const { background, ...fetchOptions } = options;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 2000);
  activeRequests += 1;
  if (options.method === "POST" && !background) prefetchTask?.abort();
  try {
    const response = await fetch(url, {
      ...fetchOptions, signal: controller.signal, cache: "no-store", priority: "high",
    });
    const data = await response.json();
    if (!response.ok || data.error) {
      const error = new Error(data.error || `Request failed (${response.status})`);
      error.code = data.code;
      error.status = response.status;
      throw error;
    }
    return data;
  } finally {
    clearTimeout(timeout);
    activeRequests -= 1;
  }
}

export function prefetchImages(urls) {
  const added = urls.filter(Boolean).map(url => new URL(url, location.href).href);
  for (const url of added) {
    if (!prefetched.has(url) && !prefetchQueue.has(url)) prefetchQueue.set(url, 0);
  }
  if (!prefetchRunning) {
    prefetchRunning = true;
    const run = async () => {
      if (!prefetchQueue.size || document.hidden) {
        prefetchRunning = false;
        return;
      }
      if (activeRequests || document.readyState !== "complete") {
        setTimeout(run, 250);
        return;
      }
      const [url, attempts] = prefetchQueue.entries().next().value;
      prefetchTask = new AbortController();
      let cancelled = false;
      try {
        const cache = await openMapCache(url);
        const cached = await cachedMap(cache, url);
        prefetchTask.signal.throwIfAborted();
        const response = cached || await fetch(url, {
          priority: "low", cache: "force-cache", signal: prefetchTask.signal,
        });
        if (!response.ok) throw new Error("Prefetch failed");
        // Cache Storage consumes the stream directly; no clone or decoded Image.
        if (!cached && cache) {
          await cache.put(url, response);
        } else if (!cached && response.body) {
          const reader = response.body.getReader();
          while (!(await reader.read()).done) { /* discard chunks */ }
        } else if (!cached) {
          await response.blob();
        }
        prefetched.add(url);
        prefetchQueue.delete(url);
      } catch (error) {
        cancelled = error.name === "AbortError";
        if (!cancelled && attempts >= 1) prefetchQueue.delete(url);
        else if (prefetchQueue.has(url)) prefetchQueue.set(url, attempts + (cancelled ? 0 : 1));
      } finally {
        prefetchTask = null;
      }
      if ("requestIdleCallback" in window) requestIdleCallback(run);
      else setTimeout(run, cancelled ? 500 : 100);
    };
    if ("requestIdleCallback" in window) requestIdleCallback(run);
    else setTimeout(run, 100);
  }
  return () => {
    for (const url of added) prefetchQueue.delete(url);
    prefetchTask?.abort();
  };
}

window.addEventListener("pagehide", () => {
  prefetchQueue.clear();
  prefetchTask?.abort();
});
