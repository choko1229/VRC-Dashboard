// フレンド詳細（モーダル/フルページ共通）のタブ切替。
// 実際のタブ内容はHTMXで #friend-detail-tab-content のみを差し替えるため、
// タブボタン自体の見た目（active状態）はここでクリック時に切り替える。
(function () {
    document.body.addEventListener("click", function (evt) {
        var tab = evt.target.closest(".detail-tab");
        if (!tab) {
            return;
        }
        var bar = tab.closest(".detail-tabs");
        if (!bar) {
            return;
        }
        bar.querySelectorAll(".detail-tab").forEach(function (btn) {
            btn.classList.remove("active");
        });
        tab.classList.add("active");
    });
})();
