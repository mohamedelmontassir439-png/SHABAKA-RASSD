const CACHE = "mb3-v1";
const STATIC = ["/","/marketplace","/annuaire","/contact"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(STATIC).catch(()=>{})));
  self.skipWaiting();
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))
  ));
  self.clients.claim();
});
self.addEventListener("fetch", e => {
  if(e.request.method!=="GET") return;
  const url = e.request.url;
  if(url.includes("/admin")||url.includes("/api/")||url.includes("sw.js")) return;
  e.respondWith(
    fetch(e.request).then(resp=>{
      if(resp&&resp.status===200&&resp.type==="basic"){
        const c=resp.clone();
        caches.open(CACHE).then(ca=>ca.put(e.request,c));
      }
      return resp;
    }).catch(()=>caches.match(e.request))
  );
});
self.addEventListener("push", e=>{
  if(!e.data) return;
  const d = e.data.json();
  e.waitUntil(self.registration.showNotification(d.title||"Modern Business",{
    body:d.body||"Nouveau marché disponible",
    icon:"/static/icon-192.png",
    badge:"/static/icon-192.png",
    tag:d.tag||"mb-notif",
    data:{url:d.url||"/"}
  }));
});
self.addEventListener("notificationclick",e=>{
  e.notification.close();
  e.waitUntil(clients.openWindow(e.notification.data.url||"/"));
});
