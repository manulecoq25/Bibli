// Bibli service worker: shell + catalogue cached on install, book parts cached as they are read.
const V='bibli-v3';
const SHELL=['./','index.html','manifest.json','icon.svg','data/catalogue.json','data/shelves.json','data/blog.json','data/editorial.json'];
self.addEventListener('install',e=>{e.waitUntil(caches.open(V).then(c=>c.addAll(SHELL)).then(()=>self.skipWaiting()))});
self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==V).map(k=>caches.delete(k)))).then(()=>self.clients.claim()))});
self.addEventListener('fetch',e=>{
  const u=new URL(e.request.url);if(e.request.method!=='GET'||u.origin!==location.origin)return;
  // catalogue & shell: network first (fresh), fall back to cache (offline)
  if(u.pathname.endsWith('catalogue.json')||u.pathname.endsWith('index.html')||u.pathname.endsWith('/')){
    e.respondWith(fetch(e.request).then(r=>{caches.open(V).then(c=>c.put(e.request,r.clone()));return r}).catch(()=>caches.match(e.request)));return}
  // book parts & assets: cache first
  e.respondWith(caches.match(e.request).then(h=>h||fetch(e.request).then(r=>{if(r.ok)caches.open(V).then(c=>c.put(e.request,r.clone()));return r})));
});
