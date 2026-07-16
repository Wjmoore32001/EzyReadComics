(function () {
  "use strict";

  const listing = window.EzyReadComicsComicLists;

  if (!listing) {
    return;
  }

  const helpers = listing.helpers;
  const unfollowStatusValue = helpers.UNFOLLOW_STATUS_VALUE;

  listing.onReady(function () {
    const statusModalElement = document.getElementById("tracking-status-modal");
    const statusModalTitle = document.getElementById("tracking-status-modal-title");
    const statusModalCopy = document.getElementById("tracking-status-modal-copy");
    const statusModalSelect = document.getElementById("tracking-status-select");
    const statusModalConfirm = document.querySelector("[data-status-modal-confirm]");
    const statusModal = statusModalElement && window.bootstrap
      ? window.bootstrap.Modal.getOrCreateInstance(statusModalElement)
      : null;

    let statusModalResolve = null;
    let statusModalContext = null;
    let statusModalControls = null;

    function itemTypeLabel(itemType) {
      const labels = {
        run: "run",
        issue: "issue",
        volume: "volume",
        one_shot: "one-shot",
      };

      return labels[itemType] || "item";
    }

    function optionObjectsFromSelect(select) {
      return Array.from(select.options)
        .filter(function (option) {
          return option.value !== unfollowStatusValue;
        })
        .map(function (option) {
          return {
            value: option.value,
            label: option.textContent.trim(),
          };
        });
    }

    function populateSelect(select, choices, selectedValue) {
      helpers.clearElement(select);

      (choices || []).forEach(function (choice) {
        const option = document.createElement("option");
        option.value = choice.value;
        option.textContent = choice.label;

        if (choice.value === selectedValue) {
          option.selected = true;
        }

        select.appendChild(option);
      });
    }

    function ensureStatusModalControls() {
      if (statusModalControls) {
        return statusModalControls;
      }

      const body = statusModalElement.querySelector(".modal-body");
      const error = document.createElement("div");
      const runOptions = document.createElement("div");
      const followIssuesCheck = document.createElement("div");
      const followIssuesInput = document.createElement("input");
      const followIssuesLabel = document.createElement("label");
      const followIssuesSettings = document.createElement("div");
      const individualCheck = document.createElement("div");
      const individualInput = document.createElement("input");
      const individualLabel = document.createElement("label");
      const sharedIssueStatusGroup = document.createElement("div");
      const sharedIssueStatusLabel = document.createElement("label");
      const sharedIssueStatusSelect = document.createElement("select");
      const individualIssueStatusGroup = document.createElement("div");
      const individualIssueStatusLabel = document.createElement("div");
      const individualIssueStatusList = document.createElement("div");

      error.className = "alert alert-danger d-none";
      error.dataset.statusModalError = "";
      body.insertBefore(error, body.firstChild);

      runOptions.className = "mt-4 d-none";
      runOptions.dataset.runFollowOptions = "";

      followIssuesCheck.className = "form-check";
      followIssuesInput.type = "checkbox";
      followIssuesInput.className = "form-check-input";
      followIssuesInput.id = "tracking-follow-issues";
      followIssuesInput.dataset.followIssuesCheckbox = "";
      followIssuesLabel.className = "form-check-label";
      followIssuesLabel.setAttribute("for", "tracking-follow-issues");
      followIssuesLabel.textContent = "Follow all issues in this run too";
      followIssuesCheck.appendChild(followIssuesInput);
      followIssuesCheck.appendChild(followIssuesLabel);

      followIssuesSettings.className = "mt-3 d-none";
      followIssuesSettings.dataset.followIssuesSettings = "";

      individualCheck.className = "form-check";
      individualInput.type = "checkbox";
      individualInput.className = "form-check-input";
      individualInput.id = "tracking-individual-issue-statuses";
      individualInput.dataset.individualIssueStatusesCheckbox = "";
      individualLabel.className = "form-check-label";
      individualLabel.setAttribute(
        "for",
        "tracking-individual-issue-statuses",
      );
      individualLabel.textContent = "Set status for individual issues";
      individualCheck.appendChild(individualInput);
      individualCheck.appendChild(individualLabel);

      sharedIssueStatusGroup.className = "mt-3";
      sharedIssueStatusGroup.dataset.sharedIssueStatusGroup = "";
      sharedIssueStatusLabel.className = "form-label erc-muted";
      sharedIssueStatusLabel.setAttribute(
        "for",
        "tracking-issue-status-select",
      );
      sharedIssueStatusLabel.textContent = "Issue status";
      sharedIssueStatusSelect.id = "tracking-issue-status-select";
      sharedIssueStatusSelect.className = "form-select";
      sharedIssueStatusSelect.dataset.issueStatusSelect = "";
      sharedIssueStatusGroup.appendChild(sharedIssueStatusLabel);
      sharedIssueStatusGroup.appendChild(sharedIssueStatusSelect);

      individualIssueStatusGroup.className = "mt-3 d-none";
      individualIssueStatusGroup.dataset.individualIssueStatusGroup = "";
      individualIssueStatusLabel.className = "form-label erc-muted";
      individualIssueStatusLabel.textContent = "Issue statuses";
      individualIssueStatusList.dataset.individualIssueStatusList = "";
      individualIssueStatusGroup.appendChild(individualIssueStatusLabel);
      individualIssueStatusGroup.appendChild(individualIssueStatusList);

      followIssuesSettings.appendChild(individualCheck);
      followIssuesSettings.appendChild(sharedIssueStatusGroup);
      followIssuesSettings.appendChild(individualIssueStatusGroup);
      runOptions.appendChild(followIssuesCheck);
      runOptions.appendChild(followIssuesSettings);
      body.appendChild(runOptions);

      statusModalControls = {
        error,
        runOptions,
        followIssuesInput,
        followIssuesSettings,
        individualInput,
        sharedIssueStatusGroup,
        sharedIssueStatusSelect,
        individualIssueStatusGroup,
        individualIssueStatusList,
      };

      followIssuesInput.addEventListener("change", function () {
        followIssuesSettings.classList.toggle(
          "d-none",
          !followIssuesInput.checked,
        );
      });

      individualInput.addEventListener("change", function () {
        sharedIssueStatusGroup.classList.toggle(
          "d-none",
          individualInput.checked,
        );
        individualIssueStatusGroup.classList.toggle(
          "d-none",
          !individualInput.checked,
        );
      });

      return statusModalControls;
    }

    function hideStatusModalError() {
      const controls = ensureStatusModalControls();
      controls.error.classList.add("d-none");
      controls.error.textContent = "";
    }

    function showStatusModalError(message) {
      const controls = ensureStatusModalControls();
      controls.error.textContent = message;
      controls.error.classList.remove("d-none");
    }

    function createIndividualIssueStatusRow(
      issue,
      choices,
      selectedStatus,
    ) {
      const wrapper = document.createElement("div");
      const label = document.createElement("label");
      const select = document.createElement("select");

      wrapper.className = "d-flex flex-column gap-1 mb-3";
      label.className = "form-label erc-muted mb-0";
      label.textContent = issue.label || "Issue";
      select.className = "form-select";
      select.dataset.issueId = String(issue.id);
      populateSelect(
        select,
        choices,
        issue.status || selectedStatus || "planned",
      );

      wrapper.appendChild(label);

      if (issue.meta) {
        const meta = document.createElement("small");
        meta.className = "erc-muted";
        meta.textContent = issue.meta;
        wrapper.appendChild(meta);
      }

      wrapper.appendChild(select);
      return wrapper;
    }

    function resetRunModalControls(options) {
      const controls = ensureStatusModalControls();
      const isRun =
        statusModalContext && statusModalContext.itemType === "run";
      const issueChoices =
        options.issueStatusChoices ||
        optionObjectsFromSelect(statusModalSelect);
      const selectedStatus = statusModalSelect
        ? statusModalSelect.value
        : "planned";
      const issues = options.issues || [];

      controls.runOptions.classList.toggle("d-none", !isRun);
      controls.followIssuesInput.checked = false;
      controls.followIssuesSettings.classList.add("d-none");
      controls.individualInput.checked = false;
      controls.sharedIssueStatusGroup.classList.remove("d-none");
      controls.individualIssueStatusGroup.classList.add("d-none");
      populateSelect(
        controls.sharedIssueStatusSelect,
        issueChoices,
        selectedStatus,
      );
      helpers.clearElement(controls.individualIssueStatusList);

      issues.forEach(function (issue) {
        controls.individualIssueStatusList.appendChild(
          createIndividualIssueStatusRow(
            issue,
            issueChoices,
            selectedStatus,
          ),
        );
      });
    }

    function buildStatusModalResult() {
      const controls = ensureStatusModalControls();
      const individualIssueStatuses = [];

      controls.individualIssueStatusList
        .querySelectorAll("select[data-issue-id]")
        .forEach(function (select) {
          individualIssueStatuses.push({
            issueId: select.dataset.issueId,
            status: select.value,
          });
        });

      return {
        status: statusModalSelect.value,
        followIssues: controls.followIssuesInput.checked,
        issueStatusMode: controls.individualInput.checked
          ? "individual"
          : "single",
        issueStatus:
          controls.sharedIssueStatusSelect.value ||
          statusModalSelect.value,
        individualIssueStatuses,
      };
    }

    function openStatusModal(itemType, options) {
      if (!statusModal || !statusModalElement || !statusModalSelect) {
        return Promise.resolve({ status: "planned" });
      }

      statusModalContext = {
        itemType,
        options: options || {},
      };

      hideStatusModalError();
      statusModalTitle.textContent = `Follow ${itemTypeLabel(itemType)}`;
      statusModalCopy.textContent =
        `Choose the status to save for this ${itemTypeLabel(itemType)}.`;
      statusModalSelect.value = "planned";
      resetRunModalControls(options || {});

      if (options && options.error) {
        showStatusModalError(options.error);
      }

      statusModal.show();

      return new Promise(function (resolve) {
        statusModalResolve = resolve;
      });
    }

    function resolveStatusModal(value) {
      if (!statusModalResolve) {
        return;
      }

      const resolve = statusModalResolve;
      statusModalResolve = null;
      statusModal.hide();
      resolve(value);
    }

    if (statusModalConfirm) {
      statusModalConfirm.addEventListener("click", function () {
        resolveStatusModal(buildStatusModalResult());
      });
    }

    if (statusModalElement) {
      statusModalElement.addEventListener(
        "hidden.bs.modal",
        function () {
          if (statusModalResolve) {
            const resolve = statusModalResolve;
            statusModalResolve = null;
            resolve(null);
          }

          statusModalContext = null;
        },
      );
    }

    function createTrackingCell(tracking) {
      const cell = document.createElement("td");
      const form = document.createElement("form");

      cell.className = "text-end erc-track-cell";
      form.method = "post";
      form.action = tracking.action_url;
      form.className = "erc-track-form";
      form.dataset.trackingForm = "";
      form.dataset.itemType = tracking.item_type || "";

      form.appendChild(
        helpers.createHiddenInput(
          "csrfmiddlewaretoken",
          helpers.getCsrfToken(),
        ),
      );
      form.appendChild(
        helpers.createHiddenInput("next", helpers.currentNextValue()),
      );

      if (tracking.item_type === "run") {
        form.dataset.runIssueCount = String(
          tracking.catalog_issue_count || 0,
        );
        form.dataset.trackedIssueCount = String(
          tracking.tracked_issue_count || 0,
        );
        form.appendChild(
          helpers.createHiddenInput("apply_to_issues", ""),
        );
        form.appendChild(
          helpers.createHiddenInput("issue_status", ""),
        );
        form.appendChild(
          helpers.createHiddenInput("issue_status_mode", ""),
        );
        form.appendChild(
          helpers.createHiddenInput("remove_issues", ""),
        );
      }

      if (tracking.tracked) {
        form.dataset.currentStatus = tracking.status || "";

        const select = document.createElement("select");
        select.name = "status";
        select.className = "form-select form-select-sm";
        select.dataset.autoSubmit = "";

        helpers.addStatusOptions(
          select,
          tracking.status_choices || [],
          tracking.status,
          tracking.item_type === "volume"
            ? "Remove"
            : "Unfollow",
        );

        helpers.bindAutoSubmit(select);
        form.appendChild(select);
      } else {
        form.dataset.trackFollow = "";

        const button = document.createElement("button");
        button.type = "submit";
        button.className =
          "btn btn-outline-light btn-sm erc-track-button";
        button.textContent = "Follow";
        form.appendChild(button);
      }

      bindTrackingForm(form);
      cell.appendChild(form);
      return cell;
    }

    function runTitleWithYear(item) {
      if (item.year && !item.year_muted) {
        return `${item.title} (${item.year})`;
      }

      return item.title;
    }

    function createRunRow(item) {
      const row = helpers.createClickableRow(item);
      helpers.addCell(row, runTitleWithYear(item), {
        bold: true,
        linkLike: true,
        href: item.row_url,
      });
      helpers.addCell(row, item.publisher, { meta: item.status });
      helpers.addCell(row, item.issue_count, {
        muted: item.issue_count_muted,
      });
      row.appendChild(createTrackingCell(item.tracking));
      return row;
    }

    function createVolumeRow(item) {
      const row = helpers.createClickableRow(item);
      helpers.addCell(row, item.volume, {
        bold: true,
        linkLike: true,
        href: item.row_url,
      });
      helpers.addCell(row, item.run, { linkLike: true });
      helpers.addCell(row, item.release_date, {
        muted: item.release_date_muted,
      });
      row.appendChild(createTrackingCell(item.tracking));
      return row;
    }

    function createIssueRow(item) {
      const row = helpers.createClickableRow(item);
      helpers.addCell(row, item.issue, {
        bold: true,
        linkLike: true,
        href: item.row_url,
      });
      helpers.addCell(row, item.run, { linkLike: true });
      helpers.addCell(row, item.published_date, {
        muted: item.published_date_muted,
      });
      row.appendChild(createTrackingCell(item.tracking));
      return row;
    }

    function createOneShotRow(item) {
      const row = helpers.createClickableRow(item);
      helpers.addCell(row, item.title, {
        bold: true,
        linkLike: true,
        href: item.row_url,
      });
      helpers.addCell(row, item.publisher);
      helpers.addCell(row, item.published_date, {
        muted: item.published_date_muted,
      });
      row.appendChild(createTrackingCell(item.tracking));
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

    function normalizeUrl(value) {
      return new URL(value, window.location.origin).toString();
    }

    function sameActionUrl(left, right) {
      return normalizeUrl(left) === normalizeUrl(right);
    }

    function replaceTrackingCellForForm(form, tracking) {
      const cell = form.closest(".erc-track-cell");

      if (cell && tracking) {
        cell.replaceWith(createTrackingCell(tracking));
      }
    }

    function replaceMatchingTrackingCells(actionUrl, tracking) {
      document
        .querySelectorAll("[data-tracking-form]")
        .forEach(function (form) {
          if (sameActionUrl(form.action, actionUrl)) {
            replaceTrackingCellForForm(form, tracking);
          }
        });
    }

    async function postTrackingForm(actionUrl, formData) {
      const response = await fetch(actionUrl, {
        method: "POST",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
        },
        body: formData,
      });

      let data = null;

      try {
        data = await response.json();
      } catch (error) {
        data = null;
      }

      if (response.status === 401 && data && data.redirect_url) {
        window.location.href = data.redirect_url;
        return null;
      }

      if (!response.ok || !data || data.ok === false) {
        const message =
          data && data.error
            ? data.error
            : "Could not save tracking status.";
        throw new Error(message);
      }

      return data;
    }

    function runFollowOptionsUrl(actionUrl) {
      const url = new URL(actionUrl, window.location.origin);
      url.pathname = url.pathname.replace(
        /\/status\/?$/,
        "/follow-options/",
      );
      return url;
    }

    async function fetchRunFollowOptions(form) {
      const response = await fetch(
        runFollowOptionsUrl(form.action),
        {
          headers: {
            "X-Requested-With": "XMLHttpRequest",
          },
        },
      );

      if (!response.ok) {
        throw new Error("Could not load run issue options.");
      }

      return response.json();
    }

    function setRunIssueFormData(formData, modalResult) {
      formData.set(
        "apply_to_issues",
        modalResult.followIssues ? "1" : "",
      );

      if (!modalResult.followIssues) {
        formData.set("issue_status", "");
        formData.set("issue_status_mode", "");
        return;
      }

      formData.set(
        "issue_status_mode",
        modalResult.issueStatusMode || "single",
      );

      if (modalResult.issueStatusMode === "individual") {
        formData.set("issue_status", "");

        (modalResult.individualIssueStatuses || []).forEach(
          function (issueStatus) {
            formData.set(
              `issue_status_${issueStatus.issueId}`,
              issueStatus.status,
            );
          },
        );
      } else {
        formData.set(
          "issue_status",
          modalResult.issueStatus || modalResult.status,
        );
      }
    }

    function handleTrackedStatusSubmit(form, select, event) {
      const currentStatus = form.dataset.currentStatus || "";

      if (!select || select.value === currentStatus) {
        event.preventDefault();
        return;
      }

      if (select.value === unfollowStatusValue) {
        const confirmed = window.confirm(
          helpers.unfollowPrompt(form.dataset.itemType || ""),
        );

        if (!confirmed) {
          event.preventDefault();
          helpers.resetSelectToCurrentValue(select);
          return;
        }

        if (form.dataset.itemType === "run") {
          const trackedIssues = helpers.getDatasetCount(
            form,
            "trackedIssueCount",
          );

          if (trackedIssues > 0) {
            const removeIssues = window.confirm(
              `Also unfollow the ${trackedIssues} saved ${helpers.issueLabel(trackedIssues)} from this run?`,
            );

            if (removeIssues) {
              const removeInput = form.querySelector(
                "input[name='remove_issues']",
              );

              if (removeInput) {
                removeInput.value = "1";
              }
            }
          }
        }

        return;
      }

      if (form.dataset.itemType === "run") {
        const totalIssues = helpers.getDatasetCount(
          form,
          "runIssueCount",
        );
        const trackedIssues = helpers.getDatasetCount(
          form,
          "trackedIssueCount",
        );
        const message = helpers.applyRunStatusMessage(
          select.value,
          totalIssues,
          trackedIssues,
        );
        const applyInput = form.querySelector(
          "input[name='apply_to_issues']",
        );

        if (applyInput) {
          applyInput.value = "";
        }

        if (message && window.confirm(message) && applyInput) {
          applyInput.value = "1";
        }
      }
    }

    async function handleFollowSubmit(form, event) {
      event.preventDefault();

      const itemType = form.dataset.itemType || "item";
      const submitter =
        event.submitter ||
        form.querySelector("button[type='submit']");
      const originalButtonText = submitter
        ? submitter.textContent
        : "";
      let modalOptions = {};

      if (submitter) {
        submitter.disabled = true;
        submitter.textContent = "Loading...";
      }

      try {
        if (itemType === "run") {
          try {
            const followOptions = await fetchRunFollowOptions(form);
            modalOptions = {
              issues: followOptions.issues || [],
              issueStatusChoices:
                followOptions.issue_status_choices || [],
            };
          } catch (error) {
            modalOptions = {
              error: error.message,
            };
          }
        }

        while (true) {
          const modalResult = await openStatusModal(
            itemType,
            modalOptions,
          );

          if (!modalResult) {
            return;
          }

          const formData = new FormData(form);
          formData.set(
            "status",
            modalResult.status || "planned",
          );

          if (itemType === "run") {
            setRunIssueFormData(formData, modalResult);
          }

          if (submitter) {
            submitter.textContent = "Saving...";
          }

          try {
            const data = await postTrackingForm(
              form.action,
              formData,
            );

            if (data && data.tracking) {
              replaceMatchingTrackingCells(
                form.action,
                data.tracking,
              );
            }

            return;
          } catch (error) {
            if (itemType !== "run") {
              window.alert(error.message);
              return;
            }

            modalOptions = {
              ...modalOptions,
              error: error.message,
            };
          }
        }
      } finally {
        if (submitter && document.body.contains(submitter)) {
          submitter.disabled = false;
          submitter.textContent = originalButtonText;
        }
      }
    }

    function bindTrackingForm(form) {
      if (!form || form.dataset.trackingBound === "1") {
        return;
      }

      form.dataset.trackingBound = "1";
      form.addEventListener("submit", async function (event) {
        const select = form.querySelector(
          "select[name='status']",
        );

        if (form.dataset.trackFollow !== undefined) {
          await handleFollowSubmit(form, event);
          return;
        }

        if (select) {
          handleTrackedStatusSubmit(form, select, event);
        }
      });
    }

    document
      .querySelectorAll("[data-tracking-form]")
      .forEach(bindTrackingForm);

    document
      .querySelectorAll("[data-auto-submit]")
      .forEach(helpers.bindAutoSubmit);

    listing.init({ createRow });
  });
})();
