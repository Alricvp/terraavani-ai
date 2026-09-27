// Terraavani AI Service Worker — Offline Support
const CACHE_NAME = 'terraavani-v1';
const OFFLINE_URLS = [
  '/',
  '/dashboard.html',
  '/manifest.json',
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',
  'https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap'
];

// Install — cache essential files
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(OFFLINE_URLS))
  );
  self.skipWaiting();
});

// Activate — clean old caches
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
    ))
  );
  self.clients.claim();
});

// Fetch — network first, fallback to cache
self.addEventListener('fetch', event => {
  // Skip API calls — always go to network
  if (event.request.url.includes('/api/') || event.request.url.includes('/ws')) {
    event.respondWith(
      fetch(event.request).catch(() => {
        return new Response(JSON.stringify({error: 'Offline', data: null}), {
          headers: {'Content-Type': 'application/json'}
        });
      })
    );
    return;
  }

  // Network first for HTML pages (so updates are seen)
  // Cache first for static assets (CSS, JS, images)
  const isHTML = event.request.mode === 'navigate' || event.request.url.endsWith('/');
  
  if (isHTML) {
    // NETWORK FIRST — always try to get fresh version
    event.respondWith(
      fetch(event.request).then(response => {
        if (response.status === 200) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      }).catch(() => {
        // Offline fallback — return cached dashboard
        return caches.match(event.request).then(cached => cached || caches.match('/'));
      })
    );
  } else {
    // CACHE FIRST — for CSS, JS, fonts, images
    event.respondWith(
      caches.match(event.request).then(cached => {
        return cached || fetch(event.request).then(response => {
          if (response.status === 200) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
          }
          return response;
        });
      }).catch(() => {
        return new Response('', {status: 503});
      })
    );
  }
});

// Listen for messages from main thread
self.addEventListener('message', event => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
  // Show notification on behalf of the page (required on Android Chrome)
  if (event.data && event.data.type === 'notify') {
    self.registration.showNotification(event.data.title, {
      body: event.data.body,
      tag: 'terraavani-v1',
      renotify: true,
      vibrate: [300, 120, 300, 120, 300],
      requireInteraction: event.data.body && event.data.body.includes('DANGER')
    });
  }
});

// Notification tap — focus the app or open it
self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(cs => {
      for (const c of cs) { if ('focus' in c) return c.focus(); }
      return self.clients.openWindow('/');
    })
  );
});
