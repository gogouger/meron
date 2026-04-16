/**
 * Page-transition UX for Dash multi-page navigation.
 *
 *   - Scrolls to top on path change.
 *   - Shows a MERON pulse overlay while the new page renders (some pages
 *     do heavy pandas work server-side and can take a couple seconds).
 *   - Hides the overlay as soon as new DOM content lands after the path
 *     change, with a 5-second safety timeout so the overlay can never
 *     trap the UI if something goes wrong.
 */
(function () {
    "use strict";

    var lastPath = window.location.pathname;
    var overlay = null;
    var safetyTimer = null;
    var navPending = false;

    function ensureOverlay() {
        if (overlay) return overlay;
        overlay = document.createElement("div");
        overlay.id = "meron-page-loading";
        overlay.innerHTML = '<div class="meron-page-loading__mark"></div>';
        overlay.setAttribute("aria-hidden", "true");
        document.body.appendChild(overlay);
        return overlay;
    }

    function showLoading() {
        var el = ensureOverlay();
        el.classList.add("is-visible");
        navPending = true;
        clearTimeout(safetyTimer);
        // Safety: hide overlay after 5s even if the mutation trigger never fires
        safetyTimer = setTimeout(hideLoading, 5000);
    }

    function hideLoading() {
        if (overlay) overlay.classList.remove("is-visible");
        clearTimeout(safetyTimer);
        navPending = false;
    }

    function onPageSwap() {
        var currentPath = window.location.pathname;
        if (currentPath !== lastPath) {
            lastPath = currentPath;
            window.scrollTo(0, 0);
            // New page content has landed — hide the loading overlay.
            // Small delay so the overlay isn't visible for a single frame on
            // the very fast case where content is already in the DOM.
            setTimeout(hideLoading, 50);
        } else if (navPending) {
            // Path already matched (e.g. initial render) and DOM changed —
            // also safe to hide.
            setTimeout(hideLoading, 50);
        }
    }

    // Show loading overlay immediately when an internal link is clicked.
    document.addEventListener("click", function (e) {
        var link = e.target.closest("a[href]");
        if (!link) return;
        var href = link.getAttribute("href");
        if (!href || href.startsWith("http") || href.startsWith("#")) return;
        if (href === window.location.pathname) return;
        showLoading();
    }, true);

    // Watch for DOM updates (Dash page_container re-renders).
    function init() {
        new MutationObserver(function (mutations) {
            for (var i = 0; i < mutations.length; i++) {
                if (mutations[i].addedNodes.length) {
                    onPageSwap();
                    return;
                }
            }
        }).observe(document.body, { childList: true, subtree: true });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
