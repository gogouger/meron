/**
 * Custom bounded scroll-zoom for Plotly charts.
 *
 * Plotly's built-in scrollZoom is disabled (config.scrollZoom = false).
 * This script re-implements scroll-zoom with hard range clamping so the
 * user can zoom in freely but can never zoom out past the data bounds.
 * When already at max zoom-out, scroll events fall through to the page.
 */
(function () {
    /* Convert axis value to a number (handles date strings). */
    function toNum(v) {
        return typeof v === "string" ? new Date(v).getTime() : +v;
    }

    /* Convert number back to the same type as the reference value. */
    function fromNum(n, ref) {
        if (typeof ref === "string") return new Date(n).toISOString().replace("Z", "");
        return n;
    }

    /**
     * Compute a new [lo, hi] range after zooming by `factor` around `frac`
     * (0 = left/bottom, 1 = right/top). Clamp to [minN, maxN].
     * Returns null if the range cannot change (already at boundary).
     */
    function zoomedRange(curLo, curHi, factor, frac, minN, maxN) {
        var span = curHi - curLo;
        var anchor = curLo + frac * span;
        var newSpan = span * factor;

        var newLo = anchor - frac * newSpan;
        var newHi = anchor + (1 - frac) * newSpan;

        // Clamp
        if (newLo < minN) newLo = minN;
        if (newHi > maxN) newHi = maxN;

        // If nothing changed (zooming out at max, or zooming in at max-in)
        var eps = Math.abs(maxN - minN) * 1e-9 || 1;
        if (Math.abs(newLo - curLo) < eps && Math.abs(newHi - curHi) < eps) {
            return null;
        }
        return [newLo, newHi];
    }

    function handleWheel(plotDiv, e) {
        var layout = plotDiv._fullLayout;
        if (!layout) return false;

        // Find the plot area rect for mouse-position fraction
        var nsew = plotDiv.querySelector(".nsewdrag");
        if (!nsew) return false;
        var rect = nsew.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return false;

        // Mouse position as fraction of plot area
        var xFrac = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
        var yFrac = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));

        // Zoom factor — scroll down (deltaY > 0) zooms out
        var factor = 1 + Math.min(Math.abs(e.deltaY), 300) * 0.003;
        if (e.deltaY < 0) factor = 1 / factor;

        var update = {};
        var anyChange = false;

        // Process each axis
        var axes = [
            {name: "xaxis", frac: xFrac},
            {name: "yaxis", frac: 1 - yFrac},  // screen Y is inverted
        ];

        for (var i = 0; i < axes.length; i++) {
            var ax = layout[axes[i].name];
            if (!ax || ax.fixedrange) continue;

            var r0 = toNum(ax.range[0]), r1 = toNum(ax.range[1]);
            var reversed = r0 > r1;
            var curLo = reversed ? r1 : r0;
            var curHi = reversed ? r0 : r1;
            var minN = ax.minallowed !== undefined ? toNum(ax.minallowed) : -Infinity;
            var maxN = ax.maxallowed !== undefined ? toNum(ax.maxallowed) : Infinity;
            var frac = reversed ? (1 - axes[i].frac) : axes[i].frac;

            var result = zoomedRange(curLo, curHi, factor, frac, minN, maxN);
            if (result) {
                var ref = ax.range[0];  // preserve type (string vs number)
                if (reversed) {
                    update[axes[i].name + ".range[0]"] = fromNum(result[1], ref);
                    update[axes[i].name + ".range[1]"] = fromNum(result[0], ref);
                } else {
                    update[axes[i].name + ".range[0]"] = fromNum(result[0], ref);
                    update[axes[i].name + ".range[1]"] = fromNum(result[1], ref);
                }
                anyChange = true;
            }
        }

        if (!anyChange) return false;  // at zoom limit — let page scroll

        Plotly.relayout(plotDiv, update);
        return true;
    }

    function attach(plotDiv) {
        if (plotDiv._boundedZoomAttached) return;
        plotDiv._boundedZoomAttached = true;

        plotDiv.addEventListener("wheel", function (e) {
            // Only handle events targeted at the chart's interactive area
            if (!e.target.closest || !e.target.closest(".draglayer, .nsewdrag, .main-svg")) return;

            if (handleWheel(plotDiv, e)) {
                e.preventDefault();
                e.stopPropagation();
            }
            // If handleWheel returned false, let the page scroll naturally
        }, {passive: false});
    }

    function scan() {
        document.querySelectorAll(".js-plotly-plot").forEach(attach);
    }

    new MutationObserver(scan).observe(document.body, {
        childList: true, subtree: true,
        attributes: true, attributeFilter: ["class"],
    });

    var attempts = 0;
    var timer = setInterval(function () {
        scan();
        if (++attempts >= 10) clearInterval(timer);
    }, 500);

    scan();
})();
