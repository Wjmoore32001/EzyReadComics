document.addEventListener("DOMContentLoaded", function () {
  const unfollowStatusValue = "__unfollow__";
  const dropdownOptionPageSize = 10;

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
  }

  function applyAllMyComicsSectionToggles() {
    document
      .querySelectorAll("[data-my-comics-section-toggle]")
      .forEach(applyMyComicsSectionToggle);
  }

  document.addEventListener("change", function (event) {
    const toggle = event.target.closest("[data-my-comics-section-toggle]");

    if (!toggle) {
      return;
    }

    applyMyComicsSectionToggle(toggle);
  });

  applyAllMyComicsSectionToggles();

  function getCount(form, name) {
    const value = Number(form.dataset[name] || "0");

    if (Number.isNaN(value)) {
      return 0;
    }

    return value;
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
    const optionsUrl = dropdown.dataset.optionsUrl;
    const optionsKind = dropdown.dataset.optionsKind;

    if (!searchInput || !optionsContainer || !optionsUrl || !optionsKind) {
      return;
    }

    let debounceTimer = null;
    let latestRequestNumber = 0;
    let isLoadingOptions = false;
    let nextOffset = renderedOptionCount(optionsContainer);
    let hasMoreOptions = nextOffset >= dropdownOptionPageSize;

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
    });

    dropdown.addEventListener("hidden.bs.dropdown", function () {
      if (!searchInput.value) {
        return;
      }

      searchInput.value = "";
      resetAndFetchOptions();
    });
  }

  document
    .querySelectorAll("[data-my-comics-filter-dropdown]")
    .forEach(bindFilterDropdown);

  document.querySelectorAll("[data-run-status-form]").forEach(function (form) {
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
  });

  document.querySelectorAll("form[data-item-type]").forEach(function (form) {
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
  });

  document.querySelectorAll("[data-auto-submit]").forEach(function (select) {
    select.addEventListener("change", function () {
      select.form.requestSubmit();
    });
  });
});