// フレンドカードのクリックで/friends/{id}へ遷移する代わりに、
// /friends/{id}/modal の内容をモーダルダイアログに読み込んで表示する。
(function () {
    var MODAL_ID = "friend-modal";
    var BODY_ID = "friend-modal-body";

    function openModal() {
        var modal = document.getElementById(MODAL_ID);
        if (modal) {
            modal.classList.add("open");
        }
    }

    window.closeFriendModal = function () {
        var modal = document.getElementById(MODAL_ID);
        var body = document.getElementById(BODY_ID);
        if (modal) {
            modal.classList.remove("open");
        }
        if (body) {
            body.innerHTML = "";
        }
    };

    document.body.addEventListener("htmx:beforeRequest", function (evt) {
        var target = evt.detail.target;
        if (target && target.id === BODY_ID) {
            target.innerHTML = '<p class="placeholder">読み込み中...</p>';
            openModal();
        }
    });

    document.addEventListener("keydown", function (evt) {
        if (evt.key === "Escape") {
            window.closeFriendModal();
        }
    });

    document.addEventListener("click", function (evt) {
        if (evt.target && evt.target.id === MODAL_ID) {
            window.closeFriendModal();
        }
    });
})();
