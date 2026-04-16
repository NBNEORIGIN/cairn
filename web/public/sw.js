/*
 * Deek service worker.
 *
 * Strategy:
 *   - network-first for navigation requests (always try fresh HTML),
 *     falling back to the cached shell or an offline page if the
 *     network is unreachable. This matters because Deek is a live
 *     agent — stale UI would be misleading.
 *   - network-only for /api/* (no caching of agent responses; the
 *     chat stream is an SSE connection the SW shouldn't touch).
 *   - cache-first for /icon-*.png, /favicon.*, /apple-touch-icon.png,
 *     /manifest.webmanifest, /offline.html, and _next/static/* — these
 *     are content-hashed or immutable and benefit from instant load.
 *
 * Bump CACHE_VERSION when you change this file or want to flush the
 * cache. sw.js is not versioned by next/static so we handle it here.
 */

const CACHE_VERSION = 'cairn-v1';
const SHELL_CACHE = `${CACHE_VERSION}-shell`;
const RUNTIME_CACHE = `${CACHE_VERSION}-runtime`;

// Files to precache on install. Keep this list small — most static
// assets are cache-on-demand via the fetch handler.
const SHELL_ASSETS = [
  '/offline.html',
  '/icon-192.png',
  '/icon-512.png',
  '/manifest.webmanifest',
  '/favicon.ico',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL_ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => !key.startsWith(CACHE_VERSION))
          .map((stale) => caches.delete(stale))
      )
    ).then(() => self.clients.claim())
  );
});

function shouldBypass(url) {
  return (
    url.pathname.startsWith('/api/') ||
    url.pathname.startsWith('/ws') ||
    url.pathname.includes('/stream')
  );
}

function isImmutableStatic(url) {
  return (
    url.pathname.startsWith('/_next/static/') ||
    url.pathname.startsWith('/icon-') ||
    url.pathname.startsWith('/favicon') ||
    url.pathname === '/apple-touch-icon.png' ||
    url.pathname === '/manifest.webmanifest'
  );
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  // Never touch API calls, WS, or SSE streams — let them fail loud.
  if (shouldBypass(url)) return;

  // Navigation — network-first with offline fallback.
  if (request.mode === 'navigate') {
    event.respondWith(
      (async () => {
        try {
          const network = await fetch(request);
          const runtime = await caches.open(RUNTIME_CACHE);
          runtime.put(request, network.clone());
          return network;
        } catch (err) {
          const runtime = await caches.open(RUNTIME_CACHE);
          const cached = await runtime.match(request);
          if (cached) return cached;
          const shell = await caches.open(SHELL_CACHE);
          return (await shell.match('/offline.html')) || new Response('Offline', { status: 503 });
        }
      })()
    );
    return;
  }

  // Immutable static — cache-first.
  if (isImmutableStatic(url)) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request)
          .then((response) => {
            if (!response || response.status !== 200) return response;
            const clone = response.clone();
            caches.open(RUNTIME_CACHE).then((cache) => cache.put(request, clone));
            return response;
          })
          .catch(() => cached);
      })
    );
    return;
  }

  // Everything else — stale-while-revalidate.
  event.respondWith(
    caches.match(request).then((cached) => {
      const networkFetch = fetch(request)
        .then((response) => {
          if (response && response.status === 200) {
            const clone = response.clone();
            caches.open(RUNTIME_CACHE).then((cache) => cache.put(request, clone));
          }
          return response;
        })
        .catch(() => cached);
      return cached || networkFetch;
    })
  );
});
