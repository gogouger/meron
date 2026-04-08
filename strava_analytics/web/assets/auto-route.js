/**
 * Auto-load route charts when a run card is expanded.
 * Clicks the hidden "View Route & Charts" button automatically on toggle.
 */
(function () {
    document.addEventListener("toggle", function (e) {
        var details = e.target;
        if (!details.open || details.tagName !== "DETAILS") return;
        if (!details.id || !(details.id.startsWith("run-card-") || details.id.startsWith("activity-card-"))) return;

        // Find the route button inside this card and click it (if not already loaded)
        var btn = details.querySelector('[id*="route-btn"]');
        if (btn && btn.getAttribute("data-loaded") !== "1") {
            btn.setAttribute("data-loaded", "1");
            btn.click();
        }
    }, true);
})();
