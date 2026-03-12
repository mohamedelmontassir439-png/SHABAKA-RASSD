const CACHE = 'mb-v1';
const OFFLINE = ['/', '/tenders', '/pricing'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(OFFLINE).catch(()=>{})));
  self.skipWaiting();
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))));
  self.clients.claim();
});
self.addEventListener('fetch', e => {
  if(e.request.method!=='GET'||e.request.url.includes('/admin')||e.request.url.includes('/api')) return;
  e.respondWith(fetch(e.request).then(r=>{
    if(r&&r.status===200&&r.type==='basic'){const c=r.clone();caches.open(CACHE).then(cache=>cache.put(e.request,c));}
    return r;
  }).catch(()=>caches.match(e.request)));
});
