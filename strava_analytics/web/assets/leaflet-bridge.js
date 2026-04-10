/**
 * Leaflet bridge — auto-renders route maps from data-mapcfg attributes.
 *
 * Convention: Python outputs:
 *   html.Div(className="leaflet-map-wrap", **{"data-mapcfg": json, "data-mapid": "container-id"})
 *     └─ html.Div(id="container-id", className="leaflet-map-box")
 *
 * This script uses a MutationObserver (same pattern as chartjs-bridge.js)
 * to detect elements with data-mapcfg and render Leaflet maps.
 */

(function () {
    "use strict";

    var _maps = {};

    function renderMap(el) {
        var raw = el.getAttribute("data-mapcfg");
        if (!raw) return;
        if (el.getAttribute("data-maprendered")) return;
        if (typeof L === "undefined") return; // Leaflet not loaded yet

        var containerId = el.getAttribute("data-mapid");
        if (!containerId) return;
        var container = document.getElementById(containerId);
        if (!container) return;

        var cfg;
        try { cfg = JSON.parse(raw); } catch (e) { return; }
        if (!cfg.coords || !cfg.coords.length) return;

        el.setAttribute("data-maprendered", "1");

        // Ensure container has height
        container.style.height = (cfg.height || 300) + "px";

        // Destroy old map if re-rendering
        if (_maps[containerId]) {
            _maps[containerId].remove();
            delete _maps[containerId];
        }

        // Mini maps (height <= 160) are static previews — no interaction
        var isMini = (cfg.height || 300) <= 160;
        var map = L.map(container, {
            zoomControl: !isMini,
            scrollWheelZoom: !isMini,
            dragging: !isMini,
            doubleClickZoom: !isMini,
            touchZoom: !isMini,
            boxZoom: !isMini,
            keyboard: !isMini,
            attributionControl: false,
        });

        L.tileLayer("https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png", {
            maxZoom: 19, subdomains: "abcd",
        }).addTo(map);

        // Heat layer (if heatData provided and L.heatLayer available)
        if (cfg.heatData && cfg.heatData.length && typeof L.heatLayer === "function") {
            var heat = L.heatLayer(cfg.heatData, {
                radius: cfg.heatRadius || 8,
                blur: cfg.heatBlur || 12,
                maxZoom: cfg.heatMaxZoom || 15,
                gradient: cfg.heatGradient || {0.2: "#2563eb", 0.5: "#f59e0b", 0.8: "#ef4444", 1.0: "#ffffff"},
            }).addTo(map);
            // Fit to heat bounds
            var bounds = L.latLngBounds(cfg.heatData.map(function(p) { return [p[0], p[1]]; }));
            map.fitBounds(bounds, { padding: [20, 20] });
        }

        // Route polyline (if coords provided)
        if (cfg.coords && cfg.coords.length) {
            var polyline = L.polyline(cfg.coords, {
                color: cfg.color || "#ef3c4a",
                weight: 3, opacity: 0.9,
            }).addTo(map);
            map.fitBounds(polyline.getBounds(), { padding: [20, 20] });
        }
        _maps[containerId] = map;
    }

    function scanMaps() {
        var els = document.querySelectorAll("[data-mapcfg]:not([data-maprendered])");
        for (var i = 0; i < els.length; i++) renderMap(els[i]);
        // Also scan for standalone heatmaps
        scanHeatmaps();
    }

    function scanHeatmaps() {
        var els = document.querySelectorAll("[data-heatmap]:not([data-maprendered])");
        for (var i = 0; i < els.length; i++) renderHeatmap(els[i]);
    }

    function renderHeatmap(el) {
        if (el.getAttribute("data-maprendered")) return;
        if (typeof L === "undefined" || typeof L.heatLayer !== "function") return;

        var containerId = "run-heatmap-map";
        var container = document.getElementById(containerId);
        if (!container) return;
        if (container.offsetHeight < 10) return; // not visible yet

        el.setAttribute("data-maprendered", "1");
        container.style.height = "400px";

        var map = L.map(container, {
            zoomControl: true, scrollWheelZoom: true,
            dragging: true, attributionControl: false,
        });

        L.tileLayer("https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png", {
            maxZoom: 19, subdomains: "abcd",
        }).addTo(map);

        // Fetch precomputed heat data
        fetch("/assets/heatmap-data.json")
            .then(function(r) { return r.json(); })
            .then(function(heatData) {
                if (!heatData || !heatData.length) return;
                L.heatLayer(heatData, {
                    radius: 6, blur: 10, maxZoom: 16,
                    gradient: {0.2: "#2563eb", 0.5: "#f59e0b", 0.8: "#ef4444", 1.0: "#ffffff"},
                }).addTo(map);
                var bounds = L.latLngBounds(heatData.map(function(p) { return [p[0], p[1]]; }));
                map.fitBounds(bounds, { padding: [20, 20] });
            })
            .catch(function(e) { console.warn("Heatmap data fetch failed:", e); });
    }

    function init() {
        if (typeof L === "undefined") { setTimeout(init, 200); return; }
        scanMaps();

        var observer = new MutationObserver(function (mutations) {
            var dominated = false;
            for (var i = 0; i < mutations.length; i++) {
                if (mutations[i].addedNodes.length) { dominated = true; break; }
                if (mutations[i].type === "attributes" && mutations[i].attributeName === "data-mapcfg") {
                    dominated = true; break;
                }
            }
            if (dominated) {
                requestAnimationFrame(scanMaps);
                setTimeout(scanMaps, 300);
                setTimeout(scanMaps, 800);
            }
        });
        observer.observe(document.body, {
            childList: true, subtree: true,
            attributes: true, attributeFilter: ["data-mapcfg"],
        });

        setInterval(scanMaps, 2000);
    }

    if (document.readyState === "loading")
        document.addEventListener("DOMContentLoaded", init);
    else
        setTimeout(init, 0);
})();
