/**
 * D-020 Web UI -- Filter version history + rollback module (US-090 T-090-6).
 *
 * Provides a version history panel showing deployed filter versions per channel,
 * with rollback to previous versions and cleanup of old versions.
 *
 * API endpoints:
 *   GET  /api/v1/filters/versions  — list versions per channel
 *   GET  /api/v1/filters/active    — currently active filter files
 *   POST /api/v1/filters/rollback  — revert to a previous version
 *   POST /api/v1/filters/cleanup   — remove old versions
 */

"use strict";

(function () {

    var API_VERSIONS = "/api/v1/filters/versions";
    var API_ACTIVE = "/api/v1/filters/active";
    var API_ROLLBACK = "/api/v1/filters/rollback";
    var API_CLEANUP = "/api/v1/filters/cleanup";

    // -- Helpers --

    function $(id) { return document.getElementById(id); }

    function escapeHtml(s) {
        var d = document.createElement("div");
        d.textContent = s;
        return d.innerHTML;
    }

    function formatTimestamp(ts) {
        // ts format: "20260327_100341" -> "2026-03-27 10:03:41"
        if (!ts || ts.length < 15) return ts || "--";
        return ts.substring(0, 4) + "-" + ts.substring(4, 6) + "-" +
            ts.substring(6, 8) + " " + ts.substring(9, 11) + ":" +
            ts.substring(11, 13) + ":" + ts.substring(13, 15);
    }

    function setVersionStatus(text, cls) {
        var el = $("fv-status");
        if (!el) return;
        el.textContent = text;
        el.className = cls ? ("fv-status " + cls) : "fv-status";
    }

    function setVersionSpinner(visible) {
        var sp = $("fv-spinner");
        if (sp) sp.classList.toggle("hidden", !visible);
    }

    // -- Load versions --

    function loadVersions() {
        var container = $("fv-channel-list");
        var empty = $("fv-empty");
        if (!container) return;

        container.innerHTML = '<div class="fv-loading">Loading versions...</div>';
        if (empty) empty.classList.add("hidden");

        fetch(API_VERSIONS)
            .then(function (r) {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.json();
            })
            .then(function (data) {
                var channels = data.channels || {};
                var channelKeys = Object.keys(channels);

                if (channelKeys.length === 0) {
                    container.innerHTML = "";
                    if (empty) empty.classList.remove("hidden");
                    updateCleanupButton(0);
                    return;
                }

                if (empty) empty.classList.add("hidden");
                renderVersionList(channels, channelKeys, container);
            })
            .catch(function (err) {
                container.innerHTML = '<div class="fv-error">Failed to load versions: ' +
                    escapeHtml(err.message) + '</div>';
            });
    }

    function renderVersionList(channels, channelKeys, container) {
        var html = "";
        var totalInactive = 0;

        for (var c = 0; c < channelKeys.length; c++) {
            var ch = channelKeys[c];
            var versions = channels[ch];

            html += '<div class="fv-channel-group">';
            html += '<div class="fv-channel-name">' + escapeHtml(ch) +
                ' <span class="fv-version-count">(' + versions.length + ')</span></div>';

            for (var v = 0; v < versions.length; v++) {
                var ver = versions[v];
                var isActive = ver.active;
                var rowCls = "fv-version-row" + (isActive ? " fv-version-row--active" : "");

                html += '<div class="' + rowCls + '">';
                html += '<span class="fv-version-ts">' + escapeHtml(formatTimestamp(ver.timestamp)) + '</span>';
                html += '<span class="fv-version-file">' + escapeHtml(ver.file) + '</span>';

                if (isActive) {
                    html += '<span class="fv-badge fv-badge--active">ACTIVE</span>';
                } else {
                    html += '<button class="fv-rollback-btn" type="button" ' +
                        'data-ts="' + escapeHtml(ver.timestamp) + '" ' +
                        'data-file="' + escapeHtml(ver.file) + '">ROLLBACK</button>';
                    totalInactive++;
                }

                html += '</div>';
            }

            html += '</div>';
        }

        container.innerHTML = html;
        updateCleanupButton(totalInactive);

        // Bind rollback buttons
        var btns = container.querySelectorAll(".fv-rollback-btn");
        for (var i = 0; i < btns.length; i++) {
            btns[i].addEventListener("click", onRollbackClick);
        }
    }

    // -- Rollback --

    function onRollbackClick() {
        var ts = this.getAttribute("data-ts");
        var file = this.getAttribute("data-file");

        var msg = "Revert to filters from " + formatTimestamp(ts) + "?\n\n" +
            "File: " + file + "\n\n" +
            "This will update the PipeWire config to reference the older version. " +
            "PipeWire reload is required separately.";

        if (!window.confirm(msg)) return;

        setVersionSpinner(true);
        setVersionStatus("Rolling back to " + formatTimestamp(ts) + "...", "c-warning");

        fetch(API_ROLLBACK, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ version_timestamp: ts })
        })
            .then(function (r) {
                return r.json().then(function (j) { return { status: r.status, body: j }; });
            })
            .then(function (resp) {
                setVersionSpinner(false);

                if (resp.status === 200 && resp.body.rolled_back) {
                    var detail = "Rolled back " + (resp.body.files ? resp.body.files.length : 0) +
                        " file(s) to " + formatTimestamp(ts) + ".";
                    if (resp.body.conf_updated) {
                        detail += " PW config updated.";
                    }
                    detail += " Reload PipeWire to activate.";
                    setVersionStatus(detail, "c-safe");
                    showRollbackVerification(resp.body.verification);
                    loadVersions();
                } else if (resp.status === 422) {
                    setVersionStatus("Rollback rejected: " + (resp.body.detail || resp.body.reason), "c-danger");
                    showRollbackVerification(resp.body.verification);
                } else {
                    setVersionStatus("Rollback failed: " + (resp.body.detail || resp.body.error || "unknown"), "c-danger");
                }
            })
            .catch(function (err) {
                setVersionSpinner(false);
                setVersionStatus("Rollback request failed: " + err.message, "c-danger");
            });
    }

    function showRollbackVerification(verification) {
        var el = $("fv-rollback-result");
        if (!el || !verification || verification.length === 0) {
            if (el) el.classList.add("hidden");
            return;
        }

        var html = '<div class="fv-verify-title">D-009 Verification</div>';
        for (var i = 0; i < verification.length; i++) {
            var v = verification[i];
            var passCls = v.d009_pass ? "fv-badge--pass" : "fv-badge--fail";
            var passText = v.d009_pass ? "PASS" : "FAIL";
            html += '<div class="fv-verify-row">' +
                '<span class="fv-verify-file">' + escapeHtml(v.file) + '</span>' +
                '<span class="fv-badge ' + passCls + '">' + passText + '</span>' +
                '<span class="fv-verify-db">' + v.d009_peak_db + ' dB</span>' +
                '</div>';
        }
        el.innerHTML = html;
        el.classList.remove("hidden");
    }

    // -- Cleanup --

    function updateCleanupButton(inactiveCount) {
        var btn = $("fv-cleanup-btn");
        var info = $("fv-cleanup-info");
        if (btn) {
            btn.disabled = inactiveCount === 0;
        }
        if (info) {
            if (inactiveCount > 0) {
                info.textContent = inactiveCount + " inactive version(s) can be removed";
            } else {
                info.textContent = "No inactive versions to clean up";
            }
        }
    }

    function onCleanupClick() {
        var cb = $("fv-cleanup-confirm-cb");
        if (!cb || !cb.checked) {
            setVersionStatus("Check the confirmation box to proceed.", "c-warning");
            return;
        }

        if (!window.confirm("Permanently delete old filter versions? Active versions will be kept.")) {
            return;
        }

        var btn = $("fv-cleanup-btn");
        if (btn) btn.disabled = true;
        setVersionSpinner(true);
        setVersionStatus("Cleaning up old versions...", "c-warning");

        fetch(API_CLEANUP, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ confirmed: true, keep: 2 })
        })
            .then(function (r) {
                return r.json().then(function (j) { return { status: r.status, body: j }; });
            })
            .then(function (resp) {
                setVersionSpinner(false);

                if (resp.status === 200 && resp.body.cleaned) {
                    setVersionStatus(
                        "Cleaned up " + resp.body.removed_count + " old version(s). " +
                        "Keeping " + resp.body.keep + " most recent per channel.",
                        "c-safe"
                    );
                    // Reset checkbox
                    if (cb) cb.checked = false;
                    loadVersions();
                } else {
                    setVersionStatus(
                        "Cleanup failed: " + (resp.body.detail || resp.body.error || "unknown"),
                        "c-danger"
                    );
                }
                if (btn) btn.disabled = false;
            })
            .catch(function (err) {
                setVersionSpinner(false);
                setVersionStatus("Cleanup request failed: " + err.message, "c-danger");
                if (btn) btn.disabled = false;
            });
    }

    function onCleanupConfirmChange() {
        var cb = $("fv-cleanup-confirm-cb");
        var btn = $("fv-cleanup-btn");
        if (cb && btn) {
            // Only visually indicate — actual guard is in onCleanupClick
            btn.style.opacity = cb.checked ? "1" : "0.5";
        }
    }

    // -- Event binding --

    function bindEvents() {
        var cleanupBtn = $("fv-cleanup-btn");
        if (cleanupBtn) cleanupBtn.addEventListener("click", onCleanupClick);

        var cleanupCb = $("fv-cleanup-confirm-cb");
        if (cleanupCb) cleanupCb.addEventListener("change", onCleanupConfirmChange);

        var refreshBtn = $("fv-refresh-btn");
        if (refreshBtn) refreshBtn.addEventListener("click", loadVersions);
    }

    // -- View lifecycle --

    function onShow() {
        loadVersions();
    }

    function init() {
        bindEvents();
    }

    PiAudio.registerGlobalConsumer("filter-versions", {
        init: init
    });

    document.addEventListener("DOMContentLoaded", function () {
        setTimeout(function () {
            var tabs = document.querySelectorAll('.nav-tab[data-view="config"]');
            for (var i = 0; i < tabs.length; i++) {
                tabs[i].addEventListener("click", function () {
                    setTimeout(onShow, 50);
                });
            }
            var cfgView = document.getElementById("view-config");
            if (cfgView && cfgView.classList.contains("active")) {
                onShow();
            }
        }, 0);
    });

})();
