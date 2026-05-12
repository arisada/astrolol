// Minimal service worker — satisfies Chrome's PWA installability requirement.
// No caching: every request goes to the network as normal.
self.addEventListener('fetch', (event) => {
  event.respondWith(fetch(event.request))
})
