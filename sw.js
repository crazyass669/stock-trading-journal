const CACHE_NAME = 'trading-journal-v4';
const CORE_ASSETS = [
  './',
  './index.html',
  './manifest.json',
  './icon-192.png',
  './icon-512.png'
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(CORE_ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// same-origin core files: cache-first (แอปนี้ไม่มี backend ต้องอัปเดตบ่อย ใช้ cache-first แล้วรีเฟรชเงียบๆ เบื้องหลัง)
// ข้ามโดเมนอื่น (เช่น Google Fonts): network-first แล้ว fallback เป็น cache เมื่อออฟไลน์
self.addEventListener('fetch', (e) => {
  if(e.request.method !== 'GET') return;

  const url = new URL(e.request.url);
  const isSameOrigin = url.origin === self.location.origin;

  if(isSameOrigin){
    e.respondWith(
      caches.match(e.request).then(cached => {
        const fetchPromise = fetch(e.request).then(networkRes => {
          caches.open(CACHE_NAME).then(cache => cache.put(e.request, networkRes.clone()));
          return networkRes;
        }).catch(() => cached);
        return cached || fetchPromise;
      })
    );
  } else {
    e.respondWith(
      fetch(e.request).then(networkRes => {
        caches.open(CACHE_NAME).then(cache => cache.put(e.request, networkRes.clone()));
        return networkRes;
      }).catch(() => caches.match(e.request))
    );
  }
});
