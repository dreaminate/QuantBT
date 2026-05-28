/**
 * v0.9.9 · QuantBT Service Worker (minimal)
 *
 * 策略:
 *  - 静态资源 (js/css/svg/png) → cache-first，离线可读
 *  - API 调用 (/api/*) → network-first，不缓存（金融数据必须实时）
 *  - HTML 文档 → network-first 兜底 cache（离线还能看 shell）
 *
 * 不缓存:
 *  - 任何 secrets / keystore / 交易相关 endpoint
 *  - POST/PUT/DELETE 全部 bypass
 */

const CACHE_NAME = "qb-static-v1";
const CORE_ASSETS = ["/", "/manifest.webmanifest", "/icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((c) => c.addAll(CORE_ASSETS).catch(() => null)),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))),
    ),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // 只处理同源
  if (url.origin !== self.location.origin) return;

  // 非 GET 直接走网络（POST 交易类绝不缓存）
  if (req.method !== "GET") return;

  // /api/* 走 network-first 不缓存
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(fetch(req));
    return;
  }

  // 静态资源 cache-first
  if (
    url.pathname.match(/\.(js|css|svg|png|jpg|webp|woff2?|ttf|webmanifest)$/) ||
    url.pathname === "/" ||
    url.pathname.startsWith("/assets/")
  ) {
    event.respondWith(
      caches.match(req).then((cached) => {
        if (cached) {
          // 后台静默刷新
          fetch(req)
            .then((resp) => {
              if (resp && resp.ok) caches.open(CACHE_NAME).then((c) => c.put(req, resp.clone()));
            })
            .catch(() => null);
          return cached;
        }
        return fetch(req).then((resp) => {
          if (resp && resp.ok) {
            const copy = resp.clone();
            caches.open(CACHE_NAME).then((c) => c.put(req, copy));
          }
          return resp;
        });
      }),
    );
    return;
  }

  // HTML 文档 network-first
  if (req.headers.get("accept")?.includes("text/html")) {
    event.respondWith(
      fetch(req)
        .then((resp) => {
          if (resp && resp.ok) {
            const copy = resp.clone();
            caches.open(CACHE_NAME).then((c) => c.put(req, copy));
          }
          return resp;
        })
        .catch(() => caches.match(req).then((cached) => cached || caches.match("/"))),
    );
  }
});
