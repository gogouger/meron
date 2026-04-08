/**
 * Chart.js bridge — auto-renders charts from data-chartcfg attributes.
 *
 * Convention: Python chart functions output:
 *   html.Div(id="<chartId>-wrap", className="cjs-chart-wrap",
 *            **{"data-chartcfg": json_string})
 *     └─ html.Div(className="cjs-canvas-box")
 *
 * This script uses a MutationObserver to detect elements with
 * data-chartcfg and renders Chart.js instances into the canvas box.
 */

(function () {
    "use strict";

    var _charts = {};   // chartId → Chart instance

    /* ── CSS var helper ─────────────────────────────────────────────── */
    function cssVar(name) {
        return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    }

    /* ── open activity modal (replaces old scroll-to-card) ─────────── */
    function openActivityModal(dateStr) {
        if (!dateStr) return;
        // Set the URL hash — Dash's dcc.Location picks up href changes
        // and the clientside callback forwards the date to the modal store.
        window.location.hash = "modal:" + dateStr;
    }

    /* ── hover card for run charts ────────────────────────────────── */
    function showRunHoverCard(meta) {
        var card = document.getElementById("run-hover-card");
        if (!card || !meta) return;
        var typeColors = {
            "race": "#ef3c4a", "long": "#5b9bd5",
            "moderate": "#d4a84b", "easy": "#5b9bd5"
        };
        var tc = typeColors[meta.type] || "#a8a29e";
        var badge = meta.type
            ? '<span style="background:' + tc + ';color:#fff;font-size:9px;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;padding:1px 6px;margin-left:6px">' + meta.type + '</span>'
            : '';
        card.innerHTML =
            '<div style="font-weight:600;font-size:13px;color:var(--text-primary)">' + meta.name + badge + '</div>' +
            '<div style="margin-top:8px;display:grid;grid-template-columns:1fr 1fr;gap:6px 16px">' +
                '<div><div style="font-size:9px;text-transform:uppercase;letter-spacing:0.1em;color:var(--text-muted)">Distance</div><div style="font-family:var(--font-mono);font-size:14px;font-weight:600;color:var(--text-primary)">' + meta.dist + '</div></div>' +
                '<div><div style="font-size:9px;text-transform:uppercase;letter-spacing:0.1em;color:var(--text-muted)">Pace</div><div style="font-family:var(--font-mono);font-size:14px;font-weight:600;color:var(--text-primary)">' + meta.pace + '/mi</div></div>' +
                '<div><div style="font-size:9px;text-transform:uppercase;letter-spacing:0.1em;color:var(--text-muted)">Duration</div><div style="font-family:var(--font-mono);font-size:14px;font-weight:600;color:var(--text-primary)">' + meta.duration + '</div></div>' +
                (meta.hr ? '<div><div style="font-size:9px;text-transform:uppercase;letter-spacing:0.1em;color:var(--text-muted)">Avg HR</div><div style="font-family:var(--font-mono);font-size:14px;font-weight:600;color:var(--text-primary)">' + meta.hr + '</div></div>' : '') +
            '</div>' +
            '<div style="margin-top:8px;font-size:11px;color:var(--text-muted)">Click to view details \u2193</div>';
        card.style.display = "block";
    }

    function hideRunHoverCard() {
        var card = document.getElementById("run-hover-card");
        if (card) card.style.display = "none";
    }

    document.addEventListener("mousemove", function (e) {
        var card = document.getElementById("run-hover-card");
        if (!card || card.style.display === "none") return;
        var x = e.clientX + 16, y = e.clientY + 16;
        if (x + 280 > window.innerWidth) x = e.clientX - 280;
        if (y + 200 > window.innerHeight) y = e.clientY - 200;
        card.style.left = x + "px";
        card.style.top = y + "px";
    });

    /* ── custom tooltip ──────────────────────────────────────────── */
    var _tooltip = null;
    function getTooltip() {
        if (_tooltip) return _tooltip;
        _tooltip = document.createElement("div");
        _tooltip.className = "cjs-tooltip";
        document.body.appendChild(_tooltip);
        return _tooltip;
    }

    function _fmtMinSec(num) {
        var v = parseFloat(num);
        if (isNaN(v)) return num;
        var m = Math.floor(v);
        var s = Math.round((v - m) * 60);
        if (s === 60) { m++; s = 0; }
        return m + ":" + (s < 10 ? "0" : "") + s;
    }

    function externalTooltipHandler(context) {
        var tooltip = getTooltip();
        var model = context.tooltip;
        if (model.opacity === 0) { tooltip.style.display = "none"; return; }

        // Suppress when run hover card is active
        var hoverCard = document.getElementById("run-hover-card");
        if (hoverCard && hoverCard.style.display === "block") {
            tooltip.style.display = "none";
            return;
        }

        if (model.body) {
            var inner = "";

            // Route history tooltip: show custom fields (_dist, _pace, _hr)
            var dp = model.dataPoints && model.dataPoints[0];
            var rawPt = dp && dp.dataset && dp.dataset.data && dp.dataset.data[dp.dataIndex];
            if (rawPt && rawPt._pace !== undefined) {
                if (model.title && model.title.length)
                    inner += '<div style="font-weight:600;font-size:12px;margin-bottom:4px;color:var(--text-primary)">' + model.title.join(", ") + "</div>";
                var statStyle = 'font-family:var(--font-mono);font-size:13px;font-weight:600;color:var(--text-primary)';
                var labelStyle = 'font-size:9px;text-transform:uppercase;letter-spacing:0.08em;color:var(--text-muted)';
                inner += '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px 12px;margin-top:2px">';
                inner += '<div><div style="' + labelStyle + '">Pace</div><div style="' + statStyle + '">' + rawPt._pace + '/mi</div></div>';
                inner += '<div><div style="' + labelStyle + '">Dist</div><div style="' + statStyle + '">' + rawPt._dist + ' mi</div></div>';
                if (rawPt._hr) inner += '<div><div style="' + labelStyle + '">Avg HR</div><div style="' + statStyle + '">' + rawPt._hr + '</div></div>';
                inner += '</div>';
                tooltip.innerHTML = inner;
            } else {
                var lines = model.body.map(function (b) { return b.lines; });
                var isRace = (context.chart.canvas.parentElement.parentElement.id || "").indexOf("race-pred") >= 0;
                if (model.title && model.title.length)
                    inner += '<div style="font-weight:600;font-size:12px;margin-bottom:4px;color:var(--text-primary)">' + model.title.join(", ") + "</div>";
                lines.forEach(function (ln) {
                    var text = ln.join(", ");
                    if (isRace) {
                        text = text.replace(/:\s*(\d+\.?\d*)$/, function (_match, num) {
                            return ": " + _fmtMinSec(num);
                        });
                    }
                    inner += '<div style="font-size:11px;color:var(--text-secondary)">' + text + "</div>";
                });
                tooltip.innerHTML = inner;
            }
        }
        var pos = context.chart.canvas.getBoundingClientRect();
        tooltip.style.display = "block";
        tooltip.style.left = pos.left + window.scrollX + model.caretX + "px";
        tooltip.style.top = pos.top + window.scrollY + model.caretY - 40 + "px";
    }

    /* ── theme defaults ──────────────────────────────────────────── */
    function applyThemeDefaults(cfg, meta) {
        meta = meta || cfg._meta || {};
        delete cfg._meta;
        if (!cfg.options) cfg.options = {};
        if (!cfg.options.plugins) cfg.options.plugins = {};
        cfg.options.responsive = true;
        cfg.options.maintainAspectRatio = false;

        if (!cfg.options.plugins.tooltip) cfg.options.plugins.tooltip = {};
        cfg.options.plugins.tooltip.enabled = false;
        cfg.options.plugins.tooltip.external = externalTooltipHandler;
        cfg.options.plugins.tooltip.filter = function (tooltipItem) {
            var label = tooltipItem.dataset.label || "";
            return !label.startsWith("_");
        };

        if (cfg.type === "scatter") {
            if (!cfg.options.interaction) cfg.options.interaction = {};
            if (!cfg.options.interaction.mode) cfg.options.interaction.mode = "nearest";
            if (cfg.options.interaction.intersect === undefined) cfg.options.interaction.intersect = true;
        }

        var gridColor = cssVar("--gridline") || "#f5f5f4";
        var tickColor = cssVar("--text-muted") || "#a8a29e";
        var borderColor = cssVar("--border-light") || "#d6d3d1";
        var fontMono = cssVar("--font-mono") || "'IBM Plex Mono', monospace";

        if (cfg.options.scales) {
            Object.keys(cfg.options.scales).forEach(function (key) {
                var s = cfg.options.scales[key];
                if (!s.grid) s.grid = {};
                if (!s.ticks) s.ticks = {};
                if (!s.border) s.border = {};
                if (s.grid.color === undefined) s.grid.color = gridColor;
                if (s.ticks.color === undefined) s.ticks.color = tickColor;
                if (s.ticks.font === undefined) s.ticks.font = { family: fontMono, size: 10 };
                if (s.border.color === undefined) s.border.color = borderColor;
            });
        }

        if (!cfg.options.plugins.legend) cfg.options.plugins.legend = {};
        if (!cfg.options.plugins.legend.labels) cfg.options.plugins.legend.labels = {};
        cfg.options.plugins.legend.labels.color = cssVar("--text-secondary") || "#57534e";
        cfg.options.plugins.legend.labels.font = { family: cssVar("--font-sans") || "Inter", size: 11 };
        // Hide datasets with labels starting with _ from the legend
        cfg.options.plugins.legend.labels.filter = function (item) {
            return !item.text || !item.text.startsWith("_");
        };

        if (cfg.options.plugins.title && cfg.options.plugins.title.display) {
            cfg.options.plugins.title.color = cssVar("--text-secondary") || "#57534e";
            cfg.options.plugins.title.font = { family: cssVar("--font-sans") || "Inter", size: 15, weight: "500" };
        }

        // Zoom & pan — allow zooming in but hard-clamp to data bounds.
        if (Chart.registry && Chart.registry.getPlugin("zoom")) {
            var zoomLimits = {};
            var hasCategory = false;
            if (cfg.options.scales) {
                Object.keys(cfg.options.scales).forEach(function (key) {
                    var s = cfg.options.scales[key];
                    // Category axes (bar chart x) — clamp to "original" range
                    if (!s.type || s.type === "category") {
                        hasCategory = true;
                        zoomLimits[key] = { min: "original", max: "original", minRange: 0 };
                        return;
                    }
                    // beginAtZero implies min=0 for limit purposes
                    var lo = s.min, hi = s.max;
                    if (s.beginAtZero && lo === undefined) lo = 0;
                    if (lo !== undefined || hi !== undefined) {
                        // Time axes store min/max as ISO strings — convert to ms
                        if (s.type === "time") {
                            if (typeof lo === "string") lo = new Date(lo).getTime();
                            if (typeof hi === "string") hi = new Date(hi).getTime();
                        }
                        zoomLimits[key] = {
                            min: lo !== undefined ? lo : "original",
                            max: hi !== undefined ? hi : "original",
                            minRange: 0,
                        };
                    }
                });
            }

            // For bar charts, only allow y-axis zoom (category x can't zoom sensibly)
            var zoomMode = hasCategory ? "y" : "xy";

            // panOnly meta flag: pan on x only, no zoom
            if (meta.panOnly) {
                cfg.options.plugins.zoom = {
                    pan: { enabled: true, mode: "x" },
                    zoom: { wheel: { enabled: false }, pinch: { enabled: false }, drag: { enabled: false } },
                    limits: zoomLimits,
                };
            } else {
                cfg.options.plugins.zoom = {
                    pan: {
                        enabled: true,
                        mode: zoomMode,
                    },
                    zoom: {
                        wheel: { enabled: true },
                        pinch: { enabled: true },
                        drag: {
                            enabled: true,
                            backgroundColor: "rgba(239,60,74,0.08)",
                            borderColor: "rgba(239,60,74,0.3)",
                            borderWidth: 1,
                        },
                        mode: zoomMode,
                    },
                    limits: zoomLimits,
                };
            }
        }

        return cfg;
    }

    /* ── render a chart ──────────────────────────────────────────── */
    function renderChart(chartId, cfg) {
        if (!cfg || !cfg.type) return false;
        var wrap = document.getElementById(chartId + "-wrap");
        if (!wrap) return false;
        var box = wrap.querySelector(".cjs-canvas-box");
        if (!box) return false;

        var meta = cfg._meta || {};
        cfg = applyThemeDefaults(cfg, meta);

        if (_charts[chartId]) { _charts[chartId].destroy(); delete _charts[chartId]; }

        box.innerHTML = "";
        var canvas = document.createElement("canvas");
        box.appendChild(canvas);

        var chart;
        try {
            chart = new Chart(canvas.getContext("2d"), cfg);
        } catch (e) {
            console.error("chartjs-bridge: Chart() failed for", chartId, e);
            return false;
        }
        _charts[chartId] = chart;

        // Double-click → reset zoom
        canvas.addEventListener("dblclick", function () {
            if (chart.resetZoom) chart.resetZoom();
        });

        // Dynamic trend line — recalculate rolling avg/min when legend items toggled
        if (meta.dynamicTrendLine && meta.trendLineIndex !== undefined) {
            (function (trendIdx) {
                var defaultClick = Chart.defaults.plugins.legend.onClick;
                // Detect if trend is "best" (min) or "avg" based on label
                var trendLabel = (cfg.data.datasets[trendIdx] || {}).label || "";
                var useBest = trendLabel.toLowerCase().indexOf("best") >= 0;

                chart.options.plugins.legend.onClick = function (evt, legendItem, legend) {
                    defaultClick.call(this, evt, legendItem, legend);

                    var ci = legend.chart;
                    if (legendItem.datasetIndex === trendIdx) return;

                    // Collect visible scatter points (skip trend line and star/special datasets)
                    var points = [];
                    for (var i = 0; i < ci.data.datasets.length; i++) {
                        if (i === trendIdx) continue;
                        var ds = ci.data.datasets[i];
                        // Skip non-scatter datasets (lines, stars)
                        if (ds.showLine || ds.pointStyle === "star") continue;
                        if (ci.getDatasetMeta(i).hidden) continue;
                        ds.data.forEach(function (pt) {
                            if (!pt || !pt.x) return;
                            var t = new Date(pt.x).getTime();
                            if (isNaN(t) || pt.y == null) return;
                            points.push({ x: t, y: pt.y });
                        });
                    }

                    points.sort(function (a, b) { return a.x - b.x; });

                    // 30-day rolling window
                    var MS_30D = 30 * 24 * 60 * 60 * 1000;
                    var trend = [];
                    for (var j = 0; j < points.length; j++) {
                        var vals = [];
                        for (var k = j; k >= 0; k--) {
                            if (points[j].x - points[k].x > MS_30D) break;
                            vals.push(points[k].y);
                        }
                        if (vals.length >= (useBest ? 2 : 1)) {
                            var v = useBest
                                ? Math.min.apply(null, vals)
                                : vals.reduce(function(a,b){return a+b;}, 0) / vals.length;
                            trend.push({
                                x: new Date(points[j].x).toISOString(),
                                y: Math.round(v * 100) / 100
                            });
                        }
                    }

                    ci.data.datasets[trendIdx].data = trend;
                    ci.update();
                };
            })(meta.trendLineIndex);
        }

        // Click → scroll to run card
        if (meta.clickToScroll) {
            canvas.style.cursor = "pointer";
            canvas.addEventListener("click", function (evt) {
                var pts = chart.getElementsAtEventForMode(evt, "nearest", { intersect: true }, false);
                if (!pts.length) return;
                var pt = pts[0], ds = cfg.data.datasets[pt.datasetIndex];
                var dateStr = null;
                var item = ds.data[pt.index];
                if (item && item._dateStr) dateStr = item._dateStr;
                else if (meta.dateStrings && meta.dateStrings[pt.datasetIndex])
                    dateStr = meta.dateStrings[pt.datasetIndex][pt.index];
                if (dateStr) openActivityModal(dateStr);
            });
        }

        // Route history hover → scroll run list
        if (meta.routeHistoryHover && meta.scrollListId) {
            (function (listId) {
                var lastIdx = -1;
                canvas.addEventListener("mousemove", function (evt) {
                    var pts = chart.getElementsAtEventForMode(evt, "nearest", { intersect: false }, false);
                    if (!pts.length) return;
                    var idx = pts[0].index;
                    if (idx === lastIdx) return;
                    lastIdx = idx;
                    // The chart is sorted chronologically but the list is newest-first
                    var list = document.getElementById(listId);
                    if (!list) return;
                    var totalRows = list.children.length;
                    // Chart index 0 = oldest, list index 0 = newest → reverse
                    var listIdx = totalRows - 1 - idx;
                    var row = list.children[listIdx];
                    if (row) {
                        // Highlight row
                        for (var r = 0; r < list.children.length; r++) {
                            list.children[r].style.outline = "";
                        }
                        row.style.outline = "1.5px solid var(--accent)";
                        row.scrollIntoView({ block: "nearest", behavior: "smooth" });
                    }
                });
                canvas.addEventListener("mouseleave", function () {
                    lastIdx = -1;
                    var list = document.getElementById(listId);
                    if (!list) return;
                    for (var r = 0; r < list.children.length; r++) {
                        list.children[r].style.outline = "";
                    }
                });
            })(meta.scrollListId);
        }

        // Hover card for run charts
        if (meta.runHoverCard) {
            canvas.addEventListener("mousemove", function (evt) {
                var pts = chart.getElementsAtEventForMode(evt, "nearest", { intersect: true }, false);
                if (!pts.length) { hideRunHoverCard(); return; }
                var pt = pts[0], ds = cfg.data.datasets[pt.datasetIndex];
                var dateStr = null, item = ds.data[pt.index];
                if (item && item._dateStr) dateStr = item._dateStr;
                else if (meta.dateStrings && meta.dateStrings[pt.datasetIndex])
                    dateStr = meta.dateStrings[pt.datasetIndex][pt.index];
                if (dateStr && meta.runMeta && meta.runMeta[dateStr])
                    showRunHoverCard(meta.runMeta[dateStr]);
                else hideRunHoverCard();
            });
            canvas.addEventListener("mouseleave", hideRunHoverCard);
        }
    }
    window._cjsRenderChart = renderChart;

    /* ── MutationObserver: auto-render charts from data-chartcfg ── */
    function processElement(el) {
        var raw = el.getAttribute("data-chartcfg");
        if (!raw) return;
        if (el.getAttribute("data-rendered")) return;
        if (typeof Chart === "undefined") return; // Chart.js not loaded yet — retry later

        var chartId = el.id.replace(/-wrap$/, "");
        try {
            var cfg = JSON.parse(raw);
            var ok = renderChart(chartId, cfg);
            if (ok !== false) {
                el.setAttribute("data-rendered", "1");
            }
        } catch (e) {
            console.error("chartjs-bridge: error rendering", chartId, e);
        }
    }

    function scanAll() {
        var els = document.querySelectorAll("[data-chartcfg]:not([data-rendered])");
        for (var i = 0; i < els.length; i++) processElement(els[i]);
    }

    // Initial scan after DOM ready
    function init() {
        if (typeof Chart === "undefined") { setTimeout(init, 100); return; }
        scanAll();

        // Watch for dynamically added charts (e.g. from Dash callbacks)
        var observer = new MutationObserver(function (mutations) {
            var dominated = false;
            for (var i = 0; i < mutations.length; i++) {
                if (mutations[i].addedNodes.length) { dominated = true; break; }
                if (mutations[i].type === "attributes" && mutations[i].attributeName === "data-chartcfg") {
                    dominated = true; break;
                }
            }
            if (dominated) {
                // Scan immediately and again after a short delay for Dash rendering lag
                requestAnimationFrame(scanAll);
                setTimeout(scanAll, 200);
                setTimeout(scanAll, 600);
            }
        });
        observer.observe(document.body, {
            childList: true, subtree: true,
            attributes: true, attributeFilter: ["data-chartcfg"],
        });

        // Periodic fallback scan — catches anything the observer might miss
        // during rapid Dash re-renders or page transitions
        setInterval(scanAll, 1500);

        // Also scan on Dash page transitions (SPA navigation)
        window.addEventListener("popstate", function () {
            setTimeout(scanAll, 300);
            setTimeout(scanAll, 800);
            setTimeout(scanAll, 1500);
        });

        // Intercept pushState/replaceState for Dash SPA navigation
        var origPush = history.pushState;
        history.pushState = function () {
            origPush.apply(this, arguments);
            setTimeout(scanAll, 300);
            setTimeout(scanAll, 800);
            setTimeout(scanAll, 1500);
        };
    }

    if (document.readyState === "loading")
        document.addEventListener("DOMContentLoaded", init);
    else
        setTimeout(init, 0);

    // Extra safety: also try init after a delay in case Chart.js CDN is slow
    setTimeout(function () {
        if (typeof Chart !== "undefined") scanAll();
    }, 3000);

    /* ── race prediction tab switching ─────────────────────────── */
    document.addEventListener("click", function (e) {
        var btn = e.target.closest(".race-tab-btn");
        if (!btn) return;
        var idx = btn.getAttribute("data-tab-index");
        var chartId = btn.getAttribute("data-chart-id");
        if (!idx || !chartId) return;

        var container = document.getElementById(chartId + "-tabs");
        if (!container) return;

        // Hide all panels, show selected
        container.querySelectorAll(".race-tab-panel").forEach(function (p) {
            p.style.display = "none";
        });
        var target = document.getElementById(chartId + "-panel-" + idx);
        if (target) target.style.display = "block";

        // Update active tab style
        container.querySelectorAll(".race-tab-btn").forEach(function (b) {
            b.classList.remove("race-tab-active");
        });
        btn.classList.add("race-tab-active");

        // Charts rendered while hidden have zero size — resize them
        setTimeout(function () {
            if (!target) return;
            target.querySelectorAll("[data-chartcfg]").forEach(function (w) {
                var cid = w.id.replace(/-wrap$/, "");
                if (_charts[cid]) _charts[cid].resize();
            });
            scanAll(); // render any unrendered charts in the now-visible tab
        }, 50);
    });

    /* ── sidebar scroll management ─────────────────────────────── */
    // Lock body scroll when the sidebar is open so wheel events
    // go to whatever the mouse is hovering over (sidebar vs page).
    var _sidebarObserver = new MutationObserver(function () {
        var overlay = document.getElementById("activity-modal-overlay");
        if (overlay && overlay.children.length > 0) {
            document.body.classList.add("sidebar-open");
        } else {
            document.body.classList.remove("sidebar-open");
        }
    });
    // Start observing once the container exists
    function watchSidebar() {
        var container = document.getElementById("activity-modal-container");
        if (container) {
            _sidebarObserver.observe(container, { childList: true, subtree: true });
        } else {
            setTimeout(watchSidebar, 500);
        }
    }
    watchSidebar();

    // Also close sidebar on Escape key
    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape") {
            var btn = document.getElementById("modal-close-btn");
            if (btn) btn.click();
        }
    });

    /* ── dark mode re-render ─────────────────────────────────────── */
    if (window.matchMedia) {
        window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () {
            // Re-render all charts with updated CSS vars
            var els = document.querySelectorAll("[data-chartcfg][data-rendered]");
            for (var i = 0; i < els.length; i++) {
                els[i].removeAttribute("data-rendered");
                processElement(els[i]);
            }
        });
    }
})();
