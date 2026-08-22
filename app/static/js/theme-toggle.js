// ダークモード: OS設定(prefers-color-scheme)への初回連動 + 手動トグルでの上書き。
// 手動選択はlocalStorageと、SSR側が初回描画時に参照できるようCookieの両方に保存する。
(function () {
    const STORAGE_KEY = "vrc-dashboard-theme"; // "light" | "dark" | "auto"
    const COOKIE_NAME = "theme_preference";

    function applyTheme(preference) {
        const root = document.documentElement;
        if (preference === "auto") {
            root.removeAttribute("data-theme");
        } else {
            root.setAttribute("data-theme", preference);
        }
    }

    function getStoredPreference() {
        return localStorage.getItem(STORAGE_KEY) || "auto";
    }

    window.setThemePreference = function (preference) {
        localStorage.setItem(STORAGE_KEY, preference);
        document.cookie = `${COOKIE_NAME}=${preference}; path=/; max-age=31536000; samesite=lax`;
        applyTheme(preference);
    };

    // ナビゲーションのテーマ切替ボタン用: auto → light → dark → auto の順に循環する。
    window.cycleTheme = function () {
        const order = ["auto", "light", "dark"];
        const current = getStoredPreference();
        const next = order[(order.indexOf(current) + 1) % order.length];
        window.setThemePreference(next);
    };

    applyTheme(getStoredPreference());
})();
