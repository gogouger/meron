/**
 * Text scramble animation for section labels.
 * Characters shuffle through random glyphs before settling into final text.
 * Triggers when elements with .scramble-label scroll into view.
 *
 * Uses a single IntersectionObserver and a debounced MutationObserver
 * to avoid infinite feedback loops.
 */
(function () {
    var CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%&";
    var STEP_MS = 25;
    var animating = 0; // count of active animations — MO ignores DOM changes while > 0

    function scramble(el) {
        if (el.dataset.scrambled) return;
        el.dataset.scrambled = "true"; // mark BEFORE animating to prevent re-entry

        var final_text = el.textContent;
        var len = final_text.length;
        var resolved = 0;

        animating++;
        var interval = setInterval(function () {
            var display = "";
            for (var i = 0; i < len; i++) {
                if (i < resolved) {
                    display += final_text[i];
                } else if (final_text[i] === " ") {
                    display += " ";
                } else {
                    display += CHARS[Math.floor(Math.random() * CHARS.length)];
                }
            }
            el.textContent = display;
            resolved++;

            if (resolved > len) {
                clearInterval(interval);
                el.textContent = final_text;
                animating--;
            }
        }, STEP_MS);
    }

    // Single shared IntersectionObserver for all scramble labels
    var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
            if (entry.isIntersecting) {
                scramble(entry.target);
                io.unobserve(entry.target);
            }
        });
    }, { threshold: 0.1 });

    function observeNew() {
        document.querySelectorAll(".scramble-label:not([data-scrambled])").forEach(function (el) {
            io.observe(el);
        });
    }

    // Debounced MutationObserver — only scans after 500ms of DOM quiet
    var debounceTimer = null;
    var mo = new MutationObserver(function () {
        if (animating > 0) return; // ignore mutations caused by our own animations
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(observeNew, 500);
    });

    function init() {
        observeNew();
        mo.observe(document.body, { childList: true, subtree: true });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
