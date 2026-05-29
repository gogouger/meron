/**
 * Interactive HR zone bar with draggable boundary dividers.
 *
 * Reads config from #hr-zone-bar data attributes, renders zone segments,
 * and overlays draggable handles at each boundary.  On drag, updates the
 * zone widths live and writes new values to the dcc.Store components
 * (zone-pct-0 .. zone-pct-3) via React-compatible property setting.
 */
(function () {
    "use strict";

    function initZoneBar() {
        var bar = document.getElementById("hr-zone-bar");
        if (!bar || bar._zoneInit) return;
        bar._zoneInit = true;

        var maxHR = parseInt(bar.getAttribute("data-max-hr") || "200", 10);
        var pctStr = bar.getAttribute("data-zone-pct") || "60,70,80,90";
        var pcts = pctStr.split(",").map(Number);  // [60, 70, 80, 90]
        var names = (bar.getAttribute("data-zone-names") || "Recovery,Easy,Moderate,Threshold,Max").split(",");
        var colors = (bar.getAttribute("data-zone-colors") || "#7ba05f,#1a8a77,#d4a83f,#cc7a4d,#c1543a").split(",");
        var opacities = (bar.getAttribute("data-zone-opacities") || "0.4,0.7,0.7,0.7,1.0").split(",").map(Number);

        // Container styling
        bar.style.display = "flex";
        bar.style.borderRadius = "8px";
        bar.style.overflow = "visible";
        bar.style.position = "relative";
        bar.style.cursor = "default";

        var segments = [];  // DOM elements for the 5 zone segments
        var handles = [];   // DOM elements for the 4 boundary handles

        function render() {
            // Compute boundaries
            var bounds = [0].concat(pcts).concat([100]);

            // Update or create segments
            for (var i = 0; i < 5; i++) {
                var widthPct = bounds[i + 1] - bounds[i];
                var loBpm = Math.round(maxHR * bounds[i] / 100);
                var hiBpm = i < 4 ? Math.round(maxHR * bounds[i + 1] / 100) : maxHR;

                if (!segments[i]) {
                    segments[i] = document.createElement("div");
                    segments[i].style.cssText = "display:flex;flex-direction:column;align-items:center;justify-content:center;color:white;transition:width 0.05s;overflow:hidden;";
                    bar.appendChild(segments[i]);
                }

                var seg = segments[i];
                seg.style.width = widthPct + "%";
                seg.style.background = colors[i];
                seg.style.opacity = opacities[i];
                seg.style.minHeight = "70px";

                // Only show label if segment is wide enough
                if (widthPct > 8) {
                    seg.innerHTML =
                        '<div style="font-size:11px;font-weight:700">Z' + (i + 1) + '</div>' +
                        '<div style="font-size:9px;opacity:0.8">' + names[i] + '</div>' +
                        '<div style="font-size:10px;font-family:\'IBM Plex Mono\',monospace;margin-top:2px">' + loBpm + '-' + hiBpm + '</div>';
                } else {
                    seg.innerHTML = '<div style="font-size:10px;font-weight:700">Z' + (i + 1) + '</div>';
                }
            }

            // Update or create handles (positioned absolutely between segments)
            for (var j = 0; j < 4; j++) {
                if (!handles[j]) {
                    handles[j] = document.createElement("div");
                    handles[j].style.cssText =
                        "position:absolute;top:0;width:12px;height:100%;cursor:col-resize;z-index:10;" +
                        "display:flex;align-items:center;justify-content:center;";
                    handles[j].innerHTML = '<div style="width:3px;height:24px;background:white;border-radius:2px;opacity:0.7;box-shadow:0 0 4px rgba(0,0,0,0.3)"></div>';
                    handles[j]._idx = j;
                    bar.appendChild(handles[j]);
                    attachDrag(handles[j], j);
                }
                // Position the handle at the boundary percentage
                handles[j].style.left = "calc(" + pcts[j] + "% - 6px)";
            }

            // Update dcc.Store values via React-compatible setter
            for (var k = 0; k < 4; k++) {
                updateStore(k, pcts[k]);
            }
        }

        function updateStore(idx, value) {
            // Find the dcc.Store element and update its data prop
            // Dash dcc.Store uses a hidden div; we set data via setProps
            // We use the same React property hack as chart bridge
            var storeId = "zone-pct-" + idx;
            var storeEl = document.getElementById(storeId);
            if (!storeEl) return;
            // Dash stores don't have a simple DOM value; instead we rely on
            // the save callback reading the current pcts from the bar's data attribute
            // Update the bar's data attribute as the source of truth
            bar.setAttribute("data-zone-pct", pcts.join(","));
        }

        function attachDrag(handle, idx) {
            var dragging = false;

            handle.addEventListener("mousedown", function (e) {
                e.preventDefault();
                dragging = true;
                document.body.style.cursor = "col-resize";
                document.body.style.userSelect = "none";
            });

            document.addEventListener("mousemove", function (e) {
                if (!dragging) return;
                var rect = bar.getBoundingClientRect();
                var x = e.clientX - rect.left;
                var pct = Math.round(x / rect.width * 100);

                // Clamp: can't go past neighbors (min 5% gap)
                var minPct = idx === 0 ? 10 : pcts[idx - 1] + 5;
                var maxPct = idx === 3 ? 95 : pcts[idx + 1] - 5;
                pct = Math.max(minPct, Math.min(maxPct, pct));

                pcts[idx] = pct;
                window._currentZonePct = pcts.slice();
                render();
            });

            document.addEventListener("mouseup", function () {
                if (dragging) {
                    dragging = false;
                    document.body.style.cursor = "";
                    document.body.style.userSelect = "";
                }
            });

            // Touch support
            handle.addEventListener("touchstart", function (e) {
                e.preventDefault();
                dragging = true;
            }, { passive: false });

            document.addEventListener("touchmove", function (e) {
                if (!dragging) return;
                var touch = e.touches[0];
                var rect = bar.getBoundingClientRect();
                var x = touch.clientX - rect.left;
                var pct = Math.round(x / rect.width * 100);
                var minPct = idx === 0 ? 10 : pcts[idx - 1] + 5;
                var maxPct = idx === 3 ? 95 : pcts[idx + 1] - 5;
                pcts[idx] = Math.max(minPct, Math.min(maxPct, pct));
                window._currentZonePct = pcts.slice();
                render();
            }, { passive: false });

            document.addEventListener("touchend", function () {
                dragging = false;
            });
        }

        // Also update maxHR when the input changes
        var maxHRInput = document.getElementById("max-hr-input");
        if (maxHRInput) {
            maxHRInput.addEventListener("input", function () {
                var val = parseInt(maxHRInput.value, 10);
                if (val && val > 100 && val < 250) {
                    maxHR = val;
                    bar.setAttribute("data-max-hr", String(maxHR));
                    render();
                }
            });
        }

        window._currentZonePct = pcts.slice();
        render();
    }

    // Initialize when DOM is ready
    function tryInit() {
        if (document.getElementById("hr-zone-bar")) {
            initZoneBar();
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", tryInit);
    } else {
        tryInit();
    }

    // Also re-check periodically for SPA navigation
    var observer = new MutationObserver(function () {
        if (document.getElementById("hr-zone-bar") && !document.getElementById("hr-zone-bar")._zoneInit) {
            initZoneBar();
        }
    });
    if (document.body) {
        observer.observe(document.body, { childList: true, subtree: true });
    }
})();
