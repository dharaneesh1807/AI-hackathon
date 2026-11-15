// Cache only the public app shell. Never cache API responses, tokens or shared records.
const CACHE='eldercare-shell-v1';
const SHELL=['/assets/offline.html','/assets/style.css','/assets/icon-192.png','/assets/icon-512.png'];
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(SHELL)).then(()=>self.skipWaiting())));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('eldercare-shell-')&&k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',e=>{const u=new URL(e.request.url);if(e.request.method!=='GET'||u.origin!==self.location.origin)return;if(e.request.mode==='navigate'&&u.pathname==='/'){e.respondWith(fetch(e.request).catch(()=>caches.match('/assets/offline.html')));return}if(SHELL.includes(u.pathname)){e.respondWith(fetch(e.request).catch(()=>caches.match(u.pathname)))}});
