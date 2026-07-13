document.addEventListener("DOMContentLoaded", function () {
  const unfollowStatusValue = "__unfollow__";

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

  function bindFilterDropdown(dropdown) {
    const searchInput = dropdown.querySelector("[data-dropdown-search]");
    const options = Array.from(
      dropdown.querySelectorAll("[data-dropdown-option]"),
    );
    const noResults = dropdown.querySelector("[data-no-results]");

    if (!searchInput || !options.length) {
      return;
    }

    function filterOptions() {
      const searchValue = searchInput.value.trim().toLowerCase();
      let visibleCount = 0;

      options.forEach(function (option) {
        const label = (
          option.dataset.searchLabel ||
          option.textContent ||
          ""
        ).toLowerCase();
        const isVisible = !searchValue || label.includes(searchValue);

        option.classList.toggle("d-none", !isVisible);

        if (isVisible) {
          visibleCount += 1;
        }
      });

      if (noResults) {
        noResults.classList.toggle("d-none", visibleCount > 0);
      }
    }

    searchInput.addEventListener("input", filterOptions);

    dropdown.addEventListener("shown.bs.dropdown", function () {
      searchInput.focus();
      searchInput.select();
      filterOptions();
    });

    dropdown.addEventListener("hidden.bs.dropdown", function () {
      searchInput.value = "";
      filterOptions();
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