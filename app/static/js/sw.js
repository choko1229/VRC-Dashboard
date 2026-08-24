// PWAのService Worker: 静的アセットのオフラインキャッシュ + Web Push受信。

const CACHE_NAME = "vrc-dashboard-static-v1";
const STATIC_ASSETS = [
    "/static/css/tokens.css",
    "/static/css/base.css",
    "/static/js/htmx.min.js",
    "/static/js/theme-toggle.js",
    "/static/js/pwa.js",
    "/static/icons/icon-192.png",
    "/static/icons/icon-512.png",
    "/static/fonts/LINESeedJP_OTF_Rg.woff2",
    "/static/fonts/LINESeedJP_OTF_Bd.woff2",
    "/static/offline.html",
];

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches
            .open(CACHE_NAME)
            .then((cache) => cache.addAll(STATIC_ASSETS))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches
            .keys()
            .then((keys) =>
                Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
            )
            .then(() => self.clients.claim())
    );
});

self.addEventListener("fetch", (event) => {
    const { request } = event;
    if (request.method !== "GET") {
        return;
    }
    const url = new URL(request.url);
    if (url.origin !== self.location.origin) {
        return;
    }

    // 静的アセット: キャッシュ優先（無ければ取得してキャッシュに追加）
    if (url.pathname.startsWith("/static/")) {
        event.respondWith(
            caches.match(request).then((cached) => {
                if (cached) {
                    return cached;
                }
                return fetch(request).then((response) => {
                    if (response.ok) {
                        const clone = response.clone();
                        caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
                    }
                    return response;
                });
            })
        );
        return;
    }

    // ページ遷移: フレンド状況等はリアルタイム性が重要なため常にネットワークから取得し、
    // オフライン時のみフォールバックページを表示する（HTMLはキャッシュしない）。
    if (request.mode === "navigate") {
        event.respondWith(fetch(request).catch(() => caches.match("/static/offline.html")));
    }
});

self.addEventListener("push", (event) => {
    let payload = { title: "VRC事前確認ダッシュボード", body: "", url: "/" };
    if (event.data) {
        try {
            payload = { ...payload, ...event.data.json() };
        } catch {
            payload.body = event.data.text();
        }
    }

    event.waitUntil(
        self.registration.showNotification(payload.title || "VRC事前確認ダッシュボード", {
            body: payload.body || "",
            icon: "/static/icons/icon-192.png",
            badge: "/static/icons/icon-192.png",
            data: { url: payload.url || "/" },
        })
    );
});

self.addEventListener("notificationclick", (event) => {
    event.notification.close();
    const targetUrl = new URL(event.notification.data?.url || "/", self.location.origin).href;

    event.waitUntil(
        self.clients.matchAll({ type: "window" }).then((clientList) => {
            for (const client of clientList) {
                if (client.url === targetUrl && "focus" in client) {
                    return client.focus();
                }
            }
            for (const client of clientList) {
                if ("focus" in client && "navigate" in client) {
                    return client.focus().then(() => client.navigate(targetUrl));
                }
            }
            if (self.clients.openWindow) {
                return self.clients.openWindow(targetUrl);
            }
        })
    );
});
