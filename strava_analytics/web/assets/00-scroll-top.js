/**
 * Scroll to top on Dash page navigation.
 * Uses MutationObserver to detect when Dash swaps page content.
 * Prefixed with 00- to load early.
 */
(function () {
    var lastPath = window.location.pathname;

    function checkNav() {
        var currentPath = window.location.pathname;
        if (currentPath !== lastPath) {
            lastPath = currentPath;
            window.scrollTo(0, 0);
        }
    }

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
