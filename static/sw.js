// PWA Service Worker (Cache & Offline Support for AI Data Insight Builder)
const CACHE_NAME = 'data-insight-builder-v1';
const STATIC_ASSETS = [
  '/',
  '/static/style.css',
  '/static/app.js',
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/icon.svg'
];

// 1. 설치 (Install): 정적 자산 캐싱
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

// 2. 활성화 (Activate): 이전 버전 캐시 정리
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      );
    })
  );
  self.clients.claim();
});

// 3. 네트워크 요청 처리 (Fetch)
self.addEventListener('fetch', (event) => {
  // API POST 요청(/inspect, /suggest, /run, /explain, /query, /followup)은 항상 실시간 서버로 전송
  if (event.request.method !== 'GET' || 
      event.request.url.includes('/inspect') ||
      event.request.url.includes('/suggest') ||
      event.request.url.includes('/run') ||
      event.request.url.includes('/explain') ||
      event.request.url.includes('/query') ||
      event.request.url.includes('/followup') ||
      event.request.url.includes('/health')) {
    return;
  }

  // 네트워크 우선(Network-First), 오프라인 시 캐시 폴백
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response && response.status === 200) {
          const responseClone = response.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, responseClone);
          });
        }
        return response;
      })
      .catch(() => {
        return caches.match(event.request);
      })
  );
});
