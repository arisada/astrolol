// Minimal service worker — satisfies Chrome's PWA installability requirement.
// No caching, and requests are not intercepted: passing them on with fetch() would change
// their headers (a page reload would no longer look like a navigation to the server).
self.addEventListener('fetch', () => {})
