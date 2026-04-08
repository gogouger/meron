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

    // Apply immediately on script load (before first paint)
    var saved = localStorage.getItem("strava-theme") || "system";
    applyTheme(saved);

    // Expose for Dash clientside callbacks
    window._applyTheme = applyTheme;
})();
