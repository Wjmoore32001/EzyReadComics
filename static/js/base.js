document.addEventListener("DOMContentLoaded", function () {
  function readStoredBoolean(key, fallbackValue) {
    try {
      const storedValue = window.localStorage.getItem(key);

      if (storedValue === null) {
        return fallbackValue;
      }

      return storedValue === "1";
    } catch (error) {
      return fallbackValue;
    }
  }

  function storeBoolean(key, value) {
    try {
      window.localStorage.setItem(key, value ? "1" : "0");
    } catch (error) {
      // Keep the toggle working when browser storage is unavailable.
    }
  }

  function isFiltersPanel(panel) {
    const title = panel.querySelector(
      ":scope > .card-body > .erc-section-header .erc-section-title",
    );

    return Boolean(title && title.textContent.trim() === "Filters");
  }

  function bindFilterPanelToggle(panel, panelIndex) {
    if (panel.dataset.filterPanelToggleBound === "1") {
      return;
    }

    const cardBody = panel.querySelector(":scope > .card-body");
    const header = cardBody
      ? cardBody.querySelector(":scope > .erc-section-header")
      : null;
    const title = header ? header.querySelector(".erc-section-title") : null;

    if (!cardBody || !header || !title) {
      return;
    }

    const filterContent = Array.from(cardBody.children).filter(function (child) {
      return child !== header;
    });

    if (filterContent.length === 0) {
      return;
    }

    panel.dataset.filterPanelToggleBound = "1";

    const storageKey =
      "erc-filter-panel-visible:" +
      window.location.pathname +
      ":" +
      String(panelIndex);
    const toggleId = "erc-filter-panel-toggle-" + String(panelIndex);
    const controls = document.createElement("div");
    const switchWrapper = document.createElement("div");
    const toggle = document.createElement("input");
    const label = document.createElement("label");

    controls.className = "d-flex flex-wrap align-items-center gap-3";

    Array.from(header.children).forEach(function (child) {
      if (child !== title) {
        controls.appendChild(child);
      }
    });

    switchWrapper.className = "form-check form-switch mb-0";
    toggle.className = "form-check-input";
    toggle.type = "checkbox";
    toggle.id = toggleId;

    label.className = "form-check-label erc-muted";
    label.htmlFor = toggleId;
    label.textContent = "Show filters";

    switchWrapper.appendChild(toggle);
    switchWrapper.appendChild(label);
    controls.appendChild(switchWrapper);
    header.appendChild(controls);

    function applyVisibility(shouldShow, savePreference) {
      toggle.checked = shouldShow;
      toggle.setAttribute("aria-expanded", shouldShow ? "true" : "false");
      header.classList.toggle("mb-0", !shouldShow);

      filterContent.forEach(function (element) {
        element.hidden = !shouldShow;
        element.classList.toggle("d-none", !shouldShow);
      });

      if (savePreference) {
        storeBoolean(storageKey, shouldShow);
      }
    }

    toggle.addEventListener("change", function () {
      applyVisibility(toggle.checked, true);
    });

    applyVisibility(readStoredBoolean(storageKey, true), false);
  }

  Array.from(document.querySelectorAll(".erc-page-shell > .erc-panel"))
    .filter(isFiltersPanel)
    .forEach(bindFilterPanelToggle);
});
