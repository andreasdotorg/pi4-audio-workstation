/**
 * D-020 Web UI — Core application module.
 *
 * Handles SPA view switching, WebSocket lifecycle management, and
 * shared utilities. Each view module (dashboard.js, measure.js, etc.)
 * registers itself via PiAudio.registerView().
 */

"use strict";

var PiAudio = (function () {

    // -- Constants --

    var RECONNECT_BASE_MS = 500;
    var RECONNECT_MAX_MS = 10000;

    var params = new URLSearchParams(window.location.search);
    var scenario = params.get("scenario") || "A";
    var freezeTime = params.get("freeze_time") || "";

    // -- State --

    var activeView = "dashboard";
    var views = {};          // { name: { init(), onShow(), onHide() } }
    var sockets = {};        // { path: { ws, connected, attempt, onMessage, onConn } }
    var initialized = false;

    // -- View management --

    function registerView(name, module) {
        views[name] = module;
    }

    function switchView(name) {
        if (name === activeView) return;
        var viewEls = document.querySelectorAll(".view");
        var tabEls = document.querySelectorAll(".nav-tab");

        for (var i = 0; i < viewEls.length; i++) {
            viewEls[i].classList.remove("active");
        }
        for (var j = 0; j < tabEls.length; j++) {
            tabEls[j].classList.remove("active");
        }

        var target = document.getElementById("view-" + name);
        if (target) target.classList.add("active");

        var tab = document.querySelector('.nav-tab[data-view="' + name + '"]');
        if (tab) tab.classList.add("active");

        if (views[activeView] && views[activeView].onHide) {
            views[activeView].onHide();
        }
        activeView = name;
        if (views[activeView] && views[activeView].onShow) {
            views[activeView].onShow();
        }
    }

    // -- WebSocket management --

    function connectWebSocket(path, onMessage, onConn) {
        var state = { ws: null, connected: false, attempt: 0 };
        sockets[path] = state;

        function connect() {
            var proto = window.location.protocol === "https:" ? "wss:" : "ws:";
            var url = proto + "//" + window.location.host + path + "?scenario=" + scenario;
            if (freezeTime) url += "&freeze_time=" + freezeTime;
            var ws = new WebSocket(url);
            state.ws = ws;

            ws.onopen = function () {
                state.connected = true;
                state.attempt = 0;
                if (onConn) onConn(true);
                updateConnectionDot();
            };

            ws.onmessage = function (ev) {
                try {
                    onMessage(JSON.parse(ev.data));
                } catch (e) {
                    // ignore parse errors
                }
            };

            ws.onclose = function () {
                state.connected = false;
                if (onConn) onConn(false);
                updateConnectionDot();
                scheduleReconnect();
            };

            ws.onerror = function () {
                // onclose fires after this
            };
        }

        function scheduleReconnect() {
            var delay = Math.min(
                RECONNECT_BASE_MS * Math.pow(2, state.attempt),
                RECONNECT_MAX_MS
            );
            state.attempt++;
            setTimeout(connect, delay);
        }

        connect();
    }

    function updateConnectionDot() {
        var allConnected = true;
        for (var path in sockets) {
            if (!sockets[path].connected) {
                allConnected = false;
                break;
            }
        }

        var dot = document.getElementById("conn-dot");
        if (dot) dot.classList.toggle("connected", allConnected);

        var overlay = document.getElementById("reconnect-overlay");
        if (overlay) overlay.classList.toggle("visible", !allConnected);
    }

    // -- Shared DOM helpers --

    function setText(id, text, colorClass) {
        var el = document.getElementById(id);
        if (!el) return;
        el.textContent = text;
        el.className = el.className.replace(/\bc-(green|yellow|red|blue|cyan)\b/g, "").trim();
        if (colorClass) el.classList.add(colorClass);
    }

    function cpuColor(pct) {
        if (pct >= 80) return "c-red";
        if (pct >= 60) return "c-yellow";
        return "c-green";
    }

    function cpuColorRaw(pct) {
        if (pct >= 80) return "var(--red)";
        if (pct >= 60) return "var(--yellow)";
        return "var(--green)";
    }

    function tempColor(temp) {
        if (temp >= 75) return "c-red";
        if (temp >= 65) return "c-yellow";
        return "c-green";
    }

    // -- Initialization --

    function init() {
        if (initialized) return;
        initialized = true;

        var tabs = document.querySelectorAll(".nav-tab");
        for (var i = 0; i < tabs.length; i++) {
            tabs[i].addEventListener("click", function () {
                switchView(this.dataset.view);
            });
        }

        for (var name in views) {
            if (views[name].init) views[name].init();
        }

        if (views[activeView] && views[activeView].onShow) {
            views[activeView].onShow();
        }
    }

    document.addEventListener("DOMContentLoaded", init);

    // -- Public API --

    return {
        registerView: registerView,
        connectWebSocket: connectWebSocket,
        setText: setText,
        cpuColor: cpuColor,
        cpuColorRaw: cpuColorRaw,
        tempColor: tempColor,
        scenario: scenario,
    };

})();
