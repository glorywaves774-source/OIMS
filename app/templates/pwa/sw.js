/* ZENTAVA OIMS service worker: makes the app installable and shows a friendly page when offline.
   Privacy: only the public look of the app is kept (styles, scripts, icons, fonts, the offline page).
   Pages, records, downloads and anything sent to the server always go straight to the network. */
"use strict";
var VERSION = {{ version|tojson }};
var CACHE = "zentava-" + VERSION;
var OFFLINE = {{ offline|tojson }};
var ASSETS = {{ assets|tojson }};

function keep(cache, url) {
  return fetch(new Request(url, { cache: "reload", credentials: "same-origin" })).then(function (r) {
    if (!r.ok || r.redirected || r.type !== "basic") throw new Error("Not kept: " + url);
    return cache.put(url, r);
  });
}

self.addEventListener("install", function (event) {
  event.waitUntil(caches.open(CACHE).then(function (cache) {
    return Promise.all([OFFLINE].concat(ASSETS).map(function (u) { return keep(cache, u); }));
  }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener("activate", function (event) {
  event.waitUntil(caches.keys().then(function (names) {
    return Promise.all(names.filter(function (n) { return n.indexOf("zentava-") === 0 && n !== CACHE; })
      .map(function (n) { return caches.delete(n); }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener("fetch", function (event) {
  var req = event.request;
  if (req.method !== "GET") return;
  var url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  if (req.mode === "navigate") {
    // Always the live page; the offline page only when there is no connection at all.
    event.respondWith(fetch(req).catch(function () {
      return caches.match(OFFLINE).then(function (r) {
        return r || new Response("You are offline.", { status: 503, headers: { "Content-Type": "text/plain" } });
      });
    }));
    return;
  }

  if (url.pathname.indexOf("/static/") === 0) {
    // Styles, scripts, icons and fonts: show the kept copy at once, refresh it in the background.
    event.respondWith(caches.open(CACHE).then(function (cache) {
      return cache.match(req).then(function (kept) {
        var fresh = fetch(req).then(function (r) {
          if (r.ok && r.type === "basic" && !r.redirected) cache.put(req, r.clone());
          return r;
        });
        if (kept) { event.waitUntil(fresh.catch(function () {})); return kept; }
        return fresh;
      });
    }));
  }
  // Everything else (pages' data, logos, documents, exports) is not touched.
});
