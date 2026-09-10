// VayuSetu service worker: makes the app installable and keeps its shell
// available offline.
//
// API responses are never cached. An air quality reading served from a cache is a
// stale reading shown as current, which for this app is worse than no reading.
// The API lives on another origin, and the Google Maps scripts too, so neither is
// intercepted here.

const CACHE = 'vayusetu-shell-v1';
const SHELL = ['/', '/manifest.webmanifest', '/favicon.svg', '/icon-192.png'];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))),
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin) return;

  // Network first, so a new deploy is picked up at once; the cache answers only offline.
  event.respondWith(
    fetch(event.request)
      .then(response => {
        const copy = response.clone();
        caches.open(CACHE).then(cache => cache.put(event.request, copy));
        return response;
      })
      .catch(() => caches.match(event.request).then(hit => hit || caches.match('/'))),
  );
});
