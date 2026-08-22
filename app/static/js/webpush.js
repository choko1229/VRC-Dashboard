// ブラウザ通知(Web Push)の購読/解除UI。
(function () {
    const statusEl = document.getElementById("webpush-status");
    const toggleBtn = document.getElementById("webpush-toggle-btn");

    function urlBase64ToUint8Array(base64String) {
        const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
        const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
        const rawData = window.atob(base64);
        return Uint8Array.from([...rawData].map((c) => c.charCodeAt(0)));
    }

    async function getExistingSubscription() {
        const registration = await navigator.serviceWorker.ready;
        return registration.pushManager.getSubscription();
    }

    async function subscribe() {
        const registration = await navigator.serviceWorker.ready;
        const keyResponse = await fetch("/webpush/vapid-public-key");
        const { publicKey } = await keyResponse.json();

        const subscription = await registration.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array(publicKey),
        });

        await fetch("/webpush/subscribe", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(subscription.toJSON()),
        });
    }

    async function unsubscribe(subscription) {
        await fetch("/webpush/subscribe", {
            method: "DELETE",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ endpoint: subscription.endpoint }),
        });
        await subscription.unsubscribe();
    }

    async function refreshUI() {
        if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
            statusEl.textContent = "このブラウザはWeb Pushに対応していません。";
            toggleBtn.style.display = "none";
            return;
        }

        const subscription = await getExistingSubscription();
        if (subscription) {
            statusEl.textContent = "ブラウザ通知は有効です。";
            toggleBtn.textContent = "通知を無効にする";
            toggleBtn.onclick = async () => {
                toggleBtn.disabled = true;
                await unsubscribe(subscription);
                await refreshUI();
            };
        } else {
            statusEl.textContent = "ブラウザ通知は無効です。";
            toggleBtn.textContent = "通知を有効にする";
            toggleBtn.onclick = async () => {
                toggleBtn.disabled = true;
                try {
                    await subscribe();
                } catch (err) {
                    statusEl.textContent = "通知の許可が得られませんでした。";
                }
                await refreshUI();
            };
        }
        toggleBtn.disabled = false;
    }

    if ("serviceWorker" in navigator) {
        // scope="/" にするため、静的ファイル配信下ではなくルートパスで登録する。
        navigator.serviceWorker.register("/sw.js", { scope: "/" }).then(refreshUI);
    } else {
        refreshUI();
    }
})();
