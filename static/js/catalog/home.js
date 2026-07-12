document.addEventListener("DOMContentLoaded", function () {
    const toggles = Array.from(document.querySelectorAll("[data-home-toggle]"));
    const panels = Array.from(document.querySelectorAll("[data-home-panel]"));

    if (!toggles.length || !panels.length) {
        return;
    }

    function showPanel(panelName) {
        toggles.forEach(function (toggle) {
            const isActive = toggle.dataset.homeToggle === panelName;

            toggle.classList.toggle("active", isActive);
            toggle.setAttribute("aria-selected", isActive ? "true" : "false");
        });

        panels.forEach(function (panel) {
            const isActive = panel.dataset.homePanel === panelName;

            panel.classList.toggle("d-none", !isActive);
        });
    }

    toggles.forEach(function (toggle) {
        toggle.addEventListener("click", function () {
            showPanel(toggle.dataset.homeToggle);
        });
    });
});