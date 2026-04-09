/**
 * Chat widget client-side helpers.
 *
 * Handles: open/close toggle, Enter-to-send, auto-scroll.
 */
(function () {
    "use strict";

    function ready(fn) {
        if (document.readyState !== "loading") fn();
        else document.addEventListener("DOMContentLoaded", fn);
    }

    ready(function () {
        // Toggle chat panel open/close
        document.addEventListener("click", function (e) {
            var bubble = e.target.closest("#chat-bubble-btn");
            if (bubble) {
                var panel = document.getElementById("chat-panel");
                if (panel) {
                    panel.classList.toggle("chat-open");
                    // Focus input when opening
                    if (panel.classList.contains("chat-open")) {
                        var input = document.getElementById("chat-input");
                        if (input) setTimeout(function () { input.focus(); }, 100);
                    }
                }
                return;
            }

            var closeBtn = e.target.closest("#chat-close-btn");
            if (closeBtn) {
                var panel = document.getElementById("chat-panel");
                if (panel) panel.classList.remove("chat-open");
            }
        });

        // Enter key to send (without shift)
        document.addEventListener("keydown", function (e) {
            if (e.target.id !== "chat-input") return;
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                var sendBtn = document.getElementById("chat-send-btn");
                if (sendBtn) sendBtn.click();
            }
        });

        // Auto-scroll chat messages to bottom when new content appears
        var msgContainer = document.getElementById("chat-messages");
        if (msgContainer) {
            var observer = new MutationObserver(function () {
                msgContainer.scrollTop = msgContainer.scrollHeight;
            });
            observer.observe(msgContainer, { childList: true, subtree: true });
        }
    });
})();
