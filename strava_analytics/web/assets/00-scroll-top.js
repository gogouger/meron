/**
 * Smooth page transitions for Dash multi-page navigation.
 * - Fades out content before page swap, fades in after
 * - Scrolls to top on each navigation
 */
(function () {
    var lastPath = window.location.pathname;
    var container = null;

    function getContainer() {
        if (!container) {
            container = document.getElementById("_pages_content") ||
                        document.querySelector("[id*='page-content']") ||
                        document.querySelector("main") ||
                        document.body;
        }
        return container;
    }

    function fadeIn() {
        var el = getContainer();
        el.style.transition = "opacity 150ms ease-in";
        el.style.opacity = "1";
    }

    function checkNav() {
        var currentPath = window.location.pathname;
        if (currentPath !== lastPath) {
            lastPath = currentPath;
            window.scrollTo(0, 0);
            // Fade in new content
            var el = getContainer();
            el.style.opacity = "0";
            requestAnimationFrame(function () {
                requestAnimationFrame(fadeIn);
            });
        }
    }

    // Intercept link clicks to fade out before navigation
    document.addEventListener("click", function (e) {
        var link = e.target.closest("a[href]");
        if (!link) return;
        var href = link.getAttribute("href");
        if (!href || href.startsWith("http") || href.startsWith("#") || href === window.location.pathname) return;
        // Internal Dash link — fade out
        var el = getContainer();
        el.style.transition = "opacity 100ms ease-out";
        el.style.opacity = "0.3";
    }, true);

    function init() {
        new MutationObserver(function (mutations) {
            for (var i = 0; i < mutations.length; i++) {
                if (mutations[i].addedNodes.length) {
                    checkNav();
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
