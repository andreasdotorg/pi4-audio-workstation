/**
 * D-020 Web UI — Measure view.
 *
 * Clickable prototype for the room correction measurement workflow.
 * Static content only — no WebSocket, no backend calls.
 * Sub-tab navigation: Speakers, Calibrate, Measure, Results, Deploy.
 */

"use strict";

(function () {

    var activeTab = "speakers";

    function switchMsrTab(name) {
        if (name === activeTab) return;

        var tabs = document.querySelectorAll(".msr-tab");
        var panels = document.querySelectorAll(".msr-panel");

        for (var i = 0; i < tabs.length; i++) {
            tabs[i].classList.remove("active");
        }
        for (var j = 0; j < panels.length; j++) {
            panels[j].classList.remove("active");
        }

        var tab = document.querySelector('.msr-tab[data-msr-tab="' + name + '"]');
        if (tab) tab.classList.add("active");

        var panel = document.getElementById("msr-" + name);
        if (panel) panel.classList.add("active");

        activeTab = name;
    }

    function initTabNav() {
        var tabs = document.querySelectorAll(".msr-tab");
        for (var i = 0; i < tabs.length; i++) {
            tabs[i].addEventListener("click", function () {
                switchMsrTab(this.dataset.msrTab);
            });
        }
    }

    function initDeployDialog() {
        var btnDeploy = document.getElementById("msr-btn-deploy");
        var dialog = document.getElementById("msr-deploy-dialog");
        var btnCancel = document.getElementById("msr-btn-deploy-cancel");
        var btnConfirm = document.getElementById("msr-btn-deploy-confirm");

        if (!btnDeploy || !dialog) return;

        btnDeploy.addEventListener("click", function () {
            dialog.style.display = "flex";
        });

        if (btnCancel) {
            btnCancel.addEventListener("click", function () {
                dialog.style.display = "none";
            });
        }

        if (btnConfirm) {
            btnConfirm.addEventListener("click", function () {
                dialog.style.display = "none";
            });
        }
    }

    function initResultChannelSelect() {
        var buttons = document.querySelectorAll("[data-msr-result-ch]");
        for (var i = 0; i < buttons.length; i++) {
            buttons[i].addEventListener("click", function () {
                for (var j = 0; j < buttons.length; j++) {
                    buttons[j].classList.remove("active");
                }
                this.classList.add("active");
            });
        }
    }

    PiAudio.registerView("measure", {
        init: function () {
            initTabNav();
            initDeployDialog();
            initResultChannelSelect();
        },
        onShow: function () {},
        onHide: function () {},
    });

})();
