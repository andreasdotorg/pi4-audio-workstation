/**
 * D-020 Web UI — FFT spectrum analyzer module (mountain range display).
 *
 * High-resolution FFT display driven by raw PCM data from a binary WebSocket
 * (/ws/pcm). Uses a JavaScript radix-2 Cooley-Tukey FFT (default 4096-point,
 * selectable 2048/4096/8192/16384 via US-080) with Blackman-Harris window,
 * rendered as a filled "mountain range" area with amplitude-based vertical
 * heat palette on a log-frequency x-axis. Auto-ranging Y axis (US-080).
 *
 * Data flow:
 *   Pi audio -> binary WebSocket /ws/pcm (raw PCM, 4ch float32)
 *     -> JS accumulator (L+R mono sum at -6dB)
 *     -> Blackman-Harris window + radix-2 FFT (2048-point, 50% overlap)
 *     -> magnitude (dB) + exponential smoothing
 *     -> Canvas 2D renderer at requestAnimationFrame rate
 *
 * The log-frequency axis, dB scale, and color palette are designed to be
 * reusable by future spectrogram (waterfall) and measurement views
 * (TK-109, TK-110).
 *
 * Usage:
 *   PiAudioSpectrum.init("spectrum-canvas");
 *   // Legacy updateData() still accepted for backward compat with
 *   // /ws/monitoring 1/3-octave fallback, but FFT display takes priority.
 *
 * Fallback: when /ws/pcm is unavailable, displays "No live audio" on a
 * dark background. If /ws/monitoring sends 1/3-octave bands, falls back
 * to the old bar display.
 */

"use strict";

