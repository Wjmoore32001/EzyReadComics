(function (global) {
  "use strict";

  if (global.EzyReadComicsComicLists) {
    return;
  }

  const UNFOLLOW_STATUS_VALUE = "__unfollow__";
  let controllerInitialized = false;

  const FILTER_DATA_KEYS = [
    ["filterPublisherId", "publisher"],
    ["filterRunId", "run"],
    ["filterIssueId", "issue"],
    ["filterVolumeId", "volume"],
    ["filterOneShotId", "one_shot"],
  ];

  function onReady(callback) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", callback, { once: true });
      return;
    }

    callback();
  }

  function clearElement(element) {
    while (element.firstChild) {
      element.removeChild(element.firstChild);
    }
  }

  function getCsrfToken() {
    const csrfInput = document.querySelector("input[name='csrfmiddlewaretoken']");

    if (csrfInput) {
      return csrfInput.value;
    }

    const csrfSource = document.querySelector("[data-csrf-token]");
    return csrfSource ? csrfSource.dataset.csrfToken || "" : "";
  }

  function currentNextValue() {
    return window.location.pathname + window.location.search;
  }

  function createHiddenInput(name, value) {
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = name;
    input.value = value;
    return input;
  }

  function getDatasetCount(source, name) {
    const value = Number(source.dataset[name] || "0");
    return Number.isNaN(value) ? 0 : value;
  }

  function issueLabel(count) {
    return count === 1 ? "issue" : "issues";
  }

  function statusLabel(status) {
    const labels = {
      planned: "Planned to read",
      reading: "Reading",
      read: "Read",
    };

    return labels[status] || status;
  }

  function applyRunStatusMessage(status, totalIssues, trackedIssues) {
    if (totalIssues <= 0) {
      return "";
    }

    const label = statusLabel(status);

    if (status === "read") {
      if (trackedIssues >= totalIssues) {
        return `Mark all ${totalIssues} followed ${issueLabel(totalIssues)} in this run as Read too?`;
      }

      if (trackedIssues === 0) {
        return `You are not following any issues in this run yet. Follow all ${totalIssues} ${issueLabel(totalIssues)} and mark them Read too?`;
      }

      const missingIssues = totalIssues - trackedIssues;
      return `You follow ${trackedIssues} of ${totalIssues} ${issueLabel(totalIssues)} in this run. Follow the remaining ${missingIssues} and mark all ${totalIssues} as Read too?`;
    }

    if (trackedIssues >= totalIssues) {
      return `Also change all ${totalIssues} followed ${issueLabel(totalIssues)} in this run to ${label}?`;
    }

    if (trackedIssues === 0) {
      return `Also follow all ${totalIssues} ${issueLabel(totalIssues)} in this run and set them to ${label}?`;
    }

    const missingIssues = totalIssues - trackedIssues;
    return `You follow ${trackedIssues} of ${totalIssues} ${issueLabel(totalIssues)} in this run. Follow the remaining ${missingIssues} and set all ${totalIssues} to ${label}?`;
  }

  function unfollowPrompt(itemType) {
    if (itemType === "issue") {
      return "Are you sure you want to unfollow this issue?";
    }

    if (itemType === "volume") {
      return "Are you sure you want to remove this volume from My Comics?";
    }

    if (itemType === "one_shot") {
      return "Are you sure you want to unfollow this one-shot?";
    }

    if (itemType === "run") {
      return "Are you sure you want to unfollow this run?";
    }

    return "Are you sure you want to unfollow this item?";
  }

  function resetSelectToCurrentValue(select) {
    const currentOption = Array.from(select.options).find(function (option) {
      return option.defaultSelected;
    });

    if (currentOption) {
      select.value = currentOption.value;
    }
  }

  function bindAutoSubmit(select) {
    if (!select || select.dataset.autoSubmitBound === "1") {
      return;
    }

    select.dataset.autoSubmitBound = "1";
    select.addEventListener("change", function () {
      if (select.form) {
        select.form.requestSubmit();
      }
    });
  }

  function addStatusOptions(select, choices, currentStatus, unfollowLabel) {
    (choices || []).forEach(function (choice) {
      const option = document.createElement("option");
      option.value = choice.value;
      option.textContent = choice.label;

      if (choice.value === currentStatus) {
        option.selected = true;
        option.defaultSelected = true;
      }

      select.appendChild(option);
    });

    const unfollowOption = document.createElement("option");
    unfollowOption.value = UNFOLLOW_STATUS_VALUE;
    unfollowOption.textContent = unfollowLabel;
    select.appendChild(unfollowOption);
  }

  function addCell(row, text, options) {
    const cell = document.createElement("td");
    const cellOptions = options || {};
    const safeText = text || "";

    if (cellOptions.bold) {
      cell.classList.add("fw-semibold");
    }

    if (cellOptions.alignEnd) {
      cell.classList.add("text-end");
    }

    if (cellOptions.linkLike) {
      const content = cellOptions.href
        ? document.createElement("a")
        : document.createElement("span");

      if (cellOptions.href) {
        content.href = cellOptions.href;
      }

      content.className = "erc-data-link";
      content.textContent = safeText;
      cell.appendChild(content);
    } else if (cellOptions.muted) {
      const muted = document.createElement("span");
      muted.className = "erc-muted";
      muted.textContent = safeText;
      cell.appendChild(muted);
    } else {
      cell.textContent = safeText;
    }

    if (cellOptions.meta) {
      const meta = document.createElement("span");
      meta.className = "erc-muted";
      meta.textContent = " · " + cellOptions.meta;
      cell.appendChild(meta);
    }

    row.appendChild(cell);
    return cell;
  }

  function bindClickableRow(row) {
    if (!row || row.dataset.clickableRowBound === "1") {
      return;
    }

    row.dataset.clickableRowBound = "1";

    row.addEventListener("click", function (event) {
      if (event.target.closest("a, button, input, select, textarea, label")) {
        return;
      }

      if (row.dataset.rowUrl) {
        window.location.href = row.dataset.rowUrl;
      }
    });

    row.addEventListener("keydown", function (event) {
      if (event.key !== "Enter" && event.key !== " ") {
        return;
      }

      if (!row.dataset.rowUrl) {
        return;
      }

      event.preventDefault();
      window.location.href = row.dataset.rowUrl;
    });
  }

  function createClickableRow(item) {
    const row = document.createElement("tr");
    row.className = "clickable-row";
    row.dataset.rowUrl = item.row_url;
    row.tabIndex = 0;
    row.setAttribute("aria-label", item.aria_label || "Open details");
    bindClickableRow(row);
    return row;
  }

  function createDropdownOption(option) {
    const link = document.createElement("a");
    link.href = option.url;
    link.className = "dropdown-item rounded";
    link.dataset.dropdownOption = "";
    link.dataset.searchLabel = option.search_label || option.label || "";

    if (option.active) {
      link.classList.add("active");
    }

    const label = document.createElement("span");
    label.className = "fw-semibold";
    label.textContent = option.label || "";
    link.appendChild(label);

    if (option.meta) {
      const meta = document.createElement("span");
      meta.className = "erc-muted";
      meta.textContent = " · " + option.meta;
      link.appendChild(meta);
    }

    return link;
  }

  function renderedOptionCount(optionsContainer) {
    return optionsContainer.querySelectorAll("[data-dropdown-option]").length;
  }

  function renderDropdownOptions(optionsContainer, noResults, options, append) {
    if (!append) {
      clearElement(optionsContainer);
    }

    (options || []).forEach(function (option) {
      optionsContainer.appendChild(createDropdownOption(option));
    });

    if (noResults) {
      noResults.classList.toggle(
        "d-none",
        renderedOptionCount(optionsContainer) !== 0,
      );
    }
  }

  function addFilterParams(url, source) {
    FILTER_DATA_KEYS.forEach(function (entry) {
      const dataKey = entry[0];
      const queryKey = entry[1];
      const value = source.dataset[dataKey];

      if (value) {
        url.searchParams.set(queryKey, value);
      }
    });
  }

  function bindSearchableDropdown(dropdown) {
    if (!dropdown || dropdown.dataset.searchableDropdownBound === "1") {
      return;
    }

    const searchInput = dropdown.querySelector("[data-dropdown-search]");
    const optionsContainer = dropdown.querySelector("[data-dropdown-options]");
    const noResults = dropdown.querySelector("[data-no-results]");
    const optionsUrl = dropdown.dataset.optionsUrl;
    const optionsKind = dropdown.dataset.optionsKind;

    if (!searchInput || !optionsContainer || !optionsUrl || !optionsKind) {
      return;
    }

    dropdown.dataset.searchableDropdownBound = "1";

    let debounceTimer = null;
    let latestRequestNumber = 0;
    let isLoadingOptions = false;
    let nextOffset = renderedOptionCount(optionsContainer);
    let hasMoreOptions = true;
    let hasLoadedOptions = nextOffset > 0;

    function buildOptionsUrl(offset) {
      const url = new URL(optionsUrl, window.location.origin);
      const searchValue = searchInput.value.trim();

      url.searchParams.set("kind", optionsKind);
      url.searchParams.set("offset", String(offset));

      if (searchValue) {
        url.searchParams.set("q", searchValue);
      } else {
        url.searchParams.delete("q");
      }

      if (dropdown.dataset.selectedId) {
        url.searchParams.set("selected", dropdown.dataset.selectedId);
      }

      addFilterParams(url, dropdown);
      return url;
    }

    function fetchOptions(options) {
      const append = Boolean(options && options.append);

      if (append && (!hasMoreOptions || isLoadingOptions)) {
        return;
      }


      latestRequestNumber += 1;

      const requestNumber = latestRequestNumber;
      const offset = append ? nextOffset : 0;
      isLoadingOptions = true;

      fetch(buildOptionsUrl(offset).toString(), {
        headers: {
          "X-Requested-With": "XMLHttpRequest",
        },
      })
        .then(function (response) {
          if (!response.ok) {
            throw new Error("Could not load filter options.");
          }

          return response.json();
        })
        .then(function (data) {
          if (requestNumber !== latestRequestNumber) {
            return;
          }

          const optionRows = data.options || [];
          renderDropdownOptions(
            optionsContainer,
            noResults,
            optionRows,
            append,
          );

          nextOffset = Number(
            data.next_offset || offset + optionRows.length,
          );
          hasMoreOptions = Boolean(data.has_more);
          hasLoadedOptions = true;
        })
        .catch(function () {
          if (noResults) {
            noResults.classList.remove("d-none");
          }
        })
        .finally(function () {
          if (requestNumber === latestRequestNumber) {
            isLoadingOptions = false;
          }
        });
    }

    function resetAndFetchOptions() {
      nextOffset = 0;
      hasMoreOptions = true;
      hasLoadedOptions = false;
      fetchOptions({ append: false });
    }

    function scheduleFetchOptions() {
      window.clearTimeout(debounceTimer);
      debounceTimer = window.setTimeout(resetAndFetchOptions, 150);
    }

    searchInput.addEventListener("input", scheduleFetchOptions);
    searchInput.addEventListener("click", function (event) {
      event.stopPropagation();
    });

    optionsContainer.addEventListener("scroll", function () {
      const scrollBottom =
        optionsContainer.scrollTop + optionsContainer.clientHeight;
      const nearBottom =
        scrollBottom >= optionsContainer.scrollHeight - 32;

      if (nearBottom) {
        fetchOptions({ append: true });
      }
    });

    dropdown.addEventListener("shown.bs.dropdown", function () {
      searchInput.focus();
      searchInput.select();

      if (!hasLoadedOptions && renderedOptionCount(optionsContainer) === 0) {
        fetchOptions({ append: false });
      }
    });

    dropdown.addEventListener("hidden.bs.dropdown", function () {
      if (!searchInput.value) {
        return;
      }

      searchInput.value = "";
      resetAndFetchOptions();
    });
  }

  function sectionRows(section) {
    const target = section.querySelector("[data-comic-load-target]");

    if (!target) {
      return [];
    }

    return Array.from(
      target.querySelectorAll(":scope > tr:not([data-empty-row])"),
    );
  }

  function isLocalSection(section) {
    return section.dataset.comicSectionMode === "local";
  }

  function positiveInteger(value, fallbackValue) {
    const parsedValue = Number.parseInt(value || "", 10);

    if (!Number.isFinite(parsedValue) || parsedValue <= 0) {
      return fallbackValue;
    }

    return parsedValue;
  }

  function localInitialCount(section) {
    return positiveInteger(section.dataset.localInitialCount, 10);
  }

  function localStepCount(section) {
    return positiveInteger(section.dataset.localStepCount, 10);
  }

  function localVisibleCount(section) {
    return sectionRows(section).filter(function (row) {
      return !row.hidden && !row.classList.contains("d-none");
    }).length;
  }

  function updateRemoteSectionControls(section) {
    const loadedCount = section.querySelector("[data-loaded-count]");
    const count = sectionRows(section).length;

    section.dataset.offset = String(count);

    if (loadedCount) {
      loadedCount.textContent = "Showing " + count + " loaded";
    }
  }

  function updateLocalSectionControls(section) {
    const rows = sectionRows(section);
    const visibleCount = localVisibleCount(section);

    section.dataset.offset = String(visibleCount);
    section.dataset.hasMore = visibleCount < rows.length ? "1" : "0";
    section.dataset.sectionLoaded = "1";
  }

  function applyLocalVisibleCount(section, visibleCount) {
    const rows = sectionRows(section);
    const boundedCount = Math.min(Math.max(visibleCount, 0), rows.length);

    rows.forEach(function (row, index) {
      const shouldShow = index < boundedCount;
      row.hidden = !shouldShow;
      row.classList.toggle("d-none", !shouldShow);
    });

    updateLocalSectionControls(section);
  }

  function revealLocalSectionRows(section) {
    const rows = sectionRows(section);

    if (!rows.length || section.dataset.hasMore === "0") {
      return;
    }

    const currentCount = localVisibleCount(section);
    applyLocalVisibleCount(
      section,
      Math.min(currentCount + localStepCount(section), rows.length),
    );
  }

  function ensureLocalSectionCanScroll(section) {
    if (section.dataset.hasMore === "0") {
      return;
    }

    const scrollContainer = section.querySelector(
      "[data-comic-section-scroll]",
    );

    if (!scrollContainer) {
      return;
    }

    window.requestAnimationFrame(function () {
      if (
        section.dataset.hasMore === "1" &&
        scrollContainer.scrollHeight <= scrollContainer.clientHeight + 1
      ) {
        revealLocalSectionRows(section);
        ensureLocalSectionCanScroll(section);
      }
    });
  }

  function initializeLocalSection(section) {
    if (!section || section.dataset.localSectionInitialized === "1") {
      return;
    }

    section.dataset.localSectionInitialized = "1";

    const rows = sectionRows(section);

    if (!rows.length) {
      section.dataset.offset = "0";
      section.dataset.hasMore = "0";
      section.dataset.sectionLoaded = "1";
      return;
    }

    applyLocalVisibleCount(
      section,
      Math.min(localInitialCount(section), rows.length),
    );
    ensureLocalSectionCanScroll(section);
  }

  function buildItemsUrl(section) {
    const url = new URL(section.dataset.itemsUrl, window.location.origin);
    url.searchParams.set(
      "kind",
      section.dataset.kind || section.dataset.comicSection || "",
    );
    url.searchParams.set("offset", section.dataset.offset || "0");
    addFilterParams(url, section);
    return url;
  }

  function removeEmptyRows(section) {
    section.querySelectorAll("[data-empty-row]").forEach(function (row) {
      row.remove();
    });
  }

  function appendEmptyRow(section) {
    const target = section.querySelector("[data-comic-load-target]");
    const colCount = section.querySelectorAll("thead th").length || 4;
    const message =
      section.dataset.emptyMessage || "No items match these filters.";

    if (!target || target.querySelector("[data-empty-row]")) {
      return;
    }

    const row = document.createElement("tr");
    row.dataset.emptyRow = "";

    const cell = document.createElement("td");
    cell.colSpan = colCount;
    cell.className = "text-center erc-muted py-4";
    cell.textContent = message;

    row.appendChild(cell);
    target.appendChild(row);
  }

  function loadRemoteSectionRows(section, createRow) {
    const target = section.querySelector("[data-comic-load-target]");

    if (
      !target ||
      section.dataset.loading === "1" ||
      section.dataset.hasMore === "0"
    ) {
      return Promise.resolve();
    }

    if (typeof createRow !== "function") {
      return Promise.reject(
        new Error("A createRow function is required for remote lists."),
      );
    }

    section.dataset.loading = "1";

    return fetch(buildItemsUrl(section).toString(), {
      headers: {
        "X-Requested-With": "XMLHttpRequest",
      },
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("Could not load rows.");
        }

        return response.json();
      })
      .then(function (data) {
        const items = data.items || [];
        removeEmptyRows(section);

        items.forEach(function (item) {
          const row = createRow(section.dataset.kind, item);

          if (row) {
            target.appendChild(row);
          }
        });

        section.dataset.hasMore = data.has_more ? "1" : "0";
        section.dataset.sectionLoaded = "1";
        updateRemoteSectionControls(section);

        if (sectionRows(section).length === 0) {
          appendEmptyRow(section);
        }
      })
      .catch(function (error) {
        window.alert(error.message);
      })
      .finally(function () {
        section.dataset.loading = "0";
      });
  }

  function loadSectionRows(section, createRow) {
    if (isLocalSection(section)) {
      revealLocalSectionRows(section);
      return Promise.resolve();
    }

    return loadRemoteSectionRows(section, createRow);
  }

  function ensureSectionLoaded(section, createRow) {
    if (!section) {
      return;
    }

    if (isLocalSection(section)) {
      initializeLocalSection(section);
      return;
    }

    if (section.dataset.sectionLoaded === "1") {
      return;
    }

    loadRemoteSectionRows(section, createRow);
  }

  function applySectionToggle(toggle, createRow) {
    const targetSection = toggle.dataset.targetSection;

    if (!targetSection) {
      return;
    }

    const section = document.querySelector(
      `[data-comic-section="${targetSection}"]`,
    );

    if (!section) {
      return;
    }

    const shouldShow = toggle.checked;
    section.classList.toggle("d-none", !shouldShow);
    section.hidden = !shouldShow;

    if (shouldShow) {
      ensureSectionLoaded(section, createRow);
    }
  }

  function maybeLoadMoreFromScroll(scrollContainer, createRow) {
    const section = scrollContainer.closest("[data-comic-section]");

    if (
      !section ||
      section.hidden ||
      section.dataset.hasMore === "0"
    ) {
      return;
    }

    const scrollBottom =
      scrollContainer.scrollTop + scrollContainer.clientHeight;
    const nearBottom =
      scrollBottom >= scrollContainer.scrollHeight - 96;

    if (nearBottom) {
      loadSectionRows(section, createRow);
    }
  }

  function init(options) {
    if (controllerInitialized) {
      return;
    }

    const createRow = options && options.createRow;
    const sections = Array.from(
      document.querySelectorAll("[data-comic-section]"),
    );
    const hasRemoteSections = sections.some(function (section) {
      return !isLocalSection(section);
    });

    if (hasRemoteSections && typeof createRow !== "function") {
      throw new Error("A createRow function is required for remote lists.");
    }

    controllerInitialized = true;

    document
      .querySelectorAll(".searchable-dropdown")
      .forEach(bindSearchableDropdown);

    document
      .querySelectorAll("[data-row-url]")
      .forEach(bindClickableRow);

    sections.forEach(function (section) {
      if (isLocalSection(section)) {
        initializeLocalSection(section);
      } else {
        updateRemoteSectionControls(section);
      }
    });

    document
      .querySelectorAll("[data-comic-section-scroll]")
      .forEach(function (scrollContainer) {
        if (scrollContainer.dataset.comicSectionScrollBound === "1") {
          return;
        }

        scrollContainer.dataset.comicSectionScrollBound = "1";
        scrollContainer.addEventListener("scroll", function () {
          maybeLoadMoreFromScroll(scrollContainer, createRow);
        });
      });

    document.addEventListener("change", function (event) {
      const toggle = event.target.closest("[data-comic-section-toggle]");

      if (toggle) {
        applySectionToggle(toggle, createRow);
      }
    });

    document
      .querySelectorAll("[data-comic-section-toggle]")
      .forEach(function (toggle) {
        applySectionToggle(toggle, createRow);
      });
  }

  global.EzyReadComicsComicLists = {
    init,
    onReady,
    helpers: {
      UNFOLLOW_STATUS_VALUE,
      addCell,
      addStatusOptions,
      applyRunStatusMessage,
      bindAutoSubmit,
      bindClickableRow,
      clearElement,
      createClickableRow,
      createHiddenInput,
      currentNextValue,
      getCsrfToken,
      getDatasetCount,
      issueLabel,
      resetSelectToCurrentValue,
      statusLabel,
      unfollowPrompt,
    },
  };
})(window);
