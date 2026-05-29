/**
 * Theme toggle — reads localStorage and sets data-theme on <html>.
 *
 * Named 00- so it loads before other assets (Dash serves alphabetically).
 * Runs immediately (no DOMContentLoaded wait) to prevent flash of wrong theme.
 *
 * Values: "dark", "light", "system" (or absent = system)
 */
(function () {
    "use strict";

    function applyTheme(choice) {
        if (choice === "dark") {
            document.documentElement.setAttribute("data-theme", "dark");
        } else if (choice === "light") {
            document.documentElement.setAttribute("data-theme", "light");
        } else {
            // "system" or unset — remove override, let CSS media query handle it
            document.documentElement.removeAttribute("data-theme");
        }
    }

    // Apply immediately on script load (before first paint).
    // One-time migration of the legacy "strava-theme" key to "meron-theme".
    var saved = localStorage.getItem("meron-theme")
             || localStorage.getItem("strava-theme")
             || "light";
    if (localStorage.getItem("strava-theme") && !localStorage.getItem("meron-theme")) {
        localStorage.setItem("meron-theme", saved);
        localStorage.removeItem("strava-theme");
    }
    applyTheme(saved);

    // Expose for Dash clientside callbacks
    window._applyTheme = applyTheme;
})();