(function () {

    // =====================================================================
    // Constants — reusable across future spectrogram / measurement views
    // =====================================================================

    var SAMPLE_RATE = 48000;
    var FFT_SIZE = 4096;  // US-080: default "Balanced"

    // Shared FFT pipeline (created at init)
    var fftPipeline = null;

    // Frequency range for log x-axis
    var FREQ_LO = 30;
    var FREQ_HI = 20000;
    var LOG_LO = Math.log10(FREQ_LO);
    var LOG_HI = Math.log10(FREQ_HI);

    // dB range for y-axis (static defaults; overridden by auto-ranging)
    var DB_MIN = -60;
    var DB_MAX = 0;
    var DB_GRID_LINES = [-12, -24, -36, -48];
    var DB_GRID_LINES_MINOR = [-6, -18, -30, -42, -54];

    // US-080: Auto-ranging Y axis state
    var autoDbMin = -60;
    var autoDbMax = 0;
    var AUTO_ATTACK_MS = 200;   // fast expansion
    var AUTO_RELEASE_MS = 2000; // slow contraction
    var AUTO_MARGIN_DB = 6;     // headroom above peak
    var AUTO_FLOOR_DB = -90;    // absolute minimum floor
    var AUTO_MIN_RANGE_DB = 30; // minimum display range
    var lastAutoTime = 0;

    // Frequency labels along the bottom
    var FREQ_LABELS = [
        { freq: 30,    text: "30" },
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

    // Tiered frequency grid lines for professional audio analyzer resolution
    // Major: decade boundaries (strongest visual weight)
    var FREQ_GRID_MAJOR = [100, 1000, 10000];
    // Medium: current grid lines demoted from major (moderate weight)
    var FREQ_GRID_MEDIUM = [50, 200, 500, 2000, 5000, 20000];
    // Minor: intermediate frequencies (lightest weight)
    var FREQ_GRID_MINOR = [
        30, 40, 60, 80, 150, 300, 400, 600, 800,
        1500, 3000, 4000, 6000, 8000, 15000
    ];

    // Legacy frequency-based color stops (replaced by amplitude-based color
    // LUT in buildColorLUT). Retained for export backward compatibility.
    var COLOR_STOPS = null;

    var OUTLINE_STYLE = "rgba(220, 220, 240, 0.7)";
    var OUTLINE_WIDTH = 1.5;
    var BG_COLOR = null;       // resolved from --bg-meter at init
    var GRID_COLOR = null;     // resolved from --text-dim at init
    var LABEL_COLOR = null;    // resolved from --text-label at init

    function initSpectrumColors() {
        var cv = PiAudio.cssVar;
        BG_COLOR = cv("--bg-meter");
        GRID_COLOR = "rgba(200, 205, 214, 0.22)";
        LABEL_COLOR = cv("--text-label");
    }

    // Smoothing
    var ANALYSER_SMOOTHING = 0.3;

    // Peak hold (toggle-able)
    var PEAK_HOLD_ENABLED = true;
    var PEAK_DECAY_MS = 2000;

    // =====================================================================
    // State
    // =====================================================================

    var canvas = null;
    var ctx = null;
    var animFrame = null;

    // FFT data (filled by processFFT)
    var freqData = null;       // Float32Array(FFT_SIZE/2 + 1) for dB data

    // WebSocket
    var pcmWs = null;
    var pcmConnected = false;

    // Log-frequency lookup table: pixel x -> FFT bin index
    var freqLUT = null;        // Float32Array mapping x -> fractional bin
    var cachedW = 0;
    var cachedH = 0;

    // Layout (computed on resize)
    var plotX = 0;
    var plotY = 0;
    var plotW = 0;
    var plotH = 0;
    var labelBottomH = 14;

    // Peak hold state
    var peakEnvelope = null;   // Float32Array(plotW) — peak dB per x pixel
    var peakTimes = null;      // Float64Array(plotW) — last peak time per x pixel

    // Legacy 1/3-octave fallback
    var legacyBands = null;

    // FFT pipeline state is managed by fftPipeline (PiAudioFFT)

    // =====================================================================
    // Log-frequency utilities (reusable for TK-109, TK-110)
    // =====================================================================

    /**
     * Convert a frequency to a normalized position [0, 1] on the log axis.
     */
    function freqToNorm(freq) {
        return (Math.log10(freq) - LOG_LO) / (LOG_HI - LOG_LO);
    }

    /**
     * Convert a normalized log-axis position [0, 1] to frequency in Hz.
     */
    function normToFreq(norm) {
        return Math.pow(10, LOG_LO + norm * (LOG_HI - LOG_LO));
    }

    /**
     * Convert a frequency to the corresponding FFT bin index (fractional).
     */
    function freqToBin(freq) {
        return freq * FFT_SIZE / SAMPLE_RATE;
    }

    /**
     * Build the log-frequency LUT mapping each pixel x-position (within
     * the plot area) to a fractional FFT bin index. Called on init and resize.
     */
    function buildFreqLUT(width) {
        freqLUT = new Float32Array(width);
        var binCount = FFT_SIZE / 2;
        for (var x = 0; x < width; x++) {
            var norm = x / (width - 1);
            var freq = normToFreq(norm);
            var bin = freqToBin(freq);
            freqLUT[x] = Math.min(Math.max(bin, 0), binCount - 1);
        }
    }

    /**
     * Interpolate the dB value at a fractional FFT bin index from the
     * frequency data array.
     */
    function interpolateDB(data, fracBin) {
        var lo = Math.floor(fracBin);
        var hi = Math.min(lo + 1, data.length - 1);
        var t = fracBin - lo;
        return data[lo] * (1 - t) + data[hi] * t;
    }

    /**
     * Convert a dB value to a y-pixel position within the plot area.
     * Uses auto-ranged bounds when active.
     */
    function dbToY(db) {
        var lo = autoDbMin;
        var hi = autoDbMax;
        var clamped = Math.max(lo, Math.min(hi, db));
        var frac = (clamped - lo) / (hi - lo);
        return plotY + plotH - frac * plotH;
    }

    // =====================================================================
    // Amplitude-based color LUT (256 entries, maps dB to uniform color)
    // =====================================================================

    // Color stops: position [0..1] maps to dB range [DB_MIN..DB_MAX]
    var COLOR_LUT_STOPS = [
        { pos: 0.00, r: 20,  g: 22,  b: 55,  a: 0.80 },  // -60 dB: navy-indigo
        { pos: 0.15, r: 70,  g: 35,  b: 115, a: 0.80 },  // -51 dB: dark purple
        { pos: 0.30, r: 140, g: 50,  b: 160, a: 0.80 },  // -42 dB: magenta
        { pos: 0.50, r: 220, g: 80,  b: 40,  a: 0.80 },  // -30 dB: red-orange
        { pos: 0.65, r: 226, g: 166, b: 57,  a: 0.80 },  // -21 dB: amber
        { pos: 0.80, r: 230, g: 210, b: 60,  a: 0.80 },  // -12 dB: yellow
        { pos: 0.92, r: 255, g: 240, b: 180, a: 0.90 },  //  -5 dB: warm white
        { pos: 1.00, r: 255, g: 255, b: 255, a: 0.95 }   //   0 dB: near-white
    ];

    var colorLUT = null; // Array of 256 "rgba(r,g,b,a)" strings

    function buildColorLUT() {
        colorLUT = new Array(256);
        var stops = COLOR_LUT_STOPS;
        for (var i = 0; i < 256; i++) {
            var t = i / 255; // 0..1 normalized position
            // Find surrounding stops
            var lo = 0;
            for (var s = 1; s < stops.length; s++) {
                if (stops[s].pos >= t) { lo = s - 1; break; }
            }
            var hi = lo + 1;
            if (hi >= stops.length) { hi = stops.length - 1; lo = hi - 1; }
            var range = stops[hi].pos - stops[lo].pos;
            var frac = range > 0 ? (t - stops[lo].pos) / range : 0;
            var r = Math.round(stops[lo].r + frac * (stops[hi].r - stops[lo].r));
            var g = Math.round(stops[lo].g + frac * (stops[hi].g - stops[lo].g));
            var b = Math.round(stops[lo].b + frac * (stops[hi].b - stops[lo].b));
            var a = stops[lo].a + frac * (stops[hi].a - stops[lo].a);
            colorLUT[i] = "rgba(" + r + "," + g + "," + b + "," + a.toFixed(2) + ")";
        }
    }

    function dbToColor(db) {
        var lo = autoDbMin;
        var hi = autoDbMax;
        var clamped = Math.max(lo, Math.min(hi, db));
        var range = hi - lo;
        var idx = range > 0 ? Math.floor((clamped - lo) / range * 255) : 0;
        if (idx > 255) idx = 255;
        if (idx < 0) idx = 0;
        return colorLUT[idx];
    }

    // FFT window, FFT, and processFFT are provided by fftPipeline (PiAudioFFT)

    // =====================================================================
    // Binary WebSocket: /ws/pcm
    // =====================================================================

    var pcmReconnectTimer = null;

    function connectPcmWebSocket() {
        if (pcmWs) return;

        var proto = window.location.protocol === "https:" ? "wss:" : "ws:";
        var url = proto + "//" + window.location.host + "/ws/pcm";

        try {
            pcmWs = new WebSocket(url);
        } catch (e) {
            schedulePcmReconnect();
            return;
        }
        pcmWs.binaryType = "arraybuffer";

        pcmWs.onopen = function () {
            pcmConnected = true;
        };

        pcmWs.onmessage = function (ev) {
            if (fftPipeline) {
                fftPipeline.feedPcmMessage(ev.data, { detectGaps: true });
            }
        };

        pcmWs.onclose = function () {
            pcmConnected = false;
            pcmWs = null;
            schedulePcmReconnect();
        };

        pcmWs.onerror = function () {
            pcmConnected = false;
        };
    }

    function schedulePcmReconnect() {
        if (pcmReconnectTimer) return;
        pcmReconnectTimer = setTimeout(function () {
            pcmReconnectTimer = null;
            connectPcmWebSocket();
        }, 3000);
    }

    // =====================================================================
    // Rendering
    // =====================================================================

    function resizeCanvas() {
        if (!canvas) return;
        var rect = canvas.getBoundingClientRect();
        var dpr = window.devicePixelRatio || 1;
        var w = Math.floor(rect.width * dpr);
        var h = Math.floor(rect.height * dpr);

        if (w === cachedW && h === cachedH) return;

        canvas.width = w;
        canvas.height = h;
        ctx = canvas.getContext("2d");
        ctx.scale(dpr, dpr);

        cachedW = w;
        cachedH = h;

        // Compute layout in CSS pixels
        var cssW = rect.width;
        var cssH = rect.height;
        plotX = 30;
        plotY = 0;
        plotW = cssW - 30;
        plotH = cssH - labelBottomH;

        if (plotW > 0) {
            buildFreqLUT(Math.floor(plotW));
            if (!colorLUT) buildColorLUT();

            // Reset peak hold state on resize
            peakEnvelope = new Float32Array(Math.floor(plotW));
            peakTimes = new Float64Array(Math.floor(plotW));
            for (var i = 0; i < peakEnvelope.length; i++) {
                peakEnvelope[i] = DB_MIN;
                peakTimes[i] = 0;
            }
        }
    }

    function drawBackground() {
        var cssW = cachedW / (window.devicePixelRatio || 1);
        var cssH = cachedH / (window.devicePixelRatio || 1);

        // Background
        ctx.fillStyle = BG_COLOR;
        ctx.fillRect(0, 0, cssW, cssH);

        // --- dB grid lines: auto-ranged, 12dB major / 6dB minor ---
        // Compute grid lines dynamically from current auto-range
        var gridStep = 12;
        var lo = autoDbMin;
        var hi = autoDbMax;
        var firstMajor = Math.ceil(lo / gridStep) * gridStep;

        ctx.strokeStyle = GRID_COLOR;
        ctx.lineWidth = 1;
        for (var gd = firstMajor; gd <= hi; gd += gridStep) {
            var y = dbToY(gd);
            ctx.beginPath();
            ctx.moveTo(plotX, y);
            ctx.lineTo(plotX + plotW, y);
            ctx.stroke();
        }

        // Minor (6dB intermediates)
        ctx.strokeStyle = "rgba(200, 205, 214, 0.12)";
        ctx.lineWidth = 0.5;
        var firstMinor = Math.ceil(lo / 6) * 6;
        for (var gm = firstMinor; gm <= hi; gm += 6) {
            if (gm % gridStep === 0) continue; // skip majors
            var ym = dbToY(gm);
            ctx.beginPath();
            ctx.moveTo(plotX, ym);
            ctx.lineTo(plotX + plotW, ym);
            ctx.stroke();
        }

        // --- dB axis labels ---
        ctx.fillStyle = LABEL_COLOR;
        ctx.font = "8px monospace";
        ctx.textAlign = "right";
        ctx.textBaseline = "middle";
        for (var gl = firstMajor; gl <= hi; gl += gridStep) {
            var ly = dbToY(gl);
            ctx.fillText(gl + " dB", plotX - 3, ly);
        }
        // Always label the top and bottom of range
        ctx.fillText(Math.round(hi) + " dB", plotX - 3, dbToY(hi));
        if (Math.round(lo) !== firstMajor) {
            ctx.fillText(Math.round(lo) + " dB", plotX - 3, dbToY(lo));
        }

        // --- Vertical frequency grid: minor (lightest) ---
        ctx.strokeStyle = "rgba(200, 205, 214, 0.10)";
        ctx.lineWidth = 0.5;
        for (var km = 0; km < FREQ_GRID_MINOR.length; km++) {
            var normm = freqToNorm(FREQ_GRID_MINOR[km]);
            if (normm < 0 || normm > 1) continue;
            var xm = plotX + normm * plotW;
            ctx.beginPath();
            ctx.moveTo(xm, plotY);
            ctx.lineTo(xm, plotY + plotH);
            ctx.stroke();
        }

        // --- Vertical frequency grid: medium ---
        ctx.strokeStyle = "rgba(200, 205, 214, 0.16)";
        ctx.lineWidth = 1;
        for (var kd = 0; kd < FREQ_GRID_MEDIUM.length; kd++) {
            var normd = freqToNorm(FREQ_GRID_MEDIUM[kd]);
            if (normd < 0 || normd > 1) continue;
            var xd = plotX + normd * plotW;
            ctx.beginPath();
            ctx.moveTo(xd, plotY);
            ctx.lineTo(xd, plotY + plotH);
            ctx.stroke();
        }

        // --- Vertical frequency grid: major (strongest) ---
        ctx.strokeStyle = GRID_COLOR;
        ctx.lineWidth = 1;
        for (var k = 0; k < FREQ_GRID_MAJOR.length; k++) {
            var norm = freqToNorm(FREQ_GRID_MAJOR[k]);
            if (norm < 0 || norm > 1) continue;
            var x = plotX + norm * plotW;
            ctx.beginPath();
            ctx.moveTo(x, plotY);
            ctx.lineTo(x, plotY + plotH);
            ctx.stroke();
        }

        // --- Frequency labels along the bottom ---
        ctx.fillStyle = LABEL_COLOR;
        ctx.font = "8px monospace";
        ctx.textAlign = "center";
        ctx.textBaseline = "top";

        for (var j = 0; j < FREQ_LABELS.length; j++) {
            var lbl = FREQ_LABELS[j];
            var norm = freqToNorm(lbl.freq);
            if (norm < 0 || norm > 1) continue;
            var x = plotX + norm * plotW;
            ctx.fillText(lbl.text, x, plotY + plotH + 2);
        }
    }

    function drawMountainRange(now) {
        if (!freqData || !freqLUT || !colorLUT) return;

        var lutLen = freqLUT.length;
        if (lutLen <= 0) return;

        var baseline = plotY + plotH;

        // Per-column fill: each bin gets a uniform color based on its dB level
        for (var x = 0; x < lutLen; x++) {
            var db = interpolateDB(freqData, freqLUT[x]);
            var y = dbToY(db);
            var colH = baseline - y;

            if (colH > 0) {
                ctx.fillStyle = dbToColor(db);
                ctx.fillRect(plotX + x, y, 1, colH);
            }

            // Peak hold update
            if (PEAK_HOLD_ENABLED && peakEnvelope) {
                if (db > peakEnvelope[x] || (now - peakTimes[x]) > PEAK_DECAY_MS) {
                    peakEnvelope[x] = db;
                    peakTimes[x] = now;
                }
            }
        }

        // Outline stroke
        ctx.beginPath();
        for (var x2 = 0; x2 < lutLen; x2++) {
            var db2 = interpolateDB(freqData, freqLUT[x2]);
            var y2 = dbToY(db2);
            if (x2 === 0) {
                ctx.moveTo(plotX + x2, y2);
            } else {
                ctx.lineTo(plotX + x2, y2);
            }
        }
        ctx.strokeStyle = OUTLINE_STYLE;
        ctx.lineWidth = OUTLINE_WIDTH;
        ctx.stroke();

        // Peak hold line
        if (PEAK_HOLD_ENABLED && peakEnvelope) {
            ctx.beginPath();
            for (var x3 = 0; x3 < lutLen; x3++) {
                var peakY = dbToY(peakEnvelope[x3]);
                if (x3 === 0) {
                    ctx.moveTo(plotX + x3, peakY);
                } else {
                    ctx.lineTo(plotX + x3, peakY);
                }
            }
            ctx.strokeStyle = "rgba(255, 255, 255, 0.3)";
            ctx.lineWidth = 1;
            ctx.stroke();
        }
    }

    function drawNoSignalMessage() {
        var cssW = cachedW / (window.devicePixelRatio || 1);
        var cssH = cachedH / (window.devicePixelRatio || 1);

        ctx.fillStyle = "rgba(255, 255, 255, 0.3)";
        ctx.font = "16px monospace";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText("No live audio", cssW / 2, cssH / 2);
    }

    // US-080: Auto-ranging Y axis — track peak dB, smooth expand/contract
    function updateAutoRange(now) {
        if (!freqData) return;
        var dt = lastAutoTime > 0 ? (now - lastAutoTime) / 1000 : 0.016;
        lastAutoTime = now;
        if (dt <= 0 || dt > 1) dt = 0.016; // clamp for sanity

        // Find peak dB across all bins
        var peakDb = AUTO_FLOOR_DB;
        for (var i = 0; i < freqData.length; i++) {
            if (freqData[i] > peakDb) peakDb = freqData[i];
        }

        // Target range: floor to peak + margin, minimum AUTO_MIN_RANGE_DB
        var targetMax = Math.min(0, peakDb + AUTO_MARGIN_DB);
        var targetMin = Math.min(targetMax - AUTO_MIN_RANGE_DB, autoDbMin);
        // Don't let floor go below absolute minimum
        if (targetMin < AUTO_FLOOR_DB) targetMin = AUTO_FLOOR_DB;

        // Smoothing: fast attack (expand), slow release (contract)
        var attackCoeff = 1.0 - Math.exp(-dt / (AUTO_ATTACK_MS / 1000));
        var releaseCoeff = 1.0 - Math.exp(-dt / (AUTO_RELEASE_MS / 1000));

        // dbMax: expand up fast, contract down slow
        if (targetMax > autoDbMax) {
            autoDbMax += (targetMax - autoDbMax) * attackCoeff;
        } else {
            autoDbMax += (targetMax - autoDbMax) * releaseCoeff;
        }

        // dbMin: expand down fast, contract up slow
        if (targetMin < autoDbMin) {
            autoDbMin += (targetMin - autoDbMin) * attackCoeff;
        } else {
            autoDbMin += (targetMin - autoDbMin) * releaseCoeff;
        }

        // Ensure minimum range
        if (autoDbMax - autoDbMin < AUTO_MIN_RANGE_DB) {
            autoDbMin = autoDbMax - AUTO_MIN_RANGE_DB;
        }
    }

    function render() {
        if (!ctx || !canvas) {
            animFrame = requestAnimationFrame(render);
            return;
        }

        var now = performance.now();

        resizeCanvas();

        if (cachedW === 0 || cachedH === 0) {
            animFrame = requestAnimationFrame(render);
            return;
        }

        drawBackground();

        if (fftPipeline && fftPipeline.dirty) {
            fftPipeline.processFFT();
        }

        freqData = fftPipeline ? fftPipeline.freqData : null;

        // US-080: auto-ranging Y axis
        if (freqData && pcmConnected) {
            updateAutoRange(now);
            drawMountainRange(now);
        } else {
            drawNoSignalMessage();
        }

        animFrame = requestAnimationFrame(render);
    }

    // =====================================================================
    // Public API
    // =====================================================================

    /**
     * (Re)create the FFT pipeline with current FFT_SIZE.
     * Resets accumulator and auto-range state.
     */
    function recreatePipeline() {
        if (fftPipeline) fftPipeline.reset();
        fftPipeline = PiAudioFFT.create({
            fftSize: FFT_SIZE,
            sampleRate: SAMPLE_RATE,
            numChannels: 4,
            dbMin: DB_MIN,
            dbMax: DB_MAX,
            smoothing: ANALYSER_SMOOTHING
        });
        freqData = null;
        // Reset auto-range
        autoDbMin = DB_MIN;
        autoDbMax = DB_MAX;
        lastAutoTime = 0;
        // Rebuild freq LUT for new bin count
        if (plotW > 0) {
            buildFreqLUT(Math.floor(plotW));
        }
        // Reset peak hold
        if (peakEnvelope) {
            for (var i = 0; i < peakEnvelope.length; i++) {
                peakEnvelope[i] = autoDbMin;
                peakTimes[i] = 0;
            }
        }
    }

    function init(canvasId) {
        initSpectrumColors();
        canvas = document.getElementById(canvasId);
        if (!canvas) return;
        ctx = canvas.getContext("2d");

        resizeCanvas();

        window.addEventListener("resize", function () {
            // Invalidate cache so next frame recalculates
            cachedW = 0;
            cachedH = 0;
        });

        // Create shared FFT pipeline
        recreatePipeline();

        // US-080: Wire up FFT size selector
        var fftSelect = document.getElementById("spectrum-fft-size");
        if (fftSelect) {
            fftSelect.addEventListener("change", function () {
                var newSize = parseInt(this.value, 10);
                if (newSize && newSize !== FFT_SIZE && (newSize & (newSize - 1)) === 0) {
                    FFT_SIZE = newSize;
                    recreatePipeline();
                }
            });
        }

        // Connect WebSocket immediately (no user gesture required)
        connectPcmWebSocket();

        render();
    }

    /**
     * Legacy updateData() for backward compatibility with /ws/monitoring
     * 1/3-octave band data. When FFT display is active, this is ignored.
     */
    function updateData(bands) {
        if (!bands || bands.length !== 31) return;
        legacyBands = bands;
    }

    function destroy() {
        if (animFrame) {
            cancelAnimationFrame(animFrame);
            animFrame = null;
        }
        if (pcmWs) {
            pcmWs.close();
            pcmWs = null;
        }
        if (pcmReconnectTimer) {
            clearTimeout(pcmReconnectTimer);
            pcmReconnectTimer = null;
        }
        freqData = null;
        if (fftPipeline) fftPipeline.reset();
        autoDbMin = DB_MIN;
        autoDbMax = DB_MAX;
        lastAutoTime = 0;
    }

    // =====================================================================
    // Expose module — same interface as the old spectrum module
    // =====================================================================

    // 31 ISO 1/3-octave center frequencies (retained for backward compat)
    var BANDS = [
        20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160,
        200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600,
        2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000,
        20000
    ];
    var LABELS = ["31", "63", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"];
    var LABEL_INDICES = [2, 5, 8, 11, 14, 17, 20, 23, 26, 29];

    var spectrumApi = {
        init: init,
        updateData: updateData,
        destroy: destroy,
        BANDS: BANDS,
        LABELS: LABELS,
        LABEL_INDICES: LABEL_INDICES,
        DB_MIN: DB_MIN,
        DB_MAX: DB_MAX,
        DB_MARKS: DB_GRID_LINES,
        SMOOTHING: ANALYSER_SMOOTHING,
        PEAK_HOLD_MS: PEAK_DECAY_MS,

        // New exports for reuse by spectrogram/measurement views
        FREQ_LO: FREQ_LO,
        FREQ_HI: FREQ_HI,
        SAMPLE_RATE: SAMPLE_RATE,
        COLOR_STOPS: COLOR_STOPS,
        freqToNorm: freqToNorm,
        normToFreq: normToFreq,
        freqToBin: freqToBin
    };
    // FFT_SIZE is mutable (US-080) so expose as getter
    Object.defineProperty(spectrumApi, "FFT_SIZE", {
        get: function () { return FFT_SIZE; }
    });
    window.PiAudioSpectrum = spectrumApi;

})();
