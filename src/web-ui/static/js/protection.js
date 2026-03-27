/* Driver Protection Status display (US-092 / T-092-7).
 *
 * Polls GET /api/v1/thermal/protection every 2 s and renders per-channel
 * cards showing thermal headroom, limiter state, HPF status, and excursion
 * margin (when T/S data is available in the speaker identity).
 */
"use strict";

(function () {
    const POLL_MS = 2000;
    let _timer = null;

    const noProfileEl = () => document.getElementById("prot-no-profile");
    const channelsEl = () => document.getElementById("prot-channels");

    function isConfigVisible() {
        var el = document.getElementById("view-config");
        return el && el.classList.contains("active");
    }

    function statusClass(status) {
        if (status === "limit" || status === "over_ceiling") return "prot-danger";
        if (status === "warning") return "prot-warning";
        return "prot-safe";
    }

    function fmtDb(v) {
        if (v == null) return "--";
        const n = Number(v);
        if (!isFinite(n)) return "--";
        return (n >= 0 ? "+" : "") + n.toFixed(1);
    }

    function fmtWatts(v) {
        if (v == null) return "--";
        return Number(v).toFixed(1) + " W";
    }

    function fmtPct(v) {
        if (v == null) return "--";
        return Number(v).toFixed(0) + "%";
    }

    function renderCard(ch) {
        const thermal = ch.thermal || {};
        const limiter = ch.limiter || {};
        const tStatus = thermal.status || "unknown";
        const cls = statusClass(tStatus);

        let hpfHtml = "";
        if (ch.hpf_active) {
            hpfHtml = '<span class="prot-badge prot-badge-safe">HPF ' + ch.hpf_hz + ' Hz</span>';
        } else {
            hpfHtml = '<span class="prot-badge prot-badge-dim">NO HPF</span>';
        }

        let limiterHtml = "";
        if (limiter.is_limiting) {
            limiterHtml = '<span class="prot-badge prot-badge-warning">LIM ' +
                fmtDb(limiter.reduction_db) + ' dB</span>';
        }

        let overrideHtml = "";
        if (limiter.override) {
            overrideHtml = '<span class="prot-badge prot-badge-override">OVERRIDE</span>';
        }

        let excursionHtml = "";
        if (ch.xmax_mm != null) {
            excursionHtml =
                '<div class="prot-kv"><span class="prot-k">Xmax</span><span class="prot-v">' +
                Number(ch.xmax_mm).toFixed(1) + ' mm</span></div>';
        }
        if (ch.has_ts_data) {
            excursionHtml +=
                '<div class="prot-kv"><span class="prot-k">Excursion</span>' +
                '<span class="prot-v prot-badge-safe">T/S ready</span></div>';
        } else if (ch.xmax_mm != null) {
            excursionHtml +=
                '<div class="prot-kv"><span class="prot-k">Excursion</span>' +
                '<span class="prot-v prot-badge-dim">no T/S data</span></div>';
        }

        let portHtml = "";
        if (ch.port_tuning_hz != null) {
            portHtml =
                '<div class="prot-kv"><span class="prot-k">Port</span><span class="prot-v">' +
                Number(ch.port_tuning_hz).toFixed(0) + ' Hz</span></div>';
        }

        return '<div class="prot-card ' + cls + '">' +
            '<div class="prot-card-header">' +
                '<span class="prot-ch-name">' + escHtml(ch.name) + '</span>' +
                '<span class="prot-ch-role">' + escHtml(ch.role || "") + '</span>' +
            '</div>' +
            '<div class="prot-card-badges">' + hpfHtml + limiterHtml + overrideHtml + '</div>' +
            '<div class="prot-card-body">' +
                '<div class="prot-kv"><span class="prot-k">Power</span><span class="prot-v">' +
                    fmtWatts(thermal.power_watts) + '</span></div>' +
                '<div class="prot-kv"><span class="prot-k">Ceiling</span><span class="prot-v">' +
                    fmtWatts(thermal.ceiling_watts) + '</span></div>' +
                '<div class="prot-kv"><span class="prot-k">Headroom</span><span class="prot-v">' +
                    fmtDb(thermal.headroom_db) + ' dB</span></div>' +
                '<div class="prot-kv"><span class="prot-k">Load</span><span class="prot-v">' +
                    fmtPct(thermal.pct_of_ceiling) + '</span></div>' +
                excursionHtml + portHtml +
            '</div>' +
        '</div>';
    }

    function escHtml(s) {
        const d = document.createElement("div");
        d.textContent = s;
        return d.innerHTML;
    }

    async function poll() {
        if (!isConfigVisible()) return;
        try {
            const resp = await fetch("/api/v1/thermal/protection");
            if (!resp.ok) {
                showNoProfile("Protection API unavailable (HTTP " + resp.status + ")");
                return;
            }
            const data = await resp.json();
            render(data);
        } catch (e) {
            showNoProfile("Protection API error");
        }
    }

    function showNoProfile(msg) {
        const np = noProfileEl();
        const ch = channelsEl();
        if (!np || !ch) return;
        np.textContent = msg || "No speaker profile active.";
        np.classList.remove("hidden");
        ch.classList.add("hidden");
    }

    function render(data) {
        const np = noProfileEl();
        const ch = channelsEl();
        if (!np || !ch) return;

        if (!data.channels || data.channels.length === 0) {
            showNoProfile();
            return;
        }

        np.classList.add("hidden");
        ch.classList.remove("hidden");

        const html = data.channels.map(renderCard).join("");
        ch.innerHTML = html;
    }

    // Start polling — poll() self-checks config tab visibility
    _timer = setInterval(poll, POLL_MS);
})();
