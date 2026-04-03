/**
 * US-126 — Persistent audio gate banner.
 *
 * Shows a full-width red banner on ALL tabs when the D-063 audio gate
 * is closed.  Listens to /ws/system for gate state at ~1 Hz.  On init,
 * fetches /api/v1/venue/current for immediate state before the first
 * WebSocket frame arrives.
 */

"use strict";

(function () {

    var banner = null;
    var isGateOpen = false;

    function updateBanner() {
        if (!banner) banner = document.getElementById("gate-banner");
        if (!banner) return;
        banner.style.display = isGateOpen ? "none" : "flex";
        document.body.classList.toggle("gate-banner-visible", !isGateOpen);
    }

    PiAudio.registerGlobalConsumer("gate-banner", {
        init: function () {
            fetch("/api/v1/venue/current")
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (data) {
                    if (data) {
                        isGateOpen = !!data.gate_open;
                        updateBanner();
                    }
                })
                .catch(function () {
                    // GM unreachable — gate is closed (safe default)
                    updateBanner();
                });
        },
        onSystem: function (data) {
            var gate = data && data.gate;
            if (!gate) return;
            var newState = !!gate.gate_open;
            if (newState !== isGateOpen) {
                isGateOpen = newState;
                updateBanner();
            }
        }
    });

})();
