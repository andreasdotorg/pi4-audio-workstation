/**
 * US-120 — Transfer function view: real-time magnitude, phase, and coherence.
 *
 * Connects to /ws/transfer-function WebSocket, receives JSON frames with
 * magnitude_db[], phase_deg[], coherence[], freq_axis[] at ~8 Hz.
 * Renders three stacked canvases: magnitude (dB), phase (deg), coherence (0-1).
 * Color codes coherence: green > 0.85, yellow 0.5-0.85, red < 0.5.
 */

"use strict";

(function () {

    // -- Constants --

    var WS_PATH = "/ws/transfer-function";
    var RECONNECT_BASE_MS = 500;
    var RECONNECT_MAX_MS = 10000;
    var FREQ_LO = 20;
    var FREQ_HI = 20000;
    var LOG_LO = Math.log10(FREQ_LO);
    var LOG_HI = Math.log10(FREQ_HI);

    // Coherence color thresholds (AC #6).
    var COH_HIGH = 0.85;
    var COH_MED = 0.5;

    // Freq grid lines for the log-frequency axis.
    var FREQ_GRID = [30, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000];
    var FREQ_LABELS = [
        { freq: 20,    text: "20" },
        { freq: 50,    text: "50" },
        { freq: 100,   text: "100" },
        { freq: 200,   text: "200" },
        { freq: 500,   text: "500" },
        { freq: 1000,  text: "1k" },
        { freq: 2000,  text: "2k" },
        { freq: 5000,  text: "5k" },
        { freq: 10000, text: "10k" },
        { freq: 20000, text: "20k" }
    ];

    // -- State --

    var ws = null;
    var wsConnected = false;
    var reconnectTimer = null;
    var reconnectDelay = RECONNECT_BASE_MS;
    var active = false;
    var animFrame = null;

    // Latest data from WebSocket.
    var lastFrame = null;

    // Canvas references.
    var magCanvas = null, magCtx = null;
    var phaseCanvas = null, phaseCtx = null;
    var cohCanvas = null, cohCtx = null;

    // Cached sizes for resize detection.
    var magW = 0, magH = 0;
    var phaseW = 0, phaseH = 0;
    var cohW = 0, cohH = 0;

    // Layout.
    var LABEL_LEFT = 38;
    var LABEL_BOTTOM = 14;

    // Colors (resolved from CSS vars once).
    var bgColor = null;
    var gridColor = "rgba(200, 205, 214, 0.18)";
    var labelColor = null;

    // -- DOM helpers --

    function $(id) { return document.getElementById(id); }

    function resolveColors() {
        if (bgColor) return;
        if (typeof PiAudio !== "undefined" && PiAudio.cssVar) {
            bgColor = PiAudio.cssVar("--bg-spectrum") || "#0e0d18";
            labelColor = PiAudio.cssVar("--text-label") || "#6a7280";
        } else {
            bgColor = "#0e0d18";
            labelColor = "#6a7280";
        }
    }

    // -- Frequency axis helpers --

    function freqToNorm(freq) {
        return (Math.log10(freq) - LOG_LO) / (LOG_HI - LOG_LO);
    }

    // -- Canvas resize --

    function resizeCanvas(canvas, ctx, oldW, oldH) {
        if (!canvas) return { ctx: ctx, w: oldW, h: oldH, changed: false };
        var rect = canvas.getBoundingClientRect();
        var dpr = window.devicePixelRatio || 1;
        var w = Math.floor(rect.width * dpr);
        var h = Math.floor(rect.height * dpr);
        if (w === oldW && h === oldH) return { ctx: ctx, w: w, h: h, changed: false };

        canvas.width = w;
        canvas.height = h;
        var newCtx = canvas.getContext("2d");
        newCtx.scale(dpr, dpr);
        return { ctx: newCtx, w: w, h: h, changed: true };
    }

    // -- Grid drawing (shared for all three canvases) --

    function drawGrid(ctx, cssW, cssH, yMin, yMax, yStep, yFormat) {
        resolveColors();
        var plotX = LABEL_LEFT;
        var plotY = 0;
        var plotW = cssW - plotX;
        var plotH = cssH - LABEL_BOTTOM;

        // Background.
        ctx.fillStyle = bgColor;
        ctx.fillRect(0, 0, cssW, cssH);

        // Vertical freq grid lines.
        ctx.strokeStyle = gridColor;
        ctx.lineWidth = 1;
        for (var i = 0; i < FREQ_GRID.length; i++) {
            var norm = freqToNorm(FREQ_GRID[i]);
            if (norm < 0 || norm > 1) continue;
            var x = plotX + norm * plotW;
            ctx.beginPath();
            ctx.moveTo(x, plotY);
            ctx.lineTo(x, plotY + plotH);
            ctx.stroke();
        }

        // Horizontal grid lines + Y labels.
        ctx.font = "9px monospace";
        ctx.fillStyle = labelColor;
        ctx.textAlign = "right";
        ctx.textBaseline = "middle";
        for (var y = yMin; y <= yMax; y += yStep) {
            var frac = (y - yMin) / (yMax - yMin);
            var py = plotY + plotH - frac * plotH;
            ctx.beginPath();
            ctx.strokeStyle = gridColor;
            ctx.moveTo(plotX, py);
            ctx.lineTo(plotX + plotW, py);
            ctx.stroke();
            ctx.fillStyle = labelColor;
            ctx.fillText(yFormat(y), plotX - 3, py);
        }

        // Freq labels at bottom.
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        for (var j = 0; j < FREQ_LABELS.length; j++) {
            var fn = freqToNorm(FREQ_LABELS[j].freq);
            if (fn < 0 || fn > 1) continue;
            ctx.fillText(FREQ_LABELS[j].text, plotX + fn * plotW, plotY + plotH + 2);
        }

        return { plotX: plotX, plotY: plotY, plotW: plotW, plotH: plotH };
    }

    // -- Magnitude rendering --

    function renderMagnitude(frame) {
        if (!magCanvas) return;
        var r = resizeCanvas(magCanvas, magCtx, magW, magH);
        magCtx = r.ctx; magW = r.w; magH = r.h;
        if (!magCtx) return;

        var dpr = window.devicePixelRatio || 1;
        var cssW = magW / dpr;
        var cssH = magH / dpr;

        // dB range for magnitude.
        var dbMin = -30, dbMax = 12, dbStep = 6;
        var layout = drawGrid(magCtx, cssW, cssH, dbMin, dbMax, dbStep,
            function (v) { return (v >= 0 ? "+" : "") + v; });

        if (!frame || !frame.magnitude_db) {
            drawCenterText(magCtx, cssW, cssH, "Waiting for data...");
            return;
        }

        var mag = frame.magnitude_db;
        var freqs = frame.freq_axis;
        var coh = frame.coherence;
        var pX = layout.plotX, pY = layout.plotY;
        var pW = layout.plotW, pH = layout.plotH;

        // Draw magnitude trace, colored by coherence.
        magCtx.lineWidth = 1.5;
        var prevX = null, prevY = null;
        for (var i = 0; i < freqs.length; i++) {
            var f = freqs[i];
            if (f < FREQ_LO || f > FREQ_HI) continue;
            var norm = freqToNorm(f);
            var x = pX + norm * pW;
            var db = Math.max(dbMin, Math.min(dbMax, mag[i]));
            var frac = (db - dbMin) / (dbMax - dbMin);
            var y = pY + pH - frac * pH;

            if (prevX !== null) {
                magCtx.beginPath();
                magCtx.strokeStyle = cohColor(coh[i]);
                magCtx.moveTo(prevX, prevY);
                magCtx.lineTo(x, y);
                magCtx.stroke();
            }
            prevX = x;
            prevY = y;
        }

        // 0 dB reference line.
        var zeroY = pY + pH - ((0 - dbMin) / (dbMax - dbMin)) * pH;
        magCtx.beginPath();
        magCtx.setLineDash([4, 3]);
        magCtx.strokeStyle = "rgba(179, 157, 219, 0.5)";
        magCtx.lineWidth = 1;
        magCtx.moveTo(pX, zeroY);
        magCtx.lineTo(pX + pW, zeroY);
        magCtx.stroke();
        magCtx.setLineDash([]);

        // Title label.
        magCtx.font = "10px monospace";
        magCtx.fillStyle = "rgba(255,255,255,0.6)";
        magCtx.textAlign = "left";
        magCtx.textBaseline = "top";
        magCtx.fillText("MAGNITUDE (dB)", pX + 4, pY + 3);
    }

    // -- Phase rendering --

    function renderPhase(frame) {
        if (!phaseCanvas) return;
        var r = resizeCanvas(phaseCanvas, phaseCtx, phaseW, phaseH);
        phaseCtx = r.ctx; phaseW = r.w; phaseH = r.h;
        if (!phaseCtx) return;

        var dpr = window.devicePixelRatio || 1;
        var cssW = phaseW / dpr;
        var cssH = phaseH / dpr;

        var yMin = -180, yMax = 180, yStep = 90;
        var layout = drawGrid(phaseCtx, cssW, cssH, yMin, yMax, yStep,
            function (v) { return v + "\u00B0"; });

        if (!frame || !frame.phase_deg) return;

        var phase = frame.phase_deg;
        var freqs = frame.freq_axis;
        var coh = frame.coherence;
        var pX = layout.plotX, pY = layout.plotY;
        var pW = layout.plotW, pH = layout.plotH;

        // Phase trace — only where coherence is acceptable (phase_deg != null).
        phaseCtx.lineWidth = 1.2;
        var prevX = null, prevY = null;
        for (var i = 0; i < freqs.length; i++) {
            var f = freqs[i];
            if (f < FREQ_LO || f > FREQ_HI) continue;
            if (phase[i] === null) {
                prevX = null;
                prevY = null;
                continue;
            }
            var norm = freqToNorm(f);
            var x = pX + norm * pW;
            var deg = Math.max(yMin, Math.min(yMax, phase[i]));
            var frac = (deg - yMin) / (yMax - yMin);
            var y = pY + pH - frac * pH;

            if (prevX !== null) {
                phaseCtx.beginPath();
                phaseCtx.strokeStyle = cohColor(coh[i]);
                phaseCtx.moveTo(prevX, prevY);
                phaseCtx.lineTo(x, y);
                phaseCtx.stroke();
            }
            prevX = x;
            prevY = y;
        }

        // 0-degree reference line.
        var zeroY = pY + pH * 0.5;
        phaseCtx.beginPath();
        phaseCtx.setLineDash([4, 3]);
        phaseCtx.strokeStyle = "rgba(179, 157, 219, 0.35)";
        phaseCtx.lineWidth = 1;
        phaseCtx.moveTo(pX, zeroY);
        phaseCtx.lineTo(pX + pW, zeroY);
        phaseCtx.stroke();
        phaseCtx.setLineDash([]);

        phaseCtx.font = "10px monospace";
        phaseCtx.fillStyle = "rgba(255,255,255,0.6)";
        phaseCtx.textAlign = "left";
        phaseCtx.textBaseline = "top";
        phaseCtx.fillText("PHASE (\u00B0)", pX + 4, pY + 3);
    }

    // -- Coherence rendering --

    function renderCoherence(frame) {
        if (!cohCanvas) return;
        var r = resizeCanvas(cohCanvas, cohCtx, cohW, cohH);
        cohCtx = r.ctx; cohW = r.w; cohH = r.h;
        if (!cohCtx) return;

        var dpr = window.devicePixelRatio || 1;
        var cssW = cohW / dpr;
        var cssH = cohH / dpr;

        var yMin = 0, yMax = 1, yStep = 0.25;
        var layout = drawGrid(cohCtx, cssW, cssH, yMin, yMax, yStep,
            function (v) { return v.toFixed(2); });

        if (!frame || !frame.coherence) return;

        var coh = frame.coherence;
        var freqs = frame.freq_axis;
        var pX = layout.plotX, pY = layout.plotY;
        var pW = layout.plotW, pH = layout.plotH;

        // Coherence threshold lines.
        var highY = pY + pH - (COH_HIGH / (yMax - yMin)) * pH;
        var medY = pY + pH - (COH_MED / (yMax - yMin)) * pH;

        cohCtx.setLineDash([3, 3]);
        cohCtx.lineWidth = 1;
        cohCtx.beginPath();
        cohCtx.strokeStyle = "rgba(121, 226, 91, 0.3)";
        cohCtx.moveTo(pX, highY);
        cohCtx.lineTo(pX + pW, highY);
        cohCtx.stroke();
        cohCtx.beginPath();
        cohCtx.strokeStyle = "rgba(226, 192, 57, 0.3)";
        cohCtx.moveTo(pX, medY);
        cohCtx.lineTo(pX + pW, medY);
        cohCtx.stroke();
        cohCtx.setLineDash([]);

        // Filled coherence area.
        cohCtx.beginPath();
        var started = false;
        for (var i = 0; i < freqs.length; i++) {
            var f = freqs[i];
            if (f < FREQ_LO || f > FREQ_HI) continue;
            var norm = freqToNorm(f);
            var x = pX + norm * pW;
            var val = Math.max(0, Math.min(1, coh[i]));
            var y = pY + pH - val * pH;
            if (!started) {
                cohCtx.moveTo(x, pY + pH);
                cohCtx.lineTo(x, y);
                started = true;
            } else {
                cohCtx.lineTo(x, y);
            }
        }
        // Close the path back to baseline.
        if (started) {
            cohCtx.lineTo(pX + pW, pY + pH);
            cohCtx.closePath();
            cohCtx.fillStyle = "rgba(121, 226, 91, 0.15)";
            cohCtx.fill();
        }

        // Coherence trace, colored by value.
        cohCtx.lineWidth = 1.5;
        var prevX = null, prevY = null;
        for (var j = 0; j < freqs.length; j++) {
            var fj = freqs[j];
            if (fj < FREQ_LO || fj > FREQ_HI) continue;
            var normJ = freqToNorm(fj);
            var xj = pX + normJ * pW;
            var valJ = Math.max(0, Math.min(1, coh[j]));
            var yj = pY + pH - valJ * pH;

            if (prevX !== null) {
                cohCtx.beginPath();
                cohCtx.strokeStyle = cohColor(coh[j]);
                cohCtx.moveTo(prevX, prevY);
                cohCtx.lineTo(xj, yj);
                cohCtx.stroke();
            }
            prevX = xj;
            prevY = yj;
        }

        cohCtx.font = "10px monospace";
        cohCtx.fillStyle = "rgba(255,255,255,0.6)";
        cohCtx.textAlign = "left";
        cohCtx.textBaseline = "top";
        cohCtx.fillText("COHERENCE", pX + 4, pY + 3);
    }

    // -- Coherence color helper --

    function cohColor(c) {
        if (c >= COH_HIGH) return "rgba(121, 226, 91, 0.9)";   // green
        if (c >= COH_MED)  return "rgba(226, 192, 57, 0.9)";   // yellow
        return "rgba(229, 69, 58, 0.7)";                        // red
    }

    function drawCenterText(ctx, w, h, text) {
        ctx.fillStyle = "rgba(255, 255, 255, 0.3)";
        ctx.font = "14px monospace";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(text, w / 2, h / 2);
    }

    // -- Status info panel --

    function updateStatus(frame) {
        var delayEl = $("tf-delay");
        var confEl = $("tf-delay-conf");
        var blocksEl = $("tf-blocks");
        var refEl = $("tf-ref-status");
        var measEl = $("tf-meas-status");

        if (!frame) {
            if (delayEl) delayEl.textContent = "--";
            if (confEl) confEl.textContent = "--";
            if (blocksEl) blocksEl.textContent = "--";
            if (refEl) { refEl.textContent = "disconnected"; refEl.className = "c-danger"; }
            if (measEl) { measEl.textContent = "disconnected"; measEl.className = "c-danger"; }
            return;
        }

        if (delayEl) delayEl.textContent = (frame.delay_ms != null)
            ? frame.delay_ms.toFixed(1) + " ms"
            : "--";
        if (confEl) confEl.textContent = (frame.delay_confidence != null)
            ? frame.delay_confidence.toFixed(0)
            : "--";
        if (blocksEl) {
            blocksEl.textContent = frame.blocks_accumulated || 0;
            if (frame.warming_up) {
                blocksEl.className = "c-warning";
            } else {
                blocksEl.className = "";
            }
        }
        if (refEl) {
            refEl.textContent = frame.ref_connected ? "connected" : "disconnected";
            refEl.className = frame.ref_connected ? "c-safe" : "c-danger";
        }
        if (measEl) {
            measEl.textContent = frame.meas_connected ? "connected" : "disconnected";
            measEl.className = frame.meas_connected ? "c-safe" : "c-danger";
        }
    }

    // -- Render loop --

    function renderLoop() {
        if (!active) { animFrame = null; return; }

        renderMagnitude(lastFrame);
        renderPhase(lastFrame);
        renderCoherence(lastFrame);
        updateStatus(lastFrame);

        animFrame = requestAnimationFrame(renderLoop);
    }

    // -- WebSocket --

    function connectWs() {
        if (ws && (ws.readyState === WebSocket.CONNECTING ||
                   ws.readyState === WebSocket.OPEN)) {
            return;
        }

        var proto = window.location.protocol === "https:" ? "wss:" : "ws:";
        var chSelect = $("tf-channel");
        var channel = chSelect ? chSelect.value : "0";
        var alphaSlider = $("tf-alpha-slider");
        var alpha = alphaSlider ? alphaSlider.value : "0.125";

        var url = proto + "//" + window.location.host + WS_PATH +
            "?ref_channel=" + channel +
            "&meas_channel=" + channel +
            "&alpha=" + alpha;

        // Append scenario param if present.
        if (typeof PiAudio !== "undefined" && PiAudio.scenario) {
            url += "&scenario=" + PiAudio.scenario;
        }

        ws = new WebSocket(url);

        ws.onopen = function () {
            wsConnected = true;
            reconnectDelay = RECONNECT_BASE_MS;
            updateWsStatus("connected");
        };

        ws.onmessage = function (ev) {
            try {
                lastFrame = JSON.parse(ev.data);
            } catch (e) { /* ignore */ }
        };

        ws.onclose = function () {
            wsConnected = false;
            ws = null;
            updateWsStatus("disconnected");
            scheduleReconnect();
        };

        ws.onerror = function () {
            // onclose fires after
        };
    }

    function disconnectWs() {
        if (reconnectTimer) {
            clearTimeout(reconnectTimer);
            reconnectTimer = null;
        }
        if (ws) {
            ws.onclose = null;
            ws.close();
            ws = null;
        }
        wsConnected = false;
        updateWsStatus("disconnected");
    }

    function scheduleReconnect() {
        if (reconnectTimer || !active) return;
        reconnectTimer = setTimeout(function () {
            reconnectTimer = null;
            if (active) connectWs();
        }, Math.min(reconnectDelay, RECONNECT_MAX_MS));
        reconnectDelay *= 2;
    }

    function sendCmd(cmd) {
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        ws.send(JSON.stringify(cmd));
    }

    function updateWsStatus(status) {
        var el = $("tf-ws-status");
        if (!el) return;
        if (status === "connected") {
            el.textContent = "streaming";
            el.className = "c-safe";
        } else {
            el.textContent = "disconnected";
            el.className = "c-danger";
        }
    }

    // -- Controls --

    function initAlphaSlider() {
        var slider = $("tf-alpha-slider");
        var display = $("tf-alpha-value");
        if (!slider) return;

        slider.addEventListener("input", function () {
            var val = parseFloat(this.value);
            if (display) display.textContent = val.toFixed(3);
            // Send alpha change to server.
            sendCmd({ cmd: "set_alpha", alpha: val });
        });
    }

    function initChannelSelect() {
        var select = $("tf-channel");
        if (!select) return;
        select.addEventListener("change", function () {
            // Changing channel requires reconnecting with new query params.
            if (active) {
                disconnectWs();
                lastFrame = null;
                connectWs();
            }
        });
    }

    function initResetButton() {
        var btn = $("tf-reset-btn");
        if (!btn) return;
        btn.addEventListener("click", function () {
            sendCmd({ cmd: "reset" });
            lastFrame = null;
            btn.classList.add("flash-reset");
            setTimeout(function () {
                btn.classList.remove("flash-reset");
            }, 300);
        });
    }

    // -- View lifecycle --

    function initView() {
        initAlphaSlider();
        initChannelSelect();
        initResetButton();

        window.addEventListener("resize", function () {
            magW = 0; magH = 0;
            phaseW = 0; phaseH = 0;
            cohW = 0; cohH = 0;
        });
    }

    function showView() {
        active = true;
        magCanvas = $("tf-mag-canvas");
        phaseCanvas = $("tf-phase-canvas");
        cohCanvas = $("tf-coh-canvas");
        magW = 0; magH = 0;
        phaseW = 0; phaseH = 0;
        cohW = 0; cohH = 0;

        connectWs();
        animFrame = requestAnimationFrame(renderLoop);
    }

    function hideView() {
        active = false;
        if (animFrame) {
            cancelAnimationFrame(animFrame);
            animFrame = null;
        }
        disconnectWs();
        lastFrame = null;
    }

    // -- Register --

    PiAudio.registerView("tf", {
        init: initView,
        onShow: showView,
        onHide: hideView
    });

})();
