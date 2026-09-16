/**
 * Service Worker for Concentration Analyzer (QuantLab PWA)
 * Enables offline shell, instant loading, and installability on Android, iOS & Desktop.
 */

const CACHE_NAME = 'quantlab-cache-v1';
const PRECACHE_ASSETS = [
    '/',
    '/login',
    '/static/css/style.css',
    '/static/js/app.js',
    '/static/icons/icon-192.png',
    '/static/icons/icon-512.png',
    '/static/icons/apple-touch-icon.png',
    '/static/icons/favicon.png',
    'https://unpkg.com/lucide@latest',
    'https://cdn.plot.ly/plotly-2.27.0.min.js',
    'https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;700&display=swap'
];

// Install: Cache essential assets
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            console.log('[ServiceWorker] Pre-caching core assets');
            return cache.addAll(PRECACHE_ASSETS).catch((err) => {
                console.warn('[ServiceWorker] Pre-cache non-fatal warning:', err);
            });
        })
    );
    self.skipWaiting();
});

// Activate: Clean up old caches
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames.map((cache) => {
                    if (cache !== CACHE_NAME) {
                        console.log('[ServiceWorker] Clearing old cache:', cache);
                        return caches.delete(cache);
                    }
                })
            );
        })
    );
    self.clients.claim();
});

// Fetch strategy:
// - Network-first for dynamic API routes (/api/*)
// - Cache-first with network fallback for static assets
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // Skip caching non-GET or API endpoints
    if (event.request.method !== 'GET' || url.pathname.startsWith('/api/')) {
        return;
    }

    event.respondWith(
        caches.match(event.request).then((cachedResponse) => {
            if (cachedResponse) {
                // Return cached asset and update in background
                fetch(event.request).then((networkResponse) => {
                    if (networkResponse && networkResponse.status === 200) {
                        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, networkResponse));
                    }
                }).catch(() => {});
                return cachedResponse;
            }

            return fetch(event.request).then((response) => {
                if (!response || response.status !== 200 || response.type === 'opaque') {
                    return response;
                }
                const responseToCache = response.clone();
                caches.open(CACHE_NAME).then((cache) => {
                    cache.put(event.request, responseToCache);
                });
                return response;
            }).catch(() => {
                // If offline and requesting an HTML page, return cached root or login
                if (event.request.headers.get('accept').includes('text/html')) {
                    return caches.match('/');
                }
            });
        })
    );
});
