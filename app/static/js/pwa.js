// PWA共通処理: 全ページでService Workerを登録する(オフラインキャッシュ + Web Push受信用)。
(function () {
    if (!("serviceWorker" in navigator)) {
        return;
    }
    // scope="/" にするため、静的ファイル配信下ではなくルートパスで登録する。
    navigator.serviceWorker.register("/sw.js", { scope: "/" });
})();
