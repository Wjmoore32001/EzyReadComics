document.addEventListener("DOMContentLoaded", function () {
  const collapsibleInitialCount = 5;
  const collapsibleStepCount = 10;

  function bindClickableRow(row) {
    if (row.dataset.clickableRowBound === "1") {
      return;
    }

    row.dataset.clickableRowBound = "1";

    row.addEventListener("click", function (event) {
      if (event.target.closest("a, button, input, select, textarea, label")) {
        return;
      }

      window.location.href = row.dataset.rowUrl;
    });

    row.addEventListener("keydown", function (event) {
      if (event.key !== "Enter" && event.key !== " ") {
        return;
      }

      event.preventDefault();
      window.location.href = row.dataset.rowUrl;
    });
  }

  function pageUsesCollapsibleLists() {
    return Boolean(
      document.querySelector("[data-collapsible-lists-page], [data-my-comics-section]"),
    );
  }

  function isEmptyStateRow(row) {
    return Boolean(row.querySelector("td[colspan]"));
  }

  function makeButton(text, className) {
    const button = document.createElement("button");

    button.type = "button";
    button.className = className;
    button.textContent = text;

    return button;
  }

  function delay(milliseconds) {
    return new Promise(function (resolve) {
      window.setTimeout(resolve, milliseconds);
    });
  }

  function insertControlsAfterTable(tbody, controls) {
    const table = tbody.closest("table");
    const wrapper = table ? table.closest(".table-responsive") : null;
    const insertAfter = wrapper || table;

    if (!insertAfter || !insertAfter.parentNode) {
      return;
    }

    insertAfter.insertAdjacentElement("afterend", controls);
  }

  function bindCollapsibleTable(tbody) {
    if (tbody.dataset.collapsibleListBound === "1") {
      return;
    }

    const rows = Array.from(tbody.querySelectorAll(":scope > tr"));

    if (rows.length <= collapsibleInitialCount || rows.some(isEmptyStateRow)) {
      return;
    }

    tbody.dataset.collapsibleListBound = "1";

    let visibleCount = collapsibleInitialCount;
    let showingAll = false;

    const controls = document.createElement("div");
    controls.className = "erc-load-actions mt-3";
    controls.dataset.collapsibleListControls = "";

    const loadMoreButton = makeButton(
      "Load 10 more",
      "btn btn-outline-light erc-load-button",
    );
    const hideMoreButton = makeButton(
      "Hide 10",
      "btn btn-outline-secondary erc-hide-button",
    );
    const showAllButton = makeButton(
      "Show all",
      "btn btn-outline-light erc-load-button",
    );

    controls.appendChild(loadMoreButton);
    controls.appendChild(hideMoreButton);
    controls.appendChild(showAllButton);

    insertControlsAfterTable(tbody, controls);

    function applyVisibleRows() {
      rows.forEach(function (row, index) {
        const shouldShow = index < visibleCount;

        row.hidden = !shouldShow;
        row.classList.toggle("d-none", !shouldShow);
      });
    }

    function updateControls() {
      applyVisibleRows();

      loadMoreButton.classList.toggle(
        "d-none",
        showingAll || visibleCount >= rows.length,
      );
      hideMoreButton.classList.toggle(
        "d-none",
        showingAll || visibleCount <= collapsibleInitialCount,
      );

      showAllButton.textContent = showingAll ? "Hide" : "Show all";
    }

    loadMoreButton.addEventListener("click", function () {
      showingAll = false;
      visibleCount = Math.min(visibleCount + collapsibleStepCount, rows.length);
      updateControls();
    });

    hideMoreButton.addEventListener("click", function () {
      showingAll = false;
      visibleCount = Math.max(
        visibleCount - collapsibleStepCount,
        collapsibleInitialCount,
      );
      updateControls();
    });

    showAllButton.addEventListener("click", function () {
      if (showingAll) {
        showingAll = false;
        visibleCount = collapsibleInitialCount;
      } else {
        showingAll = true;
        visibleCount = rows.length;
      }

      updateControls();
    });

    updateControls();
  }

  function browseRowsForSection(section) {
    const target = section.querySelector("[data-load-target]");

    if (!target) {
      return [];
    }

    return Array.from(target.querySelectorAll(":scope > tr"));
  }

  function updateBrowseLoadedCount(section) {
    const loadedCount = section.querySelector("[data-loaded-count]");
    const rows = browseRowsForSection(section);

    if (loadedCount) {
      loadedCount.textContent = "Showing " + rows.length + " loaded";
    }
  }

  function browseShowAllAllowed(loadButton) {
    const kind = loadButton.dataset.kind;

    if (kind !== "issues") {
      return true;
    }

    return Boolean(loadButton.dataset.filterRunId);
  }

  async function waitUntilButtonSettles(loadButton, target, previousRowCount) {
    const startedAt = Date.now();

    while (Date.now() - startedAt < 15000) {
      await delay(50);

      const currentRowCount = target.querySelectorAll(":scope > tr").length;

      if (!loadButton.disabled) {
        return currentRowCount > previousRowCount;
      }
    }

    return target.querySelectorAll(":scope > tr").length > previousRowCount;
  }

  async function loadOneBrowsePage(loadButton, target) {
    if (loadButton.disabled || loadButton.classList.contains("d-none")) {
      return false;
    }

    const previousRowCount = target.querySelectorAll(":scope > tr").length;

    loadButton.click();

    await delay(25);

    return waitUntilButtonSettles(loadButton, target, previousRowCount);
  }

  async function loadAllBrowseRows(section, showAllButton) {
    const target = section.querySelector("[data-load-target]");
    const loadButton = section.querySelector("[data-load-more]");
    const hideButton = section.querySelector("[data-hide-more]");

    if (!target || !loadButton || loadButton.disabled) {
      return;
    }

    showAllButton.disabled = true;
    showAllButton.textContent = "Loading...";

    while (!loadButton.classList.contains("d-none")) {
      const loadedNextPage = await loadOneBrowsePage(loadButton, target);

      updateBrowseLoadedCount(section);

      if (!loadedNextPage) {
        break;
      }

      await delay(25);
    }

    loadButton.classList.add("d-none");

    if (hideButton) {
      hideButton.classList.add("d-none");
    }

    updateBrowseLoadedCount(section);

    showAllButton.dataset.showingAll = "1";
    showAllButton.disabled = false;
    showAllButton.textContent = "Hide";
  }

  function hideAllBrowseRows(section, showAllButton) {
    const target = section.querySelector("[data-load-target]");
    const loadButton = section.querySelector("[data-load-more]");
    const hideButton = section.querySelector("[data-hide-more]");

    if (!target) {
      return;
    }

    const minVisible = hideButton
      ? Number(hideButton.dataset.minVisible || String(collapsibleInitialCount))
      : collapsibleInitialCount;
    const rows = Array.from(target.querySelectorAll(":scope > tr"));

    rows.slice(minVisible).forEach(function (row) {
      row.remove();
    });

    if (loadButton) {
      loadButton.dataset.offset = String(minVisible);
      loadButton.disabled = false;
      loadButton.classList.remove("d-none");
    }

    if (hideButton) {
      hideButton.classList.add("d-none");
    }

    updateBrowseLoadedCount(section);

    showAllButton.dataset.showingAll = "";
    showAllButton.textContent = "Show all";
  }

  function bindBrowseShowAllSection(section) {
    if (section.dataset.browseShowAllBound === "1") {
      return;
    }

    const target = section.querySelector("[data-load-target]");
    const loadButton = section.querySelector("[data-load-more]");
    const hideButton = section.querySelector("[data-hide-more]");
    const actions = section.querySelector(".erc-load-actions");

    if (!target || !loadButton || !actions || !browseShowAllAllowed(loadButton)) {
      return;
    }

    if (loadButton.classList.contains("d-none")) {
      return;
    }

    section.dataset.browseShowAllBound = "1";

    const showAllButton = makeButton(
      "Show all",
      "btn btn-outline-light erc-load-button",
    );

    showAllButton.dataset.browseShowAll = "";

    if (hideButton) {
      hideButton.insertAdjacentElement("afterend", showAllButton);
    } else {
      actions.appendChild(showAllButton);
    }

    showAllButton.addEventListener("click", function () {
      if (showAllButton.dataset.showingAll === "1") {
        hideAllBrowseRows(section, showAllButton);
        return;
      }

      loadAllBrowseRows(section, showAllButton);
    });
  }

  document.querySelectorAll("[data-row-url]").forEach(bindClickableRow);

  document.querySelectorAll("[data-load-section]").forEach(bindBrowseShowAllSection);

  if (!pageUsesCollapsibleLists()) {
    return;
  }

  document
    .querySelectorAll(".erc-data-card .erc-data-table tbody")
    .forEach(bindCollapsibleTable);
});