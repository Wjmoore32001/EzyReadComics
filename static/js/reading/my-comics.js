(function () {
  "use strict";

  const listing = window.EzyReadComicsComicLists;

  if (!listing) {
    return;
  }

  const helpers = listing.helpers;
  const unfollowStatusValue = helpers.UNFOLLOW_STATUS_VALUE;

  listing.onReady(function () {
    function bindRunStatusForm(form) {
      if (!form || form.dataset.runStatusBound === "1") {
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
        const currentStatus = form.dataset.currentStatus || "";
        const totalIssues = helpers.getDatasetCount(
          form,
          "runIssueCount",
        );
        const trackedIssues = helpers.getDatasetCount(
          form,
          "trackedIssueCount",
        );

        if (!select || !applyToIssuesInput || !removeIssuesInput) {
          return;
        }

        applyToIssuesInput.value = "";
        removeIssuesInput.value = "";

        if (select.value === currentStatus) {
          event.preventDefault();
          return;
        }

        if (select.value === unfollowStatusValue) {
          const confirmed = window.confirm(
            helpers.unfollowPrompt("run"),
          );

          if (!confirmed) {
            event.preventDefault();
            helpers.resetSelectToCurrentValue(select);
            return;
          }

          if (trackedIssues > 0) {
            const removeIssues = window.confirm(
              `Also unfollow the ${trackedIssues} saved ${helpers.issueLabel(trackedIssues)} from this run?`,
            );

            if (removeIssues) {
              removeIssuesInput.value = "1";
            }
          }

          return;
        }

        const message = helpers.applyRunStatusMessage(
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
      if (!form || form.dataset.itemStatusBound === "1") {
        return;
      }

      form.dataset.itemStatusBound = "1";
      form.addEventListener("submit", function (event) {
        const select = form.querySelector("select[name='status']");

        if (!select || select.value !== unfollowStatusValue) {
          return;
        }

        const confirmed = window.confirm(
          helpers.unfollowPrompt(form.dataset.itemType || ""),
        );

        if (!confirmed) {
          event.preventDefault();
          helpers.resetSelectToCurrentValue(select);
        }
      });
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
      form.dataset.runIssueCount = String(
        item.catalog_issue_count || 0,
      );
      form.dataset.trackedIssueCount = String(
        item.tracked_issue_count || 0,
      );

      form.appendChild(
        helpers.createHiddenInput(
          "csrfmiddlewaretoken",
          helpers.getCsrfToken(),
        ),
      );
      form.appendChild(
        helpers.createHiddenInput("next", helpers.currentNextValue()),
      );
      form.appendChild(
        helpers.createHiddenInput("apply_to_issues", ""),
      );
      form.appendChild(
        helpers.createHiddenInput("remove_issues", ""),
      );

      select.name = "status";
      select.className = "form-select form-select-sm";
      select.dataset.autoSubmit = "";
      helpers.addStatusOptions(
        select,
        item.status_choices || [],
        item.current_status,
        "Unfollow",
      );

      form.appendChild(select);
      bindRunStatusForm(form);
      helpers.bindAutoSubmit(select);
      cell.appendChild(form);
      return cell;
    }

    function createProgressStatusCell(
      item,
      itemType,
      unfollowLabel,
    ) {
      const cell = document.createElement("td");
      const form = document.createElement("form");
      const select = document.createElement("select");

      cell.className = "text-end erc-track-cell";
      form.action = item.action_url;
      form.method = "post";
      form.className = "erc-track-form";
      form.dataset.itemType = itemType;

      form.appendChild(
        helpers.createHiddenInput(
          "csrfmiddlewaretoken",
          helpers.getCsrfToken(),
        ),
      );
      form.appendChild(
        helpers.createHiddenInput("next", helpers.currentNextValue()),
      );

      select.name = "status";
      select.className = "form-select form-select-sm";
      select.dataset.autoSubmit = "";
      helpers.addStatusOptions(
        select,
        item.status_choices || [],
        item.current_status,
        unfollowLabel,
      );

      form.appendChild(select);
      bindItemStatusForm(form);
      helpers.bindAutoSubmit(select);
      cell.appendChild(form);
      return cell;
    }

    function createRunRow(item) {
      const row = helpers.createClickableRow(item);

      helpers.addCell(row, item.run, {
        bold: true,
        linkLike: true,
        href: item.row_url,
      });
      helpers.addCell(row, item.publisher);
      row.appendChild(createRunStatusCell(item));
      helpers.addCell(row, item.issue_count, {
        muted: item.issue_count_muted,
      });

      return row;
    }

    function createVolumeRow(item) {
      const row = helpers.createClickableRow(item);

      helpers.addCell(row, item.volume, {
        bold: true,
        linkLike: true,
        href: item.row_url,
      });
      helpers.addCell(row, item.run, {
        linkLike: true,
        href: item.run_url,
      });
      helpers.addCell(row, item.release_date, {
        muted: item.release_date_muted,
      });
      row.appendChild(
        createProgressStatusCell(item, "volume", "Remove"),
      );

      return row;
    }

    function createIssueRow(item) {
      const row = helpers.createClickableRow(item);

      helpers.addCell(row, item.issue, {
        bold: true,
        linkLike: true,
        href: item.row_url,
      });
      helpers.addCell(row, item.run, {
        linkLike: true,
        href: item.run_url,
      });
      helpers.addCell(row, item.published_date, {
        muted: item.published_date_muted,
      });
      row.appendChild(
        createProgressStatusCell(item, "issue", "Unfollow"),
      );

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
      row.appendChild(
        createProgressStatusCell(item, "one_shot", "Unfollow"),
      );

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

    document
      .querySelectorAll("[data-run-status-form]")
      .forEach(bindRunStatusForm);

    document
      .querySelectorAll("form[data-item-type]")
      .forEach(bindItemStatusForm);

    document
      .querySelectorAll("[data-auto-submit]")
      .forEach(helpers.bindAutoSubmit);

    listing.init({ createRow });
  });
})();
