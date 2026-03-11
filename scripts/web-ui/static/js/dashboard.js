/**
 * D-020 Web UI — Dashboard view module.
 *
 * Renders the dense single-screen engineer dashboard. Subscribes to BOTH
 * /ws/monitoring and /ws/system WebSocket endpoints.
 *
 * Stage 1 layout:
 *   - Health bar (20px) — condensed system health from /ws/system
 *   - Level meters in signal-flow groups (MAIN, PA SENDS, MONITOR SENDS, SOURCE)
 *   - SPL hero + LUFS panel (180px right)
 */

"use strict";

(function () {

    // -- Channel configuration (signal-flow order) --

    // MAIN group: capture channels 0-1
    var MAIN_LABELS = ["ML", "MR"];
    var MAIN_CHANNELS = [0, 1]; // indices into capture arrays

    // SOURCE group: capture channels 2-7
    var SOURCE_LABELS = ["Src3", "Src4", "Src5", "Src6", "Src7", "Src8"];
    var SOURCE_CHANNELS = [2, 3, 4, 5, 6, 7]; // indices into capture arrays

    // PA SENDS group: playback channels 0-3
    var PA_LABELS = ["SatL", "SatR", "S1", "S2"];
    var PA_CHANNELS = [0, 1, 2, 3]; // indices into playback arrays

    // MONITOR SENDS group: playback channels 4-7
    var MONITOR_LABELS = ["EL", "ER", "IL", "IR"];
    var MONITOR_CHANNELS = [4, 5, 6, 7]; // indices into playback arrays

    // -- Constants --

    var DB_MIN = -60;
    var DB_MAX = 0;
    var PEAK_HOLD_MS = 1500;
    var CLIP_LATCH_MS = 3000;
    var CLIP_THRESHOLD_DB = -0.5;
    var SILENT_THRESHOLD_DB = -60;
    var SILENT_DIM_MS = 5000;

    var FRAC_12 = (-12 - DB_MIN) / (DB_MAX - DB_MIN);
    var FRAC_6 = (-6 - DB_MIN) / (DB_MAX - DB_MIN);

    var DB_SCALE_MARKS = [0, -6, -12, -24, -48];

    // -- State --

    var captureState = [];
    var playbackState = [];
    var mainCanvases = [];
    var sourceCanvases = [];
    var paCanvases = [];
    var monitorCanvases = [];
    // Column references for all groups (for dim toggling)
    var mainColumns = [];
    var sourceColumns = [];
    var paColumns = [];
    var monitorColumns = [];
    var animating = false;
    var startTime = performance.now();

    // Per-channel last-signal-time tracking for dim logic
    // Indexed by group key + local index
    var lastSignalTime = {};

    var i;
    for (i = 0; i < 8; i++) {
        captureState.push({ rms: -120, peak: -120, peakHold: -120, peakHoldTime: 0, clipTime: 0 });
        playbackState.push({ rms: -120, peak: -120, peakHold: -120, peakHoldTime: 0, clipTime: 0 });
    }

    // -- Helpers --

    function dbToFraction(db) {
        if (db <= DB_MIN) return 0;
        if (db >= DB_MAX) return 1;
        return (db - DB_MIN) / (DB_MAX - DB_MIN);
    }

    function dbReadoutColor(db) {
        if (db >= -3) return "#e53935";
        if (db >= -12) return "#f9a825";
        return "#43a047";
    }

    function formatUptime(seconds) {
        if (!seconds || seconds < 0) return "--";
        var h = Math.floor(seconds / 3600);
        var m = Math.floor((seconds % 3600) / 60);
        if (h > 0) return h + "h" + (m < 10 ? "0" : "") + m + "m";
        return m + "m";
    }

    // -- Meter building --

    function buildMeterGroup(containerId, labels, channels, canvasArray, columnArray, source) {
        var container = document.getElementById(containerId);
        if (!container) return;
        container.innerHTML = "";

        for (var idx = 0; idx < labels.length; idx++) {
            var col = document.createElement("div");
            col.className = "meter-channel";

            var clipInd = document.createElement("div");
            clipInd.className = "meter-clip-indicator";
            clipInd.id = containerId + "-clip-" + idx;
            clipInd.textContent = "CLIP";

            var wrapper = document.createElement("div");
            wrapper.className = "meter-canvas-wrapper";

            var canvas = document.createElement("canvas");
            canvas.dataset.channel = String(channels[idx]);
            canvas.dataset.source = source;
            wrapper.appendChild(canvas);

            // "NO SIG" overlay inside the canvas wrapper
            var noSig = document.createElement("div");
            noSig.className = "meter-no-signal";
            noSig.textContent = "NO SIG";
            wrapper.appendChild(noSig);

            var lbl = document.createElement("div");
            lbl.className = "meter-label";
            lbl.textContent = labels[idx];

            var dbVal = document.createElement("div");
            dbVal.className = "meter-db-value";
            dbVal.id = containerId + "-db-" + idx;
            dbVal.textContent = "-inf";

            col.appendChild(clipInd);
            col.appendChild(wrapper);
            col.appendChild(lbl);
            col.appendChild(dbVal);
            container.appendChild(col);

            canvasArray.push({ canvas: canvas, ctx: null, w: 0, h: 0 });
            columnArray.push(col);

            // Initialize last-signal-time to startTime so channels start active
            lastSignalTime[containerId + "-" + idx] = startTime;
        }
    }

    function resizeCanvasArray(arr) {
        for (var i = 0; i < arr.length; i++) {
            var mc = arr[i];
            var rect = mc.canvas.getBoundingClientRect();
            var dpr = window.devicePixelRatio || 1;
            mc.canvas.width = Math.floor(rect.width * dpr);
            mc.canvas.height = Math.floor(rect.height * dpr);
            mc.ctx = mc.canvas.getContext("2d");
            mc.ctx.scale(dpr, dpr);
            mc.w = rect.width;
            mc.h = rect.height;
        }
    }

    function resizeAll() {
        resizeCanvasArray(mainCanvases);
        resizeCanvasArray(sourceCanvases);
        resizeCanvasArray(paCanvases);
        resizeCanvasArray(monitorCanvases);
    }

    // -- dB scale labels --

    function updateDbScaleLabels() {
        var scaleTrack = document.querySelector("#meter-db-scale .meter-db-scale-track");
        var refCanvas = mainCanvases[0] || paCanvases[0];
        if (!scaleTrack || !refCanvas || !refCanvas.h) return;
        scaleTrack.innerHTML = "";
        var h = refCanvas.h;
        for (var i = 0; i < DB_SCALE_MARKS.length; i++) {
            var db = DB_SCALE_MARKS[i];
            var frac = dbToFraction(db);
            var y = h - frac * h;
            var label = document.createElement("span");
            label.className = "db-scale-label";
            label.textContent = db === 0 ? "0" : String(db);
            label.style.top = y + "px";
            scaleTrack.appendChild(label);
        }
    }

    // -- Canvas drawing --

    function drawMeter(mc, state, now, group) {
        var ctx = mc.ctx;
        if (!ctx) return;
        var w = mc.w;
        var h = mc.h;

        ctx.clearRect(0, 0, w, h);

        ctx.fillStyle = "#0f0f0f";
        ctx.fillRect(0, 0, w, h);

        // RMS fill
        var rmsFrac = dbToFraction(state.rms);
        var rmsH = rmsFrac * h;
        if (rmsH > 0.5) {
            var grad = ctx.createLinearGradient(0, h, 0, 0);
            if (group === "main") {
                // White/silver theme for MAIN meters
                grad.addColorStop(0, "#888");
                grad.addColorStop(Math.min(FRAC_12, 1), "#ccc");
                grad.addColorStop(Math.min(FRAC_6, 1), "#f9a825");
                grad.addColorStop(1, "#e53935");
            } else if (group === "capture") {
                grad.addColorStop(0, "#00838f");
                grad.addColorStop(Math.min(FRAC_12, 1), "#00838f");
                grad.addColorStop(Math.min(FRAC_12 + 0.01, 1), "#00acc1");
                grad.addColorStop(Math.min(FRAC_6, 1), "#00acc1");
                grad.addColorStop(Math.min(FRAC_6 + 0.01, 1), "#e53935");
                grad.addColorStop(1, "#e53935");
            } else {
                grad.addColorStop(0, "#43a047");
                grad.addColorStop(Math.min(FRAC_12, 1), "#43a047");
                grad.addColorStop(Math.min(FRAC_12 + 0.01, 1), "#f9a825");
                grad.addColorStop(Math.min(FRAC_6, 1), "#f9a825");
                grad.addColorStop(Math.min(FRAC_6 + 0.01, 1), "#e53935");
                grad.addColorStop(1, "#e53935");
            }
            ctx.fillStyle = grad;
            ctx.fillRect(0, h - rmsH, w, rmsH);
        }

        // Peak indicator
        var peakFrac = dbToFraction(state.peak);
        if (peakFrac > 0) {
            var peakY = h - peakFrac * h;
            ctx.fillStyle = "rgba(255,255,255,0.5)";
            ctx.fillRect(0, peakY, w, 1);
        }

        // Peak hold
        var holdFrac = dbToFraction(state.peakHold);
        if (holdFrac > 0 && (now - state.peakHoldTime) < PEAK_HOLD_MS) {
            var holdY = h - holdFrac * h;
            ctx.fillStyle = "#ffffff";
            ctx.fillRect(1, holdY, w - 2, 2);
        }

        // dB scale lines
        ctx.fillStyle = "rgba(255,255,255,0.08)";
        var markers = [-48, -36, -24, -12, -6];
        for (var m = 0; m < markers.length; m++) {
            var my = h - dbToFraction(markers[m]) * h;
            ctx.fillRect(0, my, w, 1);
        }
    }

    function updateClipIndicator(containerId, idx, state, now) {
        var clipEl = document.getElementById(containerId + "-clip-" + idx);
        if (!clipEl) return;
        // F-1 FIX: Only show CLIP when peak actually exceeded threshold
        // and latch for CLIP_LATCH_MS. clipTime is only set when peak >= CLIP_THRESHOLD_DB.
        // If clipTime is 0 (never clipped), never show active.
        var clipping = state.clipTime > 0 && (now - state.clipTime) < CLIP_LATCH_MS;
        clipEl.classList.toggle("active", clipping);
    }

    // -- Silent channel dimming (applies to ALL groups) --

    function updateChannelDim(containerId, localIdx, columns, state, now) {
        var key = containerId + "-" + localIdx;
        var col = columns[localIdx];
        if (!col) return;

        if (state.peak > SILENT_THRESHOLD_DB) {
            // Signal present — record time and instantly remove silent
            lastSignalTime[key] = now;
            if (col.classList.contains("silent")) {
                col.classList.remove("silent");
            }
        } else {
            // No signal — check if dim threshold exceeded
            var lastSig = lastSignalTime[key] || startTime;
            if ((now - lastSig) > SILENT_DIM_MS) {
                if (!col.classList.contains("silent")) {
                    col.classList.add("silent");
                }
            }
        }
    }

    function updateDbReadout(id, peak) {
        var el = document.getElementById(id);
        if (!el) return;
        if (peak <= DB_MIN) {
            el.textContent = "-inf";
            el.style.color = "";
        } else {
            el.textContent = peak.toFixed(1);
            // F-6 FIX: Use correct thresholds: green < -12, yellow -12 to -3, red > -3
            el.style.color = dbReadoutColor(peak);
        }
    }

    function renderFrame() {
        if (!animating) return;
        var now = performance.now();

        var ch, idx, state;

        // MAIN meters (capture ch 0-1)
        for (idx = 0; idx < MAIN_CHANNELS.length; idx++) {
            ch = MAIN_CHANNELS[idx];
            state = captureState[ch];
            updateChannelDim("meters-main", idx, mainColumns, state, now);
            drawMeter(mainCanvases[idx], state, now, "main");
            updateClipIndicator("meters-main", idx, state, now);
            updateDbReadout("meters-main-db-" + idx, state.peak);
        }

        // SOURCE meters (capture ch 2-7)
        for (idx = 0; idx < SOURCE_CHANNELS.length; idx++) {
            ch = SOURCE_CHANNELS[idx];
            state = captureState[ch];
            updateChannelDim("meters-source", idx, sourceColumns, state, now);
            drawMeter(sourceCanvases[idx], state, now, "capture");
            updateClipIndicator("meters-source", idx, state, now);
            updateDbReadout("meters-source-db-" + idx, state.peak);
        }

        // PA meters
        for (idx = 0; idx < PA_CHANNELS.length; idx++) {
            ch = PA_CHANNELS[idx];
            state = playbackState[ch];
            updateChannelDim("meters-pa", idx, paColumns, state, now);
            drawMeter(paCanvases[idx], state, now, "playback");
            updateClipIndicator("meters-pa", idx, state, now);
            updateDbReadout("meters-pa-db-" + idx, state.peak);
        }

        // Monitor meters
        for (idx = 0; idx < MONITOR_CHANNELS.length; idx++) {
            ch = MONITOR_CHANNELS[idx];
            state = playbackState[ch];
            updateChannelDim("meters-monitor", idx, monitorColumns, state, now);
            drawMeter(monitorCanvases[idx], state, now, "playback");
            updateClipIndicator("meters-monitor", idx, state, now);
            updateDbReadout("meters-monitor-db-" + idx, state.peak);
        }

        requestAnimationFrame(renderFrame);
    }

    // -- Data handlers --

    function updateChannel(state, rms, peak, now) {
        state.rms = rms;
        state.peak = peak;
        if (peak > state.peakHold || (now - state.peakHoldTime) > PEAK_HOLD_MS) {
            state.peakHold = peak;
            state.peakHoldTime = now;
        }
        if (peak >= CLIP_THRESHOLD_DB) {
            state.clipTime = now;
        }
    }

    function onMonitoringData(data) {
        var now = performance.now();

        for (var ch = 0; ch < 8; ch++) {
            updateChannel(captureState[ch], data.capture_rms[ch], data.capture_peak[ch], now);
            updateChannel(playbackState[ch], data.playback_rms[ch], data.playback_peak[ch], now);
        }

        // Health bar: DSP section (from monitoring data, higher update rate)
        var cdsp = data.camilladsp;
        PiAudio.setText("hb-dsp-state", cdsp.state,
            cdsp.state === "Running" ? "c-green" : "c-red");

        // DSP Load gauge
        var dspLoadPct = cdsp.processing_load * 100;
        PiAudio.setGauge("hb-dsp-load-gauge",
            dspLoadPct,
            dspLoadPct.toFixed(1) + "%",
            PiAudio.dspLoadColorRaw(dspLoadPct));

        PiAudio.setText("hb-dsp-buffer", String(cdsp.buffer_level));
        PiAudio.setText("hb-dsp-clip", String(cdsp.clipped_samples),
            cdsp.clipped_samples > 0 ? "c-red" : "c-green");
        PiAudio.setText("hb-dsp-xruns", String(cdsp.xruns),
            cdsp.xruns > 0 ? "c-red" : "c-green");

        // SPL (optional field)
        if (data.spl != null) {
            var heroVal = document.getElementById("spl-value");
            if (heroVal) {
                heroVal.textContent = Math.round(data.spl);
                heroVal.style.color = PiAudio.splColorRaw(data.spl);
            }
            PiAudio.setText("hb-spl", Math.round(data.spl), PiAudio.splColor(data.spl));
        }
    }

    function onSystemData(data) {
        // Nav bar: mode badge
        var mode = data.mode.toUpperCase();
        var badge = document.getElementById("mode-badge");
        if (badge) badge.textContent = mode;

        // Nav bar: temperature
        var temp = data.cpu.temperature;
        PiAudio.setText("nav-temp", temp.toFixed(1) + "\u00b0C",
            PiAudio.tempColor(temp));

        // Health bar: CPU gauge
        var cpuTotal = data.cpu.total_percent;
        var cpuPct = Math.min(100, cpuTotal / 4);
        PiAudio.setGauge("hb-cpu-gauge",
            cpuPct,
            cpuPct.toFixed(0) + "%",
            PiAudio.cpuColorRaw(cpuPct));

        // Health bar: Temperature gauge (map 30-85C to 0-100%)
        var tempPct = Math.min(100, Math.max(0, (temp - 30) / (85 - 30) * 100));
        PiAudio.setGauge("hb-temp-gauge",
            tempPct,
            temp.toFixed(0) + "\u00b0",
            PiAudio.tempColorRaw(temp));

        // Health bar: Memory gauge
        var mem = data.memory;
        var memPct = (mem.used_mb / mem.total_mb) * 100;
        PiAudio.setGauge("hb-mem-gauge",
            memPct,
            memPct.toFixed(0) + "%",
            PiAudio.memColorRaw(memPct));

        PiAudio.setText("hb-pw-quantum", "Q" + data.pipewire.quantum);

        // FIFO status
        var sched = data.pipewire.scheduling;
        var pwFifo = sched.pipewire_policy === "SCHED_FIFO";
        var cdspFifo = sched.camilladsp_policy === "SCHED_FIFO";
        var fifoText = sched.pipewire_priority + "/" + sched.camilladsp_priority;
        var fifoColor = (pwFifo && cdspFifo) ? "c-green" : "c-red";
        PiAudio.setText("hb-fifo", fifoText, fifoColor);

        // Uptime
        var elapsed = (performance.now() - startTime) / 1000;
        PiAudio.setText("hb-uptime", formatUptime(Math.floor(elapsed)));
    }

    // -- View lifecycle --

    function init() {
        buildMeterGroup("meters-main", MAIN_LABELS, MAIN_CHANNELS,
            mainCanvases, mainColumns, "capture");
        buildMeterGroup("meters-source", SOURCE_LABELS, SOURCE_CHANNELS,
            sourceCanvases, sourceColumns, "capture");
        buildMeterGroup("meters-pa", PA_LABELS, PA_CHANNELS,
            paCanvases, paColumns, "playback");
        buildMeterGroup("meters-monitor", MONITOR_LABELS, MONITOR_CHANNELS,
            monitorCanvases, monitorColumns, "playback");

        window.addEventListener("resize", function () {
            resizeAll();
            updateDbScaleLabels();
        });

        requestAnimationFrame(function () {
            resizeAll();
            updateDbScaleLabels();
        });

        // Connect both WebSocket endpoints
        PiAudio.connectWebSocket("/ws/monitoring", onMonitoringData, function () {});
        PiAudio.connectWebSocket("/ws/system", onSystemData, function () {});
    }

    function onShow() {
        resizeAll();
        updateDbScaleLabels();
        animating = true;
        requestAnimationFrame(renderFrame);
    }

    function onHide() {
        animating = false;
    }

    // -- Register --

    PiAudio.registerView("dashboard", {
        init: init,
        onShow: onShow,
        onHide: onHide,
    });

})();
