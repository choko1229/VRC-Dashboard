// サイドバーのフレンド一覧は15秒ごとにHTMXでinnerHTML全体を差し替えるため、
// そのままだとユーザーが折りたたんだ<details>の開閉状態が毎回リセットされてしまう。
// スワップ前後で開閉状態を引き継ぐことで、折りたたみ操作を維持する。
(function () {
    var CONTAINER_ID = "friends-sidebar-content";

    function captureOpenState(container) {
        var state = {};
        container.querySelectorAll("details[id]").forEach(function (details) {
            state[details.id] = details.open;
        });
        return state;
    }

    function restoreOpenState(container, state) {
        container.querySelectorAll("details[id]").forEach(function (details) {
            if (Object.prototype.hasOwnProperty.call(state, details.id)) {
                details.open = state[details.id];
            }
        });
    }

    document.body.addEventListener("htmx:beforeSwap", function (evt) {
        var target = evt.detail.target;
        if (target && target.id === CONTAINER_ID) {
            target._sidebarOpenState = captureOpenState(target);
        }
    });

    document.body.addEventListener("htmx:afterSwap", function (evt) {
        var target = evt.detail.target;
        if (target && target.id === CONTAINER_ID && target._sidebarOpenState) {
            restoreOpenState(target, target._sidebarOpenState);
        }
    });
})();
