/* Kairo – Offline-Fähigkeit: immer zuerst das Netz (aktuelle Daten), bei Funkloch die zuletzt geladene Version. */
const CACHE = "kairo-v1";
self.addEventListener("install", e => { self.skipWaiting(); e.waitUntil(caches.open(CACHE).then(c => c.addAll(["./", "index.html", "splash.css", "splash.js", "lib/lightweight-charts.standalone.production.js", "icon-192.png"]).catch(() => {}))); });
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin) return;
  e.respondWith(fetch(e.request).then(r => {
    if (r.ok) { const copy = r.clone(); caches.open(CACHE).then(c => c.put(e.request, copy)).catch(() => {}); }
    return r;
  }).catch(() => caches.match(e.request, { ignoreSearch: true }).then(r => r || caches.match("index.html"))));
});

/* Mitteilungen (Web Push) – kommen nach dem Abendscan, auch wenn die App geschlossen ist (iPadOS ab 16.4, Home-Bildschirm) */
self.addEventListener("push", e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (err) { d = { title: "Kairo", body: e.data && e.data.text() }; }
  e.waitUntil(self.registration.showNotification(d.title || "Kairo", {
    body: d.body || "", icon: "icon-192.png", badge: "icon-192.png", tag: d.tag || "kairo", renotify: true, data: { url: d.url || "./" }
  }));
});
self.addEventListener("notificationclick", e => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "./";
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(list => {
    for (const c of list) if ("focus" in c) { c.navigate ? c.navigate(url).catch(() => {}) : 0; return c.focus(); }
    return self.clients.openWindow(url);
  }));
});
