/**
 * Meron auth nav — single source of truth for "is anyone signed in?"
 *
 * Hits the same-origin Authelia proxy (/__authstate, served by Caddy on
 * meron.ggouger.localhost) to read the SSO session and reflects it onto
 * the DOM as `body[data-auth="user"]` vs `body[data-auth="anon"]`. CSS
 * then hides protected nav links and CTA buttons for anonymous visitors.
 *
 * If /__authstate is unreachable (running outside the Caddy stack, e.g.
 * bare `python -m strava_analytics.web`), falls back to Meron's own
 * cookie-session endpoint /api/auth/me — older standalone behaviour.
 *
 * Clicking the navbar "log in" link, or any .protected link while anon,
 * opens an inline login modal that POSTs to /__authlogin (Authelia's
 * /api/firstfactor). On success we reload to the original target. This
 * mirrors the personal-site pattern in site.js so the user never has to
 * leave the Meron domain to authenticate.
 */
(function () {
    "use strict";

    var STATE = { authed: false, username: "", inlineActive: false };

    function setBodyAuth(authed) {
        document.body.setAttribute("data-auth", authed ? "user" : "anon");
    }

    function escapeHTML(s) {
        return String(s).replace(/[&<>"']/g, function (c) {
            return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;",
                     "\"": "&quot;", "'": "&#39;" })[c];
        });
    }

    function renderSlot() {
        var slot = document.getElementById("nav-auth-slot");
        var gear = document.getElementById("nav-settings-gear");
        if (!slot) return;
        if (STATE.authed) {
            var name = STATE.username || "account";
            slot.innerHTML =
                '<span style="opacity:0.6">' + escapeHTML(name) + '</span>' +
                '  <a href="#" data-meron-logout ' +
                'style="color:inherit;text-decoration:underline;">logout</a>';
            if (gear) gear.style.display = "";
        } else {
            slot.innerHTML =
                '<a href="#" data-meron-login ' +
                'style="color:inherit;">log in</a>';
            if (gear) gear.style.display = "none";
        }
    }

    // Hit the Authelia same-origin proxy (canonical SSO). Falls back to
    // Meron's own /api/auth/me when outside the Caddy stack.
    function refresh() {
        return fetch("/__authstate", {
            credentials: "include",
            headers: { "Accept": "application/json" },
        })
        .then(function (r) { if (!r.ok) throw 0; return r.json(); })
        .then(function (s) {
            STATE.inlineActive = true;
            var d = (s && s.data) || {};
            STATE.authed = (d.authentication_level || 0) >= 1;
            STATE.username = d.username || "";
            setBodyAuth(STATE.authed);
            renderSlot();
        })
        .catch(function () {
            // /__authstate unreachable — try Meron's own session as a fallback.
            return fetch("/api/auth/me", { credentials: "same-origin" })
                .then(function (r) {
                    if (!r.ok) throw 0;
                    return r.json();
                })
                .then(function (body) {
                    STATE.authed = true;
                    STATE.username = body.username || "";
                    setBodyAuth(true);
                    renderSlot();
                })
                .catch(function () {
                    STATE.authed = false;
                    STATE.username = "";
                    setBodyAuth(false);
                    renderSlot();
                });
        });
    }

    // ── Inline login modal ────────────────────────────────────────────
    var modal = null, pendingHref = null;

    function buildModal() {
        if (modal) return modal;
        modal = document.createElement("div");
        modal.className = "meron-login-modal";
        modal.style.cssText = "position:fixed;inset:0;z-index:1000;display:none;align-items:center;justify-content:center;padding:20px;background:rgba(8,10,9,.55);-webkit-backdrop-filter:blur(2px);backdrop-filter:blur(2px);";
        modal.innerHTML =
            '<div class="meron-login-card" role="dialog" aria-modal="true" aria-label="Log in">' +
                '<button class="meron-login-x" type="button" aria-label="Close">×</button>' +
                '<div class="meron-login-title">Sign in</div>' +
                '<p class="meron-login-sub">One login for the site, Meron &amp; Books.</p>' +
                '<form class="meron-login-form" novalidate>' +
                    '<div class="meron-login-field"><label for="mlm-user">Username</label>' +
                        '<input id="mlm-user" name="username" autocomplete="username" autocapitalize="off" spellcheck="false" required></div>' +
                    '<div class="meron-login-field"><label for="mlm-pass">Password</label>' +
                        '<input id="mlm-pass" name="password" type="password" autocomplete="current-password" required></div>' +
                    '<p class="meron-login-err" role="alert" hidden></p>' +
                    '<button class="meron-login-submit" type="submit">Sign in</button>' +
                '</form>' +
            '</div>';
        document.body.appendChild(modal);

        // Inline styling for the card chrome — theme-aware via CSS vars so
        // the overlay renders correctly even when custom.css hasn't loaded.
        var card = modal.querySelector(".meron-login-card");
        card.style.cssText = "position:relative;width:100%;max-width:360px;background:var(--bg-card,#fff);color:var(--foreground,#111);border:1px solid var(--border,#ddd);border-radius:8px;padding:28px 28px 24px;box-shadow:0 18px 50px rgba(0,0,0,.30);font-family:inherit;";
        modal.querySelector(".meron-login-x").style.cssText = "position:absolute;top:8px;right:10px;background:none;border:0;color:var(--muted,#888);font-size:22px;line-height:1;cursor:pointer;padding:2px 7px;";
        modal.querySelector(".meron-login-title").style.cssText = "font-size:20px;font-weight:700;letter-spacing:-0.01em;margin:0 0 4px;";
        modal.querySelector(".meron-login-sub").style.cssText = "color:var(--muted,#888);font-size:12.5px;margin:0 0 20px;";

        var form = modal.querySelector(".meron-login-form");
        var err = modal.querySelector(".meron-login-err");
        err.style.cssText = "color:#d9534f;font-size:12.5px;margin:0 0 12px;";

        // Style fields + submit button to match Meron's flat input look.
        var fields = modal.querySelectorAll(".meron-login-field");
        for (var i = 0; i < fields.length; i++) {
            fields[i].style.cssText = "margin-bottom:14px;";
            var lbl = fields[i].querySelector("label");
            lbl.style.cssText = "display:block;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.08em;color:var(--muted,#888);margin-bottom:6px;";
            var inp = fields[i].querySelector("input");
            inp.style.cssText = "width:100%;font-family:var(--font-mono,monospace);font-size:14px;padding:10px 12px;border:1px solid var(--border,#ddd);border-radius:4px;background:transparent;color:inherit;outline:none;box-sizing:border-box;";
        }
        var sBtn = form.querySelector(".meron-login-submit");
        sBtn.style.cssText = "width:100%;padding:12px 24px;font-size:14px;font-weight:600;background:var(--accent,#1a8a77);color:#fff;border:0;border-radius:4px;cursor:pointer;margin-top:4px;font-family:inherit;";

        function close() {
            modal.style.display = "none";
            pendingHref = null;
            err.hidden = true;
            form.reset();
        }
        modal.addEventListener("mousedown", function (e) {
            if (e.target === modal) close();
        });
        modal.querySelector(".meron-login-x").addEventListener("click", close);
        document.addEventListener("keydown", function (e) {
            if (e.key === "Escape" && modal.style.display === "flex") close();
        });

        form.addEventListener("submit", function (e) {
            e.preventDefault();
            err.hidden = true;
            sBtn.disabled = true;
            sBtn.textContent = "Signing in…";
            fetch("/__authlogin", {
                method: "POST",
                credentials: "include",
                headers: {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                body: JSON.stringify({
                    username: form.username.value,
                    password: form.password.value,
                    keepMeLoggedIn: true,
                    requestMethod: "GET",
                    targetURL: pendingHref || location.href,
                }),
            })
            .then(function (r) {
                return r.json().then(function (j) {
                    return { ok: r.ok, j: j };
                });
            })
            .then(function (res) {
                if (res.ok && res.j && res.j.status === "OK") {
                    // Authelia issued a cookie. Go to pendingHref (the link
                    // they clicked) or just reload the current page so the
                    // navbar reflects the new state.
                    location.href = pendingHref || location.pathname + location.search;
                    return;
                }
                throw new Error(
                    (res.j && res.j.message) || "Invalid username or password"
                );
            })
            .catch(function (e2) {
                err.textContent = (e2 && e2.message) || "Login failed";
                err.hidden = false;
            })
            .finally(function () {
                sBtn.disabled = false;
                sBtn.textContent = "Sign in";
            });
        });

        return modal;
    }

    function openModal(href) {
        if (!STATE.inlineActive) {
            // No Authelia proxy → fall back to Meron's own /login page.
            location.href = "/login";
            return;
        }
        pendingHref = href || null;
        var m = buildModal();
        m.style.display = "flex";
        setTimeout(function () {
            var u = modal.querySelector("#mlm-user");
            if (u) u.focus();
        }, 30);
    }

    function logout() {
        // Prefer Authelia (the canonical SSO); also clear Meron's own
        // session cookie as belt-and-suspenders for the standalone case.
        fetch("/__authlogout", {
            method: "POST",
            credentials: "include",
            headers: { "Accept": "application/json" },
        })
        .catch(function () { /* ignore — fallback below covers it */ })
        .finally(function () {
            fetch("/api/auth/logout", {
                method: "POST",
                credentials: "same-origin",
            }).finally(function () { location.href = "/"; });
        });
    }

    // ── Global click handler ─────────────────────────────────────────
    // Delegated so it works through Dash page-swaps.
    document.addEventListener("click", function (ev) {
        var logoutEl = ev.target.closest("[data-meron-logout]");
        if (logoutEl) {
            ev.preventDefault();
            logout();
            return;
        }
        var loginEl = ev.target.closest("[data-meron-login]");
        if (loginEl) {
            ev.preventDefault();
            openModal(null);
            return;
        }
        // Anon clicking a protected nav link → open modal first.
        if (!STATE.authed) {
            var prot = ev.target.closest(".meron-nav-link.protected, .auth-only a, a.auth-only");
            if (prot && prot.getAttribute("href")) {
                ev.preventDefault();
                openModal(prot.href);
                return;
            }
        }
    });

    // Run on initial load.
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () {
            setBodyAuth(false); // start anon to avoid flash-of-protected
            refresh();
        });
    } else {
        setBodyAuth(false);
        refresh();
    }

    // Dash swaps the page-container without firing a full navigation;
    // re-render the slot whenever the navbar's auth slot appears.
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
    }).observe(document.body, { childList: true, subtree: true });
})();
