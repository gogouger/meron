/**
 * Track mouse position for the hover card tooltip.
 * Throttled to 60fps to avoid DOM thrashing.
 */
(function () {
    var mx = 0, my = 0, ticking = false;

    document.addEventListener("mousemove", function (e) {
        mx = e.clientX;
        my = e.clientY;
        if (!ticking) {
            ticking = true;
            requestAnimationFrame(function () {
                var card = document.getElementById("hover-card");
                if (card && card.style.display === "block") {
                    var x = mx + 16;
                    var y = my - 20;
                    if (x + 280 > window.innerWidth) x = mx - 280;
                    if (y + 200 > window.innerHeight) y = my - 200;
                    if (y < 0) y = 10;
                    card.style.left = x + "px";
                    card.style.top = y + "px";
                }
                ticking = false;
            });
        }
    });

    // Hide hover card when mouse leaves any chart area
    document.addEventListener("mouseout", function (e) {
        var target = e.target;
        if (target && target.closest && target.closest(".cjs-chart-wrap")) {
            var related = e.relatedTarget;
            if (!related || !related.closest || !related.closest(".cjs-chart-wrap")) {
                var card = document.getElementById("hover-card");
                if (card) card.style.display = "none";
            }
        }
    });

    // Hide hover card on scroll (scrolling doesn't fire mouseout)
    var scrollTicking = false;
    window.addEventListener("scroll", function () {
        if (scrollTicking) return;
        scrollTicking = true;
        requestAnimationFrame(function() {
            var card = document.getElementById("hover-card");
            if (card && card.style.display === "block") {
                card.style.display = "none";
            }
            scrollTicking = false;
        });
    }, {passive: true});
})();
