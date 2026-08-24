// アバター一覧テーブルの行メニュー（詳細/タグ/名前変更/説明変更/公開状態切り替え）。
(function () {
    // メニュー外クリックで閉じる
    document.addEventListener("click", (event) => {
        document.querySelectorAll(".avatar-row-menu[open]").forEach((menu) => {
            if (!menu.contains(event.target)) {
                menu.removeAttribute("open");
            }
        });
    });

    document.addEventListener("click", (event) => {
        const renameBtn = event.target.closest("[data-avatar-rename]");
        if (renameBtn) {
            const id = renameBtn.dataset.avatarRename;
            const current = renameBtn.dataset.currentName || "";
            renameBtn.closest(".avatar-row-menu")?.removeAttribute("open");
            const name = window.prompt("新しいアバター名を入力してください（VRChat本体のデータが変更されます）", current);
            if (name !== null && name.trim() && name.trim() !== current) {
                window.htmx.ajax("POST", `/avatars/${id}/rename`, {
                    values: { name: name.trim() },
                    target: `#avatar-row-${id}`,
                    swap: "outerHTML",
                });
            }
            return;
        }

        const descBtn = event.target.closest("[data-avatar-description]");
        if (descBtn) {
            const id = descBtn.dataset.avatarDescription;
            const current = descBtn.dataset.currentDescription || "";
            descBtn.closest(".avatar-row-menu")?.removeAttribute("open");
            const description = window.prompt(
                "新しい説明文を入力してください（VRChat本体のデータが変更されます。空欄で削除）",
                current
            );
            if (description !== null && description !== current) {
                window.htmx.ajax("POST", `/avatars/${id}/description`, {
                    values: { description },
                    target: `#avatar-row-${id}`,
                    swap: "outerHTML",
                });
            }
        }
    });

    // 公開状態切り替え等、hx-post付きボタンをクリックしたらメニューを閉じる
    document.body.addEventListener("htmx:afterRequest", (event) => {
        const menu = event.target.closest && event.target.closest(".avatar-row-menu");
        if (menu) {
            menu.removeAttribute("open");
        }
    });
})();
