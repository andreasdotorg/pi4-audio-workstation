/**
 * D-020 Web UI — Dashboard view module.
 *
 * Renders the dense single-screen engineer dashboard. Subscribes to BOTH
 * /ws/monitoring and /ws/system WebSocket endpoints.
 *
 * Stage 1 layout:
 *   - Health bar (20px) — condensed system health from /ws/system
 *   - Level meters in signal-flow groups (CAPTURE, PA SENDS, MONITOR SENDS)
 *   - LUFS placeholder panel (180px right)
 */

"use strict";

(function () {

    // -- Channel configuration (signal-flow order) --

    // CAPTURE group: channels 0-7 from capture_rms/capture_peak
    // Displayed as: InL, InR (always visible), then channels 2-7 (auto-hide)
    var CAPTURE_LABELS = ["InL", "InR", "In3", "In4", "In5", "In6", "In7", "In8"];
    var CAPTURE_CHANNELS = [0, 1, 2, 3, 4, 5, 6, 7]; // indices into capture arrays

    // PA SENDS group: playback channels 0-3
    var PA_LABELS = ["ML", "MR", "S1", "S2"];
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
    var SILENT_HIDE_MS = 2000;

    var FRAC_12 = (-12 - DB_MIN) / (DB_MAX - DB_MIN);
    var FRAC_6 = (-6 - DB_MIN) / (DB_MAX - DB_MIN);

    var DB_SCALE_MARKS = [0, -6, -12, -24, -48];

    // -- State --

    var captureState = [];
    var playbackState = [];
    var captureCanvases = [];
    var paCanvases = [];
    var monitorCanvases = [];
    var captureColumns = [];
    var animating = false;
    var startTime = performance.now();

    var captureVisibility = [];

    var i;
    for (i = 0; i < 8; i++) {
        captureState.push({ rms: -120, peak: -120, peakHold: -120, peakHoldTime: 0, clipTime: 0 });
        playbackState.push({ rms: -120, peak: -120, peakHold: -120, peakHoldTime: 0, clipTime: 0 });
        captureVisibility.push({ lastAboveTime: 0, visible: true });
    }

    // -- Helpers --

    function dbToFraction(db) {
        if (db <= DB_MIN) return 0;
        if (db >= DB_MAX) return 1;
        return (db - DB_MIN) / (DB_MAX - DB_MIN);
    }

    function meterColorForDb(db) {
        if (db >= -6) return "#e53935";
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
            if (columnArray) columnArray.push(col);
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
        resizeCanvasArray(captureCanvases);
        resizeCanvasArray(paCanvases);
        resizeCanvasArray(monitorCanvases);
    }

    // -- dB scale labels --

    function updateDbScaleLabels() {
        var scaleTrack = document.querySelector("#meter-db-scale .meter-db-scale-track");
        var refCanvas = captureCanvases[0] || paCanvases[0];
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
            if (group === "capture") {
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
        var clipping = (now - state.clipTime) < CLIP_LATCH_MS;
        clipEl.classList.toggle("active", clipping);
    }

    function updateCaptureVisibility(localIdx, ch, state, now) {
        // Channels 0 and 1 always visible
        if (ch <= 1) return;
        var vis = captureVisibility[ch];
        if (state.rms > SILENT_THRESHOLD_DB || state.peak > SILENT_THRESHOLD_DB) {
            vis.lastAboveTime = now;
            if (!vis.visible) {
                vis.visible = true;
                if (captureColumns[localIdx]) captureColumns[localIdx].style.display = "";
            }
        } else if (vis.visible && (now - vis.lastAboveTime) > SILENT_HIDE_MS) {
            vis.visible = false;
            if (captureColumns[localIdx]) captureColumns[localIdx].style.display = "none";
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
            el.style.color = meterColorForDb(peak);
        }
    }

    function renderFrame() {
        if (!animating) return;
        var now = performance.now();

        var ch, idx, state;

        // Capture meters
        for (idx = 0; idx < CAPTURE_CHANNELS.length; idx++) {
            ch = CAPTURE_CHANNELS[idx];
            state = captureState[ch];
            updateCaptureVisibility(idx, ch, state, now);
            drawMeter(captureCanvases[idx], state, now, "capture");
            updateClipIndicator("meters-capture", idx, state, now);
            updateDbReadout("meters-capture-db-" + idx, state.peak);
        }

        // PA meters
        for (idx = 0; idx < PA_CHANNELS.length; idx++) {
            ch = PA_CHANNELS[idx];
            state = playbackState[ch];
            drawMeter(paCanvases[idx], state, now, "playback");
            updateClipIndicator("meters-pa", idx, state, now);
            updateDbReadout("meters-pa-db-" + idx, state.peak);
        }

        // Monitor meters
        for (idx = 0; idx < MONITOR_CHANNELS.length; idx++) {
            ch = MONITOR_CHANNELS[idx];
            state = playbackState[ch];
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
        PiAudio.setText("hb-dsp-load",
            (cdsp.processing_load * 100).toFixed(1) + "%");
        PiAudio.setText("hb-dsp-buffer", String(cdsp.buffer_level));
        PiAudio.setText("hb-dsp-clip", String(cdsp.clipped_samples),
            cdsp.clipped_samples > 0 ? "c-red" : "c-green");
        PiAudio.setText("hb-dsp-xruns", String(cdsp.xruns),
            cdsp.xruns > 0 ? "c-red" : "c-green");
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

        // Health bar: system section
        var cpuTotal = data.cpu.total_percent;
        var cpuPct = Math.min(100, cpuTotal / 4);
        PiAudio.setText("hb-cpu", cpuPct.toFixed(0) + "%",
            PiAudio.cpuColor(cpuPct));

        PiAudio.setText("hb-temp", temp.toFixed(1) + "\u00b0C",
            PiAudio.tempColor(temp));

        var mem = data.memory;
        PiAudio.setText("hb-mem",
            (mem.used_mb / 1024).toFixed(1) + "/" + (mem.total_mb / 1024).toFixed(1) + "G");

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
        buildMeterGroup("meters-capture", CAPTURE_LABELS, CAPTURE_CHANNELS,
            captureCanvases, captureColumns, "capture");
        buildMeterGroup("meters-pa", PA_LABELS, PA_CHANNELS,
            paCanvases, null, "playback");
        buildMeterGroup("meters-monitor", MONITOR_LABELS, MONITOR_CHANNELS,
            monitorCanvases, null, "playback");

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
