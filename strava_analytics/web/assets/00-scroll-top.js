/**
 * Seamless page transitions for Dash multi-page navigation.
 * Hides content instantly on navigation, scrolls to top while hidden,
 * then fades in the new content. No visible scroll jump.
 */
(function () {
    var lastPath = window.location.pathname;
    var container = null;

    function getContainer() {
        if (!container) {
            container = document.getElementById("_pages_content") ||
                        document.querySelector("[id*='page-content']") ||
                        document.body;
        }
        return container;
    }

    function onPageSwap() {
        var currentPath = window.location.pathname;
        if (currentPath !== lastPath) {
            lastPath = currentPath;
            var el = getContainer();
            // Content is already hidden (opacity 0 from click handler)
            // Scroll to top while invisible — no visible jump
            window.scrollTo(0, 0);
            // Fade in new content
            requestAnimationFrame(function () {
                el.style.transition = "opacity 200ms ease-in";
                el.style.opacity = "1";
            });
        }
    }

    // Hide content immediately on internal link click
    document.addEventListener("click", function (e) {
        var link = e.target.closest("a[href]");
        if (!link) return;
        var href = link.getAttribute("href");
        if (!href || href.startsWith("http") || href.startsWith("#")) return;
        if (href === window.location.pathname) return;
        var el = getContainer();
        el.style.transition = "none";
        el.style.opacity = "0";
    }, true);

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
