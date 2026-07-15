document.addEventListener("DOMContentLoaded", function () {
  const unfollowStatusValue = "__unfollow__";
  const dropdownOptionPageSize = 10;

  function getCsrfToken() {
    const csrfInput = document.querySelector("input[name='csrfmiddlewaretoken']");

    if (csrfInput) {
      return csrfInput.value;
    }

    const csrfSource = document.querySelector("[data-csrf-token]");

    if (csrfSource) {
      return csrfSource.dataset.csrfToken || "";
    }

    return "";
  }

  function getCount(form, name) {
    const value = Number(form.dataset[name] || "0");
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

  function applyStatusMessage(status, totalIssues, trackedIssues) {
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

  function unfollowPromptForForm(form) {
    const itemType = form.dataset.itemType || "item";

    if (itemType === "issue") {
      return "Are you sure you want to unfollow this issue?";
    }

    if (itemType === "volume") {
      return "Are you sure you want to remove this volume from My Comics?";
    }

    if (itemType === "one_shot") {
      return "Are you sure you want to unfollow this one-shot?";
    }

    return "Are you sure you want to unfollow this item?";
  }

  function resetSelectToCurrentValue(select) {
    const previousOption = Array.from(select.options).find(function (option) {
      return option.defaultSelected;
    });

    if (previousOption) {
      select.value = previousOption.value;
    }
  }

  function clearElement(element) {
    while (element.firstChild) {
      element.removeChild(element.firstChild);
    }
  }

  function createHiddenInput(name, value) {
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = name;
    input.value = value;
    return input;
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

    options.forEach(function (option) {
      optionsContainer.appendChild(createDropdownOption(option));
    });

    if (noResults) {
      noResults.classList.toggle(
        "d-none",
        renderedOptionCount(optionsContainer) !== 0,
      );
    }
  }

  function bindFilterDropdown(dropdown) {
    const searchInput = dropdown.querySelector("[data-dropdown-search]");
    const optionsContainer = dropdown.querySelector("[data-dropdown-options]");
    const noResults = dropdown.querySelector("[data-no-results]");
    const dropdownButton = dropdown.querySelector("[data-bs-toggle='dropdown']");
    const optionsUrl = dropdown.dataset.optionsUrl;
    const optionsKind = dropdown.dataset.optionsKind;

    if (!searchInput || !optionsContainer || !dropdownButton || !optionsUrl || !optionsKind) {
      return;
    }

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
      }

      if (dropdown.dataset.selectedId) {
        url.searchParams.set("selected", dropdown.dataset.selectedId);
      }

      if (dropdown.dataset.selectedStatus) {
        url.searchParams.set("status", dropdown.dataset.selectedStatus);
      }

      if (dropdown.dataset.filterPublisherId) {
        url.searchParams.set("publisher", dropdown.dataset.filterPublisherId);
      }

      if (dropdown.dataset.filterRunId) {
        url.searchParams.set("run", dropdown.dataset.filterRunId);
      }

      if (dropdown.dataset.filterIssueId) {
        url.searchParams.set("issue", dropdown.dataset.filterIssueId);
      }

      if (dropdown.dataset.filterOneShotId) {
        url.searchParams.set("one_shot", dropdown.dataset.filterOneShotId);
      }

      return url;
    }

    function fetchDropdownOptions(options) {
      const append = options && options.append;

      if (append && (!hasMoreOptions || isLoadingOptions)) {
        return;
      }

      if (!append && isLoadingOptions) {
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

          renderDropdownOptions(optionsContainer, noResults, optionRows, append);

          nextOffset = Number(data.next_offset || offset + optionRows.length);
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
      fetchDropdownOptions({ append: false });
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
      const scrollBottom = optionsContainer.scrollTop + optionsContainer.clientHeight;
      const nearBottom = scrollBottom >= optionsContainer.scrollHeight - 32;

      if (nearBottom) {
        fetchDropdownOptions({ append: true });
      }
    });

    dropdown.addEventListener("shown.bs.dropdown", function () {
      searchInput.focus();
      searchInput.select();

      if (!hasLoadedOptions && renderedOptionCount(optionsContainer) === 0) {
        fetchDropdownOptions({ append: false });
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

  function createClickableRow(item) {
    const row = document.createElement("tr");
    row.className = "clickable-row";
    row.dataset.rowUrl = item.row_url;
    row.tabIndex = 0;
    row.setAttribute("aria-label", item.aria_label || "Open details");
    bindClickableRow(row);
    return row;
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
      const link = document.createElement("a");
      link.href = cellOptions.href || "#";
      link.className = "erc-data-link";
      link.textContent = safeText;
      cell.appendChild(link);
    } else if (cellOptions.muted) {
      const muted = document.createElement("span");
      muted.className = "erc-muted";
      muted.textContent = safeText;
      cell.appendChild(muted);
    } else {
      cell.textContent = safeText;
    }

    row.appendChild(cell);
  }

  function currentNextValue() {
    return window.location.pathname + window.location.search;
  }

  function addStatusOptions(select, choices, currentStatus, unfollowLabel) {
    choices.forEach(function (choice) {
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
    unfollowOption.value = unfollowStatusValue;
    unfollowOption.textContent = unfollowLabel;
    select.appendChild(unfollowOption);
  }

  function createRunStatusCell(item) {
    const cell = document.createElement("td");
    const form = document.createElement("form");
    const select = document.createElement("select");

    cell.className = "text-end erc-track-cell";
    form.action = item.action_url;
    form.method = "post";
    form.className = "erc-track-form";
    form.dataset.runStatusForm = "";
    form.dataset.currentStatus = item.current_status || "";
    form.dataset.runIssueCount = String(item.catalog_issue_count || 0);
    form.dataset.trackedIssueCount = String(item.tracked_issue_count || 0);

    form.appendChild(createHiddenInput("csrfmiddlewaretoken", getCsrfToken()));
    form.appendChild(createHiddenInput("next", currentNextValue()));
    form.appendChild(createHiddenInput("apply_to_issues", ""));
    form.appendChild(createHiddenInput("remove_issues", ""));

    select.name = "status";
    select.className = "form-select form-select-sm";
    select.dataset.autoSubmit = "";
    addStatusOptions(select, item.status_choices || [], item.current_status, "Unfollow");

    form.appendChild(select);
    bindRunStatusForm(form);
    bindAutoSubmit(select);
    cell.appendChild(form);
    return cell;
  }

  function createProgressStatusCell(item, itemType, unfollowLabel) {
    const cell = document.createElement("td");
    const form = document.createElement("form");
    const select = document.createElement("select");

    cell.className = "text-end erc-track-cell";
    form.action = item.action_url;
    form.method = "post";
    form.className = "erc-track-form";
    form.dataset.itemType = itemType;

    form.appendChild(createHiddenInput("csrfmiddlewaretoken", getCsrfToken()));
    form.appendChild(createHiddenInput("next", currentNextValue()));

    select.name = "status";
    select.className = "form-select form-select-sm";
    select.dataset.autoSubmit = "";
    addStatusOptions(select, item.status_choices || [], item.current_status, unfollowLabel);

    form.appendChild(select);
    bindItemStatusForm(form);
    bindAutoSubmit(select);
    cell.appendChild(form);
    return cell;
  }

  function createRunRow(item) {
    const row = createClickableRow(item);

    addCell(row, item.run, { bold: true, linkLike: true, href: item.row_url });
    addCell(row, item.publisher);
    row.appendChild(createRunStatusCell(item));
    addCell(row, item.issue_count, { muted: item.issue_count_muted });

    return row;
  }

  function createVolumeRow(item) {
    const row = createClickableRow(item);

    addCell(row, item.volume, { bold: true, linkLike: true, href: item.row_url });
    addCell(row, item.run, { linkLike: true, href: item.run_url });
    addCell(row, item.release_date, { muted: item.release_date_muted });
    row.appendChild(createProgressStatusCell(item, "volume", "Remove"));

    return row;
  }

  function createIssueRow(item) {
    const row = createClickableRow(item);

    addCell(row, item.issue, { bold: true, linkLike: true, href: item.row_url });
    addCell(row, item.run, { linkLike: true, href: item.run_url });
    addCell(row, item.published_date, { muted: item.published_date_muted });
    row.appendChild(createProgressStatusCell(item, "issue", "Unfollow"));

    return row;
  }

  function createOneShotRow(item) {
    const row = createClickableRow(item);

    addCell(row, item.title, { bold: true, linkLike: true, href: item.row_url });
    addCell(row, item.publisher);
    addCell(row, item.published_date, { muted: item.published_date_muted });
    row.appendChild(createProgressStatusCell(item, "one_shot", "Unfollow"));

    return row;
  }

  function createRow(kind, item) {
    if (kind === "runs") {
      return createRunRow(item);
    }

    if (kind === "volumes") {
      return createVolumeRow(item);
    }

    if (kind === "issues") {
      return createIssueRow(item);
    }

    return createOneShotRow(item);
  }

  function rowCount(section) {
    const target = section.querySelector("[data-my-comics-load-target]");
    return target ? target.querySelectorAll("tr").length : 0;
  }

  function updateSectionControls(section) {
    const loadedCount = section.querySelector("[data-loaded-count]");
    const count = rowCount(section);

    section.dataset.offset = String(count);

    if (loadedCount) {
      loadedCount.textContent = "Showing " + count + " loaded";
    }
  }

  function buildItemsUrl(section) {
    const url = new URL(section.dataset.itemsUrl, window.location.origin);

    url.searchParams.set("kind", section.dataset.kind || section.dataset.myComicsSection || "");
    url.searchParams.set("offset", section.dataset.offset || "0");

    if (section.dataset.filterPublisherId) {
      url.searchParams.set("publisher", section.dataset.filterPublisherId);
    }

    if (section.dataset.filterRunId) {
      url.searchParams.set("run", section.dataset.filterRunId);
    }

    if (section.dataset.filterIssueId) {
      url.searchParams.set("issue", section.dataset.filterIssueId);
    }

    if (section.dataset.filterOneShotId) {
      url.searchParams.set("one_shot", section.dataset.filterOneShotId);
    }

    if (section.dataset.filterStatus) {
      url.searchParams.set("status", section.dataset.filterStatus);
    }

    return url;
  }

  function removeEmptyRows(section) {
    section.querySelectorAll("[data-empty-row]").forEach(function (row) {
      row.remove();
    });
  }

  function appendEmptyRow(section) {
    const target = section.querySelector("[data-my-comics-load-target]");
    const colCount = section.querySelectorAll("thead th").length || 4;
    const message = section.dataset.emptyMessage || "No items match these filters.";

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

  function loadSectionRows(section) {
    const target = section.querySelector("[data-my-comics-load-target]");

    if (!target || section.dataset.loading === "1" || section.dataset.hasMore === "0") {
      return Promise.resolve();
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
          target.appendChild(createRow(section.dataset.kind, item));
        });

        section.dataset.hasMore = data.has_more ? "1" : "0";
        section.dataset.myComicsSectionLoaded = "1";
        updateSectionControls(section);

        if (rowCount(section) === 0) {
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

  function ensureSectionLoaded(section) {
    if (!section || section.dataset.myComicsSectionLoaded === "1") {
      return;
    }

    loadSectionRows(section);
  }

  function applyMyComicsSectionToggle(toggle) {
    const targetSection = toggle.dataset.targetSection;

    if (!targetSection) {
      return;
    }

    const section = document.querySelector(
      `[data-my-comics-section="${targetSection}"]`,
    );

    if (!section) {
      return;
    }

    section.classList.toggle("d-none", !toggle.checked);
    section.hidden = !toggle.checked;

    if (toggle.checked) {
      ensureSectionLoaded(section);
    }
  }

  function applyAllMyComicsSectionToggles() {
    document
      .querySelectorAll("[data-my-comics-section-toggle]")
      .forEach(applyMyComicsSectionToggle);
  }

  function maybeLoadMoreFromScroll(scrollContainer) {
    const section = scrollContainer.closest("[data-my-comics-section]");

    if (!section || section.hidden || section.dataset.hasMore === "0") {
      return;
    }

    const scrollBottom = scrollContainer.scrollTop + scrollContainer.clientHeight;
    const nearBottom = scrollBottom >= scrollContainer.scrollHeight - 96;

    if (nearBottom) {
      loadSectionRows(section);
    }
  }

  function bindAutoSubmit(select) {
    if (select.dataset.autoSubmitBound === "1") {
      return;
    }

    select.dataset.autoSubmitBound = "1";

    select.addEventListener("change", function () {
      select.form.requestSubmit();
    });
  }

  function bindRunStatusForm(form) {
    if (form.dataset.runStatusBound === "1") {
      return;
    }

    form.dataset.runStatusBound = "1";

    form.addEventListener("submit", function (event) {
      const select = form.querySelector("select[name='status']");
      const applyToIssuesInput = form.querySelector(
        "input[name='apply_to_issues']",
      );
      const removeIssuesInput = form.querySelector(
        "input[name='remove_issues']",
      );
      const currentStatus = form.dataset.currentStatus;
      const totalIssues = getCount(form, "runIssueCount");
      const trackedIssues = getCount(form, "trackedIssueCount");

      if (!select || !applyToIssuesInput || !removeIssuesInput) {
        return;
      }

      applyToIssuesInput.value = "";
      removeIssuesInput.value = "";

      if (select.value === currentStatus) {
        return;
      }

      if (select.value === unfollowStatusValue) {
        const confirmed = window.confirm(
          "Are you sure you want to unfollow this run?",
        );

        if (!confirmed) {
          event.preventDefault();
          select.value = currentStatus;
          return;
        }

        if (trackedIssues > 0) {
          const removeIssues = window.confirm(
            `Also unfollow the ${trackedIssues} saved ${issueLabel(trackedIssues)} from this run?`,
          );

          if (removeIssues) {
            removeIssuesInput.value = "1";
          }
        }

        return;
      }

      const message = applyStatusMessage(
        select.value,
        totalIssues,
        trackedIssues,
      );

      if (message && window.confirm(message)) {
        applyToIssuesInput.value = "1";
      }
    });
  }

  function bindItemStatusForm(form) {
    if (form.dataset.itemStatusBound === "1") {
      return;
    }

    form.dataset.itemStatusBound = "1";

    form.addEventListener("submit", function (event) {
      const select = form.querySelector("select[name='status']");

      if (!select || select.value !== unfollowStatusValue) {
        return;
      }

      const confirmed = window.confirm(unfollowPromptForForm(form));

      if (!confirmed) {
        event.preventDefault();
        resetSelectToCurrentValue(select);
      }
    });
  }

  document.addEventListener("change", function (event) {
    const toggle = event.target.closest("[data-my-comics-section-toggle]");

    if (!toggle) {
      return;
    }

    applyMyComicsSectionToggle(toggle);
  });

  document
    .querySelectorAll("[data-my-comics-filter-dropdown]")
    .forEach(bindFilterDropdown);

  document.querySelectorAll("[data-run-status-form]").forEach(bindRunStatusForm);

  document.querySelectorAll("form[data-item-type]").forEach(bindItemStatusForm);

  document.querySelectorAll("[data-auto-submit]").forEach(bindAutoSubmit);

  document.querySelectorAll(".clickable-row").forEach(bindClickableRow);

  document.querySelectorAll("[data-my-comics-section]").forEach(updateSectionControls);

  document.querySelectorAll("[data-my-comics-section-scroll]").forEach(function (scrollContainer) {
    scrollContainer.addEventListener("scroll", function () {
      maybeLoadMoreFromScroll(scrollContainer);
    });
  });

  applyAllMyComicsSectionToggles();
});
