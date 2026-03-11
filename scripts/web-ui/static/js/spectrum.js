/**
 * D-020 Web UI — 1/3-octave spectrum analyzer module.
 *
 * Self-contained spectrum display rendering 31 ISO bands (IEC 61260)
 * on a canvas element. Designed to be loaded via <script> tag and
 * integrated with the dashboard layout.
 *
 * Usage:
 *   PiAudioSpectrum.init("spectrum-canvas");
 *   PiAudioSpectrum.updateData([-25.3, -22.1, ...]);  // 31 floats
 */

"use strict";

(function () {

    // -- 31 ISO 1/3-octave center frequencies (IEC 61260) --

    var BANDS = [
        20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160,
        200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600,
        2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000,
        20000
    ];

    // 10 labeled frequencies and their indices into BANDS
    var LABELS = ["31", "63", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"];
    var LABEL_INDICES = [2, 5, 8, 11, 14, 17, 20, 23, 26, 29];

    // -- Scale --

    var DB_MIN = -60;
    var DB_MAX = 0;
    var DB_MARKS = [0, -6, -12, -18, -24, -36, -48, -60];

    // -- Thresholds --

    var GREEN_MAX = -12;   // below -12 dB: green
    var YELLOW_MAX = -3;   // -12 to -3 dB: yellow

    // -- Timing --

    var SMOOTHING = 0.8;
    var PEAK_HOLD_MS = 2000;

    // -- Colors --

    var COLOR_GREEN = "#4CAF50";
    var COLOR_YELLOW = "#FFEB3B";
    var COLOR_RED = "#F44336";
    var COLOR_PEAK = "#fff";
    var COLOR_BG = "#0f0f0f";
    var COLOR_GRID = "#222";
    var COLOR_LABEL = "#555";

    // -- State --

    var currentLevels = new Array(31);
    var smoothedLevels = new Array(31);
    var peakLevels = new Array(31);
    var peakTimes = new Array(31);
    var canvas = null;
    var ctx = null;
    var animFrame = null;

    var i;
    for (i = 0; i < 31; i++) {
        currentLevels[i] = DB_MIN;
        smoothedLevels[i] = DB_MIN;
        peakLevels[i] = DB_MIN;
        peakTimes[i] = 0;
    }

    // -- Helpers --

    function dbToY(db, plotY, plotH) {
        return plotY + plotH * (1 - (db - DB_MIN) / (DB_MAX - DB_MIN));
    }

    // -- Public API --

    function init(canvasId) {
        canvas = document.getElementById(canvasId);
        if (!canvas) return;
        ctx = canvas.getContext("2d");
        render();
    }

    function updateData(bands) {
        if (!bands || bands.length !== 31) return;
        for (var i = 0; i < 31; i++) {
            currentLevels[i] = bands[i];
        }
    }

    function render() {
        if (!ctx || !canvas) return;

        var now = performance.now();
        var w = canvas.width = canvas.clientWidth;
        var h = canvas.height = canvas.clientHeight;

        if (w === 0 || h === 0) {
            animFrame = requestAnimationFrame(render);
            return;
        }

        // Reserve space for labels
        var labelBottomH = 16;
        var labelLeftW = 28;
        var plotW = w - labelLeftW;
        var plotH = h - labelBottomH;
        var plotX = labelLeftW;
        var plotY = 0;

        // Clear
        ctx.fillStyle = COLOR_BG;
        ctx.fillRect(0, 0, w, h);

        // Bar dimensions
        var gap = 2;
        var barW = Math.max(10, Math.floor(plotW / 31) - gap);
        var totalBarW = (barW + gap) * 31 - gap;
        var offsetX = plotX + Math.floor((plotW - totalBarW) / 2);

        // Draw dB gridlines and labels
        ctx.strokeStyle = COLOR_GRID;
        ctx.lineWidth = 1;
        ctx.fillStyle = COLOR_LABEL;
        ctx.font = "8px monospace";
        ctx.textAlign = "right";
        ctx.textBaseline = "middle";

        var m, db, y;
        for (m = 0; m < DB_MARKS.length; m++) {
            db = DB_MARKS[m];
            y = dbToY(db, plotY, plotH);
            ctx.beginPath();
            ctx.moveTo(plotX, y);
            ctx.lineTo(w, y);
            ctx.stroke();
            ctx.fillText(db.toString(), plotX - 3, y);
        }

        // Draw bars
        var level, x, barH, barY;
        var greenTopDb, greenH;
        var yellowBottom, yellowTop, yellowBottomY, yellowTopY;
        var redBottom, redBottomY;
        var peakY;

        for (i = 0; i < 31; i++) {
            // Exponential smoothing
            smoothedLevels[i] = smoothedLevels[i] * SMOOTHING + currentLevels[i] * (1 - SMOOTHING);
            level = Math.max(DB_MIN, Math.min(DB_MAX, smoothedLevels[i]));

            // Peak hold: update if new peak or hold expired
            if (level > peakLevels[i] || now - peakTimes[i] > PEAK_HOLD_MS) {
                peakLevels[i] = level;
                peakTimes[i] = now;
            }

            x = offsetX + i * (barW + gap);
            barH = plotH * (level - DB_MIN) / (DB_MAX - DB_MIN);
            barY = plotY + plotH - barH;

            if (barH > 0) {
                // Green segment (below -12 dB)
                greenTopDb = Math.min(level, GREEN_MAX);
                greenH = plotH * (greenTopDb - DB_MIN) / (DB_MAX - DB_MIN);
                if (greenH > 0) {
                    ctx.fillStyle = COLOR_GREEN;
                    ctx.fillRect(x, plotY + plotH - greenH, barW, greenH);
                }

                // Yellow segment (-12 to -3 dB)
                if (level > GREEN_MAX) {
                    yellowBottom = GREEN_MAX;
                    yellowTop = Math.min(level, YELLOW_MAX);
                    yellowBottomY = dbToY(yellowBottom, plotY, plotH);
                    yellowTopY = dbToY(yellowTop, plotY, plotH);
                    ctx.fillStyle = COLOR_YELLOW;
                    ctx.fillRect(x, yellowTopY, barW, yellowBottomY - yellowTopY);
                }

                // Red segment (above -3 dB)
                if (level > YELLOW_MAX) {
                    redBottom = YELLOW_MAX;
                    redBottomY = dbToY(redBottom, plotY, plotH);
                    ctx.fillStyle = COLOR_RED;
                    ctx.fillRect(x, barY, barW, redBottomY - barY);
                }
            }

            // Peak hold line (1px white)
            if (peakLevels[i] > DB_MIN) {
                peakY = dbToY(peakLevels[i], plotY, plotH);
                ctx.fillStyle = COLOR_PEAK;
                ctx.fillRect(x, peakY, barW, 1);
            }
        }

        // Frequency labels (bottom)
        ctx.fillStyle = COLOR_LABEL;
        ctx.font = "8px monospace";
        ctx.textAlign = "center";
        ctx.textBaseline = "top";

        var li, idx, lx;
        for (li = 0; li < LABEL_INDICES.length; li++) {
            idx = LABEL_INDICES[li];
            lx = offsetX + idx * (barW + gap) + barW / 2;
            ctx.fillText(LABELS[li], lx, plotY + plotH + 3);
        }

        animFrame = requestAnimationFrame(render);
    }

    function destroy() {
        if (animFrame) {
            cancelAnimationFrame(animFrame);
            animFrame = null;
        }
    }

    // -- Expose module --

    window.PiAudioSpectrum = {
        init: init,
        updateData: updateData,
        destroy: destroy,
        BANDS: BANDS,
        LABELS: LABELS,
        LABEL_INDICES: LABEL_INDICES,
        DB_MIN: DB_MIN,
        DB_MAX: DB_MAX,
        DB_MARKS: DB_MARKS,
        SMOOTHING: SMOOTHING,
        PEAK_HOLD_MS: PEAK_HOLD_MS
    };

})();
