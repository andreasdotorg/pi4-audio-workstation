/**
 * US-113 Phase 4 — Venue selection + audio gate controls.
 *
 * Adds to the Config tab:
 *   - Venue dropdown (from list_venues RPC via REST)
 *   - Venue detail display (gains, delays, coefficients per channel)
 *   - Apply button (calls set_venue)
 *   - Gate open/close controls with safety confirmation
 *   - Gate status indicator
 *
 * Data flow:
 *   venue.js -> /api/v1/venue/* -> venue_routes.py -> GraphManager RPC
 */

"use strict";

(function () {

    var currentVenue = null;   // active venue name
    var gateOpen = false;
    var hasPending = false;

    // -- Helpers --

    function setStatus(id, text, cssClass) {
        var el = document.getElementById(id);
        if (!el) return;
        el.textContent = text;
        el.className = cssClass ? ("cfg-status " + cssClass) : "cfg-status";
    }

    function multToDb(mult) {
        if (mult <= 0) return "-INF";
        var db = 20 * Math.log10(mult);
        if (db <= -100) return "-INF";
        return db.toFixed(1);
    }

    // -- Gate UI update --

    function updateGateUI() {
        var indicator = document.getElementById("gate-indicator");
        var venueLabel = document.getElementById("gate-venue-label");
        var openBtn = document.getElementById("gate-open-btn");
        var closeBtn = document.getElementById("gate-close-btn");

        if (indicator) {
            indicator.textContent = gateOpen ? "OPEN" : "CLOSED";
            indicator.className = "gate-indicator " + (gateOpen ? "gate-open" : "gate-closed");
        }
        if (venueLabel) {
            venueLabel.textContent = currentVenue
                ? ("Venue: " + currentVenue)
                : "No venue loaded";
        }
        if (openBtn) {
            openBtn.disabled = gateOpen || !currentVenue;
        }
        if (closeBtn) {
            closeBtn.disabled = !gateOpen;
        }
    }

    // -- Venue detail display --

    function renderVenueDetail(data) {
        var container = document.getElementById("venue-detail");
        if (!container) return;

        if (!data || !data.channels) {
            container.innerHTML = "";
            return;
        }

        var html = '<div class="venue-detail-name">' + escHtml(data.name) + '</div>';
        if (data.description) {
            html += '<div class="venue-detail-desc">' + escHtml(data.description) + '</div>';
        }
        html += '<table class="venue-channel-table">';
        html += '<tr><th>Ch</th><th>Gain</th><th>Delay</th><th>Coefficients</th></tr>';

        for (var i = 0; i < data.channels.length; i++) {
            var ch = data.channels[i];
            var dbStr = multToDb(ch.gain_mult) + " dB";
            html += '<tr>';
            html += '<td class="venue-ch-key">' + escHtml(ch.key) + '</td>';
            html += '<td class="venue-ch-gain">' + escHtml(dbStr) + '</td>';
            html += '<td class="venue-ch-delay">' + ch.delay_ms.toFixed(1) + ' ms</td>';
            html += '<td class="venue-ch-coeff">' + escHtml(ch.coefficients) + '</td>';
            html += '</tr>';
        }
        html += '</table>';
        container.innerHTML = html;
    }

    function escHtml(str) {
        var div = document.createElement("div");
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }

    // -- API calls --

    function fetchVenueList() {
        fetch("/api/v1/venue/list")
            .then(function (r) {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.json();
            })
            .then(function (data) {
                var sel = document.getElementById("venue-select");
                if (!sel) return;

                // Keep the placeholder option
                sel.innerHTML = '<option value="">-- select venue --</option>';
                var venues = data.venues || [];
                for (var i = 0; i < venues.length; i++) {
                    var opt = document.createElement("option");
                    opt.value = venues[i].name;
                    opt.textContent = venues[i].display_name || venues[i].name;
                    sel.appendChild(opt);
                }

                // Pre-select current venue if one is active
                if (currentVenue) {
                    sel.value = currentVenue;
                }
            })
            .catch(function (err) {
                setStatus("venue-status", "Failed to load venues: " + err.message, "c-danger");
            });
    }

    function fetchGateStatus() {
        fetch("/api/v1/venue/current")
            .then(function (r) {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.json();
            })
            .then(function (data) {
                currentVenue = data.venue || null;
                gateOpen = data.gate_open || false;
                hasPending = data.has_pending_gains || false;
                updateGateUI();

                // Pre-select current venue in dropdown
                var sel = document.getElementById("venue-select");
                if (sel && currentVenue) {
                    sel.value = currentVenue;
                }
            })
            .catch(function (err) {
                setStatus("gate-status", "Failed to get gate status: " + err.message, "c-danger");
            });
    }

    function fetchVenueDetail(name) {
        if (!name) {
            renderVenueDetail(null);
            return;
        }
        fetch("/api/v1/venue/detail?name=" + encodeURIComponent(name))
            .then(function (r) {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.json();
            })
            .then(function (data) {
                renderVenueDetail(data);
            })
            .catch(function (err) {
                setStatus("venue-status", "Failed to load detail: " + err.message, "c-danger");
                renderVenueDetail(null);
            });
    }

    function applyVenue() {
        var sel = document.getElementById("venue-select");
        var name = sel ? sel.value : "";
        if (!name) return;

        setStatus("venue-status", "Loading venue...", "c-warning");
        var applyBtn = document.getElementById("venue-apply-btn");
        if (applyBtn) applyBtn.disabled = true;

        fetch("/api/v1/venue/select", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({venue: name})
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.ok) {
                    currentVenue = name;
                    gateOpen = data.gate_open || false;
                    hasPending = data.has_pending_gains || false;
                    updateGateUI();
                    setStatus("venue-status", "Venue '" + name + "' loaded", "c-safe");
                    fetchVenueDetail(name);
                } else {
                    setStatus("venue-status", "Error: " + (data.detail || data.error || "unknown"), "c-danger");
                }
                if (applyBtn) applyBtn.disabled = false;
            })
            .catch(function (err) {
                setStatus("venue-status", "Request failed: " + err.message, "c-danger");
                if (applyBtn) applyBtn.disabled = false;
            });
    }

    function openGate() {
        // Safety confirmation dialog
        var msg = "Open the audio gate?\n\n" +
            "This will apply venue gains to the signal chain. " +
            "Ensure amplifiers are at safe levels before proceeding.\n\n" +
            "Venue: " + (currentVenue || "none");
        if (!window.confirm(msg)) return;

        setStatus("gate-status", "Opening gate...", "c-warning");
        var openBtn = document.getElementById("gate-open-btn");
        if (openBtn) openBtn.disabled = true;

        fetch("/api/v1/venue/gate/open", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: "{}"
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.ok) {
                    gateOpen = true;
                    updateGateUI();
                    setStatus("gate-status", "Gate opened", "c-safe");
                } else {
                    setStatus("gate-status", "Error: " + (data.detail || data.error || "unknown"), "c-danger");
                    if (openBtn) openBtn.disabled = false;
                }
            })
            .catch(function (err) {
                setStatus("gate-status", "Request failed: " + err.message, "c-danger");
                if (openBtn) openBtn.disabled = false;
            });
    }

    function closeGate() {
        setStatus("gate-status", "Closing gate...", "c-warning");
        var closeBtn = document.getElementById("gate-close-btn");
        if (closeBtn) closeBtn.disabled = true;

        fetch("/api/v1/venue/gate/close", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: "{}"
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.ok) {
                    gateOpen = false;
                    updateGateUI();
                    setStatus("gate-status", "Gate closed", "c-safe");
                } else {
                    setStatus("gate-status", "Error: " + (data.detail || "unknown"), "c-danger");
                }
            })
            .catch(function (err) {
                setStatus("gate-status", "Request failed: " + err.message, "c-danger");
                if (closeBtn) closeBtn.disabled = false;
            });
    }

    // -- Event binding --

    function bindEvents() {
        var sel = document.getElementById("venue-select");
        if (sel) {
            sel.addEventListener("change", function () {
                var name = sel.value;
                var applyBtn = document.getElementById("venue-apply-btn");
                if (applyBtn) applyBtn.disabled = !name;

                // Show detail preview on selection change
                fetchVenueDetail(name);
            });
        }

        var applyBtn = document.getElementById("venue-apply-btn");
        if (applyBtn) {
            applyBtn.addEventListener("click", applyVenue);
        }

        var openBtn = document.getElementById("gate-open-btn");
        if (openBtn) {
            openBtn.addEventListener("click", openGate);
        }

        var closeBtn = document.getElementById("gate-close-btn");
        if (closeBtn) {
            closeBtn.addEventListener("click", closeGate);
        }
    }

    // -- View lifecycle --

    function onShow() {
        fetchVenueList();
        fetchGateStatus();
    }

    // -- Register as part of the config view --
    // venue.js loads after config.js, so the "config" view is already
    // registered. We wrap its onShow to also fetch venue/gate data.

    PiAudio.registerGlobalConsumer("venue-config", {
        init: function () {
            bindEvents();
        },
        onSystem: function (data) {
            // Gate events arrive via the system WebSocket
            var gate = data && data.gate;
            if (!gate) return;
            var type = gate.type || gate.event;
            if (type === "gate_opened") {
                gateOpen = true;
                currentVenue = gate.venue || currentVenue;
                updateGateUI();
            } else if (type === "gate_closed") {
                gateOpen = false;
                updateGateUI();
                if (gate.reason && gate.reason !== "close_gate RPC") {
                    setStatus("gate-status",
                        "Gate closed: " + gate.reason, "c-warning");
                }
            }
        }
    });

    // Wrap the config view's onShow so venue data is fetched when the
    // Config tab becomes visible. This runs after config.js has already
    // registered the "config" view via PiAudio.registerView().
    (function wrapConfigOnShow() {
        // Access the internal view registry via the switchView mechanism:
        // PiAudio doesn't expose views directly, so we use a one-time
        // MutationObserver on the config view div to detect when it
        // becomes active (gets the "active" class).
        var configDiv = document.getElementById("view-config");
        if (!configDiv) {
            // DOM not ready yet — defer
            document.addEventListener("DOMContentLoaded", wrapConfigOnShow);
            return;
        }
        var observer = new MutationObserver(function (mutations) {
            for (var i = 0; i < mutations.length; i++) {
                if (mutations[i].attributeName === "class" &&
                    configDiv.classList.contains("active")) {
                    onShow();
                    return;
                }
            }
        });
        observer.observe(configDiv, { attributes: true });

        // Also fire if config is already the active view
        if (configDiv.classList.contains("active")) {
            onShow();
        }
    })();

})();
