/**
 * Calendar activity click → jump to run/lift card on the target page.
 * Also handles arriving on a page with a pending jump from sessionStorage.
 */
(function () {
    // Click handler for calendar activity links
    document.addEventListener("click", function (e) {
        var link = e.target.closest(".cal-activity-link");
        if (!link) return;
        var dateStr = link.getAttribute("data-date");
        var target = link.getAttribute("data-target");
        if (!dateStr || !target) return;

        sessionStorage.setItem("jumpToCard", dateStr);
        sessionStorage.setItem("jumpBackPage", window.location.pathname);
        window.location.href = target;
    });

    function scrollToCard(dateStr) {
        // Unhide all cards if paginated
        var hidden = document.getElementById("hidden-run-cards");
        if (hidden) hidden.style.display = "block";
        var showBtn = document.getElementById("show-all-runs-btn");
        if (showBtn) showBtn.style.display = "none";

        // Find card — try run cards, then lift cards
        var card = document.querySelector('details[id^="run-card-' + dateStr + '"]')
                || document.querySelector('details[id^="lift-card-' + dateStr + '"]');
        if (!card) return false;

        card.open = true;
        setTimeout(function () {
            card.scrollIntoView({behavior: "smooth", block: "center"});
            card.style.transition = "box-shadow 0.3s";
            card.style.boxShadow = "0 0 0 3px #ef3c4a";
            setTimeout(function () { card.style.boxShadow = ""; }, 2500);
        }, 200);

        // Show back button
        var backBtn = document.getElementById("jump-back-btn");
        if (backBtn) {
            var backPage = sessionStorage.getItem("jumpBackPage");
            sessionStorage.removeItem("jumpBackPage");
            backBtn.style.display = "flex";
            backBtn.onclick = function () {
                if (backPage) {
                    window.location.href = backPage;
                } else if (window._jumpBackY !== undefined) {
                    window.scrollTo({top: window._jumpBackY, behavior: "smooth"});
                    backBtn.style.display = "none";
                } else {
                    history.back();
                }
            };
        }
        return true;
    }

    function checkPendingJump() {
        var dateStr = sessionStorage.getItem("jumpToCard");
        if (!dateStr) return;

        // Poll until cards are rendered (Dash loads content async)
        var attempts = 0;
        var timer = setInterval(function () {
            var hasCards = document.querySelector("details[id^='run-card-']")
                       || document.querySelector("details[id^='lift-card-']");
            if (hasCards) {
                clearInterval(timer);
                sessionStorage.removeItem("jumpToCard");
                scrollToCard(dateStr);
            }
            if (++attempts >= 30) {
                clearInterval(timer);
                sessionStorage.removeItem("jumpToCard");
            }
        }, 200);
    }

    // Check on initial load
    checkPendingJump();

    // Also check on Dash URL changes (MutationObserver on the page content)
    new MutationObserver(function () {
        if (sessionStorage.getItem("jumpToCard")) {
            checkPendingJump();
        }
    }).observe(document.body, {childList: true, subtree: true});
})();
