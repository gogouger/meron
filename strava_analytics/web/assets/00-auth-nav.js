/**
 * Render the auth slot in the navbar.
 *
 * Hits /api/auth/me to see if there's a logged-in user. If so, shows
 * "<username> · logout"; otherwise shows "login". Re-runs on navigation
 * so the slot stays in sync after login/signup redirects.
 *
 * The slot itself (<span id="nav-auth-slot">) is rendered by Dash in
 * app.py. This file only manipulates its innerHTML.
 */
(function () {
    function renderSlot() {
        var slot = document.getElementById("nav-auth-slot");
        var gear = document.getElementById("nav-settings-gear");
        if (!slot) return;
        fetch("/api/auth/me", {credentials: "same-origin"})
            .then(function (resp) {
                if (resp.ok) {
                    return resp.json().then(function (body) {
                        var name = body.username || "account";
                        slot.innerHTML =
                            '<span style="opacity:0.6">' + escape(name) + '</span>' +
                            '  <a href="#" data-meron-logout ' +
                            'style="color:inherit;text-decoration:underline;">logout</a>';
                        if (gear) gear.style.display = "";
                    });
                }
                // Anonymous: empty auth slot, gear stays hidden.
                slot.innerHTML = "";
                if (gear) gear.style.display = "none";
            })
            .catch(function () {
                slot.innerHTML = "";
                if (gear) gear.style.display = "none";
            });
    }

    function escape(s) {
        return String(s).replace(/[&<>"']/g, function (c) {
            return ({"&": "&amp;", "<": "&lt;", ">": "&gt;",
                     "\"": "&quot;", "'": "&#39;"})[c];
        });
    }

    // Single delegated click listener — works even after re-renders.
    document.addEventListener("click", function (ev) {
        var target = ev.target.closest("[data-meron-logout]");
        if (!target) return;
        ev.preventDefault();
        fetch("/api/auth/logout", {
            method: "POST", credentials: "same-origin",
        }).finally(function () { window.location.href = "/"; });
    });

    // Run on initial load and whenever Dash swaps the page (the slot is
    // part of the static layout, so usually only one render, but MO
    // covers page-replace edge cases).
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", renderSlot);
    } else {
        renderSlot();
    }
    new MutationObserver(function (muts) {
        for (var i = 0; i < muts.length; i++) {
            if (muts[i].addedNodes.length) {
                var slot = document.getElementById("nav-auth-slot");
                if (slot && !slot.dataset.meronAuthRendered) {
                    slot.dataset.meronAuthRendered = "1";
                    renderSlot();
                }
            }
        }
    }).observe(document.body, {childList: true, subtree: true});
})();
