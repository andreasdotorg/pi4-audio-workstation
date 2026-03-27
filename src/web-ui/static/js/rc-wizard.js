/**
 * D-020 Web UI -- Room Correction wizard extension (US-097).
 *
 * Extends the Measure tab with room correction pipeline UI:
 *   - SETUP: profile selector, mic check, pre-flight status
 *   - FILTER_GEN: pipeline steps, per-channel filter cards
 *   - DEPLOY: file copy + config install + reload progress
 *   - VERIFY: D-009, min-phase, format, crossover sum, loaded checks
 *
 * Backend endpoints are not yet available -- uses mock data for scaffold.
 * When the backend is ready, replace mock responses with real fetch calls.
 */

"use strict";

(function () {

    var PROFILES_URL = "/api/v1/filters/profiles";
    var SPEAKER_PROFILE_URL = "/api/v1/speakers/profiles/";

    // Cached speaker data from the selected profile.
    var profileSpeakers = null;

    // -- DOM helpers --

    function $(id) { return document.getElementById(id); }

    function escapeHtml(s) {
        var d = document.createElement("div");
        d.textContent = s;
        return d.innerHTML;
    }

    // -- Setup screen enhancements --

    function loadSetupProfiles() {
        var sel = $("mw-setup-profile");
        if (!sel) return;

        fetch(PROFILES_URL)
            .then(function (r) {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.json();
            })
            .then(function (data) {
                var profiles = data.profiles || [];
                sel.innerHTML = "";
                var def = document.createElement("option");
                def.value = "";
                def.textContent = profiles.length ? "-- select profile --" : "No profiles found";
                sel.appendChild(def);
                for (var i = 0; i < profiles.length; i++) {
                    var opt = document.createElement("option");
                    opt.value = profiles[i];
                    opt.textContent = profiles[i];
                    sel.appendChild(opt);
                }
                updatePreflightProfile();
            })
            .catch(function () {
                sel.innerHTML = '<option value="">Failed to load</option>';
                updatePreflightProfile();
            });
    }

    function updatePreflightProfile() {
        var sel = $("mw-setup-profile");
        var indicator = document.querySelector("#rc-pf-profile .rc-pf-indicator");
        if (!sel || !indicator) return;
        if (sel.value) {
            indicator.textContent = "OK";
            indicator.className = "rc-pf-indicator c-safe";
            fetchProfileSpeakers(sel.value);
        } else {
            indicator.textContent = "--";
            indicator.className = "rc-pf-indicator c-warning";
            profileSpeakers = null;
        }
    }

    function fetchProfileSpeakers(profileName) {
        fetch(SPEAKER_PROFILE_URL + encodeURIComponent(profileName))
            .then(function (r) {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.json();
            })
            .then(function (data) {
                profileSpeakers = data.speakers || null;
                updateChannelPreview();
            })
            .catch(function () {
                profileSpeakers = null;
                updateChannelPreview();
            });
    }

    function updateChannelPreview() {
        var list = $("mw-setup-channels");
        if (!list) return;
        var channels = buildChannelsFromProfile();
        if (!channels || channels.length === 0) return;
        list.innerHTML = "";
        for (var i = 0; i < channels.length; i++) {
            var ch = channels[i];
            var item = document.createElement("div");
            item.className = "mw-setup-channel-item";
            item.textContent = "Ch" + ch.index + " " + ch.name;
            list.appendChild(item);
        }
    }

    function runPreflightChecks() {
        // Mic check: mock as connected (real: query /api/v1/system or ws/system)
        var micInd = document.querySelector("#rc-pf-mic .rc-pf-indicator");
        if (micInd) {
            micInd.textContent = "OK";
            micInd.className = "rc-pf-indicator c-safe";
        }

        // GM mode: mock as ready
        var gmInd = document.querySelector("#rc-pf-gm .rc-pf-indicator");
        if (gmInd) {
            gmInd.textContent = "OK";
            gmInd.className = "rc-pf-indicator c-safe";
        }

        // Amps: manual confirmation required
        var ampsInd = document.querySelector("#rc-pf-amps .rc-pf-indicator");
        if (ampsInd) {
            ampsInd.textContent = "MANUAL";
            ampsInd.className = "rc-pf-indicator c-warning";
        }

        updatePreflightProfile();

        var statusEl = $("mw-preflight-status");
        if (statusEl) {
            statusEl.textContent = "Ready (verify amps are on before starting)";
            statusEl.className = "mw-preflight-status c-safe";
        }
    }

    // -- Pipeline step updates --

    function setPipelineStep(stepId, status, cls) {
        var step = $(stepId);
        if (!step) return;
        var statusEl = step.querySelector(".rc-step-status");
        if (statusEl) {
            statusEl.textContent = status;
            statusEl.className = "rc-step-status" + (cls ? " " + cls : "");
        }
        step.className = "rc-step" + (cls === "c-safe" ? " rc-step--done" :
            cls === "c-warning" ? " rc-step--active" : "");
    }

    // Called by measure.js updatePipelineStage when filter_gen messages arrive
    function onFilterGenProgress(msg) {
        if (!msg) return;

        // Map backend pipeline steps to our UI steps
        var stepMap = {
            "averaging": "rc-step-average",
            "target_curve": "rc-step-target",
            "inversion": "rc-step-inversion",
            "crossover": "rc-step-crossover",
            "minimum_phase": "rc-step-minphase",
            "export": "rc-step-export"
        };

        if (msg.step && stepMap[msg.step]) {
            if (msg.phase === "complete") {
                setPipelineStep(stepMap[msg.step], "DONE", "c-safe");
            } else if (msg.phase === "error") {
                setPipelineStep(stepMap[msg.step], "FAIL", "c-danger");
            } else {
                setPipelineStep(stepMap[msg.step], "...", "c-warning");
            }
        }

        // Channel cards from result data
        if (msg.channels) {
            renderChannelCards(msg.channels);
        }
    }

    function renderChannelCards(channels) {
        var container = $("rc-channel-cards");
        if (!container) return;
        container.innerHTML = "";

        var keys = Object.keys(channels);
        for (var i = 0; i < keys.length; i++) {
            var name = keys[i];
            var ch = channels[name];
            var card = document.createElement("div");
            card.className = "rc-channel-card";

            var header = document.createElement("div");
            header.className = "rc-card-header";
            header.innerHTML =
                '<span class="rc-card-name">' + escapeHtml(name) + '</span>' +
                '<span class="rc-card-badge ' +
                    (ch.all_pass ? 'rc-card-badge--pass' : 'rc-card-badge--fail') + '">' +
                    (ch.all_pass ? 'PASS' : 'FAIL') + '</span>';

            var body = document.createElement("div");
            body.className = "rc-card-body";
            body.innerHTML =
                '<div class="rc-card-row">' +
                    '<span>D-009 peak</span>' +
                    '<span class="' + (ch.d009_pass ? 'c-safe' : 'c-danger') + '">' +
                        (ch.d009_peak_db != null ? ch.d009_peak_db + ' dB' : '--') + '</span>' +
                '</div>' +
                '<div class="rc-card-row">' +
                    '<span>Min phase</span>' +
                    '<span class="' + (ch.min_phase_pass ? 'c-safe' : 'c-danger') + '">' +
                        (ch.min_phase_pass ? 'PASS' : 'FAIL') + '</span>' +
                '</div>' +
                '<div class="rc-card-row">' +
                    '<span>Format</span>' +
                    '<span class="' + (ch.format_pass ? 'c-safe' : 'c-danger') + '">' +
                        (ch.format_pass ? 'OK' : 'FAIL') + '</span>' +
                '</div>';

            if (ch.path) {
                body.innerHTML +=
                    '<div class="rc-card-path">' + escapeHtml(ch.path) + '</div>';
            }

            card.appendChild(header);
            card.appendChild(body);
            container.appendChild(card);
        }
    }

    // -- Deploy screen updates --

    function onDeployProgress(msg) {
        if (!msg) return;

        var stepMap = {
            "copy": "rc-deploy-step-copy",
            "config": "rc-deploy-step-conf",
            "reload": "rc-deploy-step-reload"
        };

        if (msg.step && stepMap[msg.step]) {
            if (msg.phase === "complete") {
                setPipelineStep(stepMap[msg.step], "DONE", "c-safe");
            } else if (msg.phase === "error") {
                setPipelineStep(stepMap[msg.step], "FAIL", "c-danger");
            } else {
                setPipelineStep(stepMap[msg.step], "...", "c-warning");
            }
        }
    }

    // -- Verify screen updates --

    function onVerifyProgress(msg) {
        if (!msg) return;

        // Update individual check results
        if (msg.checks) {
            var checkMap = {
                "d009": "rc-verify-d009",
                "minimum_phase": "rc-verify-minphase",
                "format": "rc-verify-format",
                "crossover_sum": "rc-verify-xover",
                "filter_loaded": "rc-verify-loaded"
            };
            for (var key in msg.checks) {
                var elId = checkMap[key];
                if (!elId) continue;
                var el = $(elId);
                if (!el) continue;
                var result = el.querySelector(".rc-verify-result");
                if (result) {
                    var passed = msg.checks[key];
                    result.textContent = passed ? "PASS" : "FAIL";
                    result.className = "rc-verify-result " + (passed ? "c-safe" : "c-danger");
                }
            }
        }

        // Per-channel D-009 details
        if (msg.channel_details) {
            var container = $("rc-verify-channels");
            if (container) {
                container.innerHTML = '<div class="rc-verify-ch-title">Per-Channel D-009</div>';
                for (var ch in msg.channel_details) {
                    var d = msg.channel_details[ch];
                    var row = document.createElement("div");
                    row.className = "rc-verify-ch-row";
                    row.innerHTML =
                        '<span class="rc-verify-ch-name">' + escapeHtml(ch) + '</span>' +
                        '<span class="rc-verify-ch-peak ' + (d.passed ? 'c-safe' : 'c-danger') + '">' +
                            d.peak_db + ' dB</span>' +
                        '<span class="rc-verify-ch-result ' + (d.passed ? 'c-safe' : 'c-danger') + '">' +
                            (d.passed ? 'PASS' : 'FAIL') + '</span>';
                    container.appendChild(row);
                }
            }
        }
    }

    // -- Mock simulation (remove when backend is ready) --

    function simulatePipelineMock() {
        var steps = ["average", "target", "inversion", "crossover", "minphase", "export"];
        var idx = 0;

        function tick() {
            if (idx >= steps.length) {
                // Pipeline done - show mock channel cards
                renderChannelCards({
                    "left_hp": { all_pass: true, d009_pass: true, d009_peak_db: -1.2, min_phase_pass: true, format_pass: true, path: "/tmp/output/combined_left_hp.wav" },
                    "right_hp": { all_pass: true, d009_pass: true, d009_peak_db: -1.1, min_phase_pass: true, format_pass: true, path: "/tmp/output/combined_right_hp.wav" },
                    "sub1_lp": { all_pass: true, d009_pass: true, d009_peak_db: -0.8, min_phase_pass: true, format_pass: true, path: "/tmp/output/combined_sub1_lp.wav" },
                    "sub2_lp": { all_pass: true, d009_pass: true, d009_peak_db: -0.9, min_phase_pass: true, format_pass: true, path: "/tmp/output/combined_sub2_lp.wav" }
                });
                return;
            }
            var stepId = "rc-step-" + steps[idx];
            setPipelineStep(stepId, "...", "c-warning");
            setTimeout(function () {
                setPipelineStep(stepId, "DONE", "c-safe");
                idx++;
                setTimeout(tick, 300);
            }, 500);
        }

        tick();
    }

    // -- Event binding --

    function bindEvents() {
        var profileSel = $("mw-setup-profile");
        if (profileSel) {
            profileSel.addEventListener("change", updatePreflightProfile);
        }
    }

    // -- Integration hooks --
    // These are called from measure.js via the global window.RCWizard object.

    /**
     * Build a channels array from the cached profile speakers dict.
     * Returns null if no profile speakers data is available.
     *
     * Each entry: {index, name, target_spl_db, thermal_ceiling_dbfs}
     * - Subwoofers get -14 dBFS ceiling (higher headroom needed).
     * - All other roles get -20 dBFS ceiling.
     */
    function buildChannelsFromProfile() {
        if (!profileSpeakers) return null;
        var channels = [];
        var keys = Object.keys(profileSpeakers);
        for (var i = 0; i < keys.length; i++) {
            var key = keys[i];
            var spk = profileSpeakers[key];
            var isSubwoofer = spk.role === "subwoofer";
            channels.push({
                index: spk.channel,
                name: key.replace(/_/g, " "),
                target_spl_db: 75.0,
                thermal_ceiling_dbfs: isSubwoofer ? -14.0 : -20.0
            });
        }
        // Sort by channel index for consistent ordering.
        channels.sort(function (a, b) { return a.index - b.index; });
        return channels;
    }

    window.RCWizard = {
        onFilterGenProgress: onFilterGenProgress,
        onDeployProgress: onDeployProgress,
        onVerifyProgress: onVerifyProgress,
        simulatePipelineMock: simulatePipelineMock,
        loadSetupProfiles: loadSetupProfiles,
        runPreflightChecks: runPreflightChecks,
        buildChannelsFromProfile: buildChannelsFromProfile
    };

    // -- Init --

    function init() {
        bindEvents();
    }

    PiAudio.registerGlobalConsumer("rc-wizard", {
        init: init
    });

    // Hook into measure tab to load profiles when setup screen shows.
    document.addEventListener("DOMContentLoaded", function () {
        setTimeout(function () {
            var tabs = document.querySelectorAll('.nav-tab[data-view="measure"]');
            for (var i = 0; i < tabs.length; i++) {
                tabs[i].addEventListener("click", function () {
                    setTimeout(function () {
                        loadSetupProfiles();
                        runPreflightChecks();
                    }, 100);
                });
            }
        }, 0);
    });

})();
