/**
 * Render inline SVG icons from data-svg-icon attributes.
 * Uses MutationObserver to handle Dash dynamic rendering.
 */
(function () {
    function renderIcons() {
        var els = document.querySelectorAll("[data-svg-icon]:not([data-icon-rendered])");
        for (var i = 0; i < els.length; i++) {
            var el = els[i];
            var svg = el.getAttribute("data-svg-icon");
            if (svg) {
                el.innerHTML = svg;
                el.setAttribute("data-icon-rendered", "1");
            }
        }
    }

    function init() {
        renderIcons();
        var observer = new MutationObserver(function (mutations) {
            for (var i = 0; i < mutations.length; i++) {
                if (mutations[i].addedNodes.length) {
                    requestAnimationFrame(renderIcons);
                    return;
                }
            }
        });
        observer.observe(document.body, { childList: true, subtree: true });
        // Periodic fallback
        setInterval(renderIcons, 2000);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
