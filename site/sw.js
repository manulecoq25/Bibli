// Itanva service worker: app shell + light index cached on install; book parts cached as they are read.
const V='itanva-v5';
const SHELL=['./','index.html','css/app.css','js/app.js','manifest.json','icon.svg','data/index.json','data/shelves.json','data/editorial.json','data/archives.json'];
self.addEventListener('install',e=>{e.waitUntil(caches.open(V).then(c=>c.addAll(SHELL)).then(()=>self.skipWaiting()))});
self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==V).map(k=>caches.delete(k)))).then(()=>self.clients.claim()))});
self.addEventListener('fetch',e=>{
  const u=new URL(e.request.url);if(e.request.method!=='GET'||u.origin!==location.origin)return;
  const p=u.pathname;
  // shell, index, editorial: network first (fresh), cache fallback (offline)
  if(/\/(index\.html|css\/app\.css|js\/app\.js|data\/(index|shelves|editorial|blog)\.json)$/.test(p)||p.endsWith('/')){
    e.respondWith(fetch(e.request).then(r=>{caches.open(V).then(c=>c.put(e.request,r.clone()));return r}).catch(()=>caches.match(e.request).then(h=>h||caches.match('./'))));return}
  // book parts, meta, samples, covers, fonts: cache first
  e.respondWith(caches.match(e.request).then(h=>h||fetch(e.request).then(r=>{if(r.ok)caches.open(V).then(c=>c.put(e.request,r.clone()));return r})));
});
