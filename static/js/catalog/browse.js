document.addEventListener("DOMContentLoaded", function () {
    const unfollowStatusValue = "__unfollow__";
    const dropdowns = Array.from(document.querySelectorAll(".searchable-dropdown"));
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

    function applySectionVisibilityToggle(toggle) {
        const targetSection = toggle.dataset.targetSection;

        if (!targetSection) {
            return;
        }

        const section = document.querySelector(`[data-load-section="${targetSection}"]`);

        if (!section) {
            return;
        }

        const shouldShow = toggle.checked;

        section.classList.toggle("d-none", !shouldShow);
        section.hidden = !shouldShow;
    }

    function applyAllSectionVisibilityToggles() {
        document.querySelectorAll("[data-section-visibility-toggle]").forEach(function (toggle) {
            applySectionVisibilityToggle(toggle);
        });
    }

    document.addEventListener("change", function (event) {
        const toggle = event.target.closest("[data-section-visibility-toggle]");

        if (!toggle) {
            return;
        }

        applySectionVisibilityToggle(toggle);
    });

    applyAllSectionVisibilityToggles();

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

    function clearElement(element) {
        while (element.firstChild) {
            element.removeChild(element.firstChild);
        }
    }

    function createOptionElement(option) {
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

    function renderOptions(optionsContainer, noResultsMessage, options) {
        clearElement(optionsContainer);

        options.forEach(function (option) {
            optionsContainer.appendChild(createOptionElement(option));
        });

        if (noResultsMessage) {
            noResultsMessage.classList.toggle("d-none", options.length !== 0);
        }
    }

    dropdowns.forEach(function (dropdown) {
        const searchInput = dropdown.querySelector("[data-dropdown-search]");
        const optionsContainer = dropdown.querySelector("[data-dropdown-options]");
        const noResultsMessage = dropdown.querySelector("[data-no-results]");
        const dropdownButton = dropdown.querySelector("[data-bs-toggle='dropdown']");
        const optionsUrl = dropdown.dataset.optionsUrl;
        const optionsKind = dropdown.dataset.optionsKind;

        if (!searchInput || !optionsContainer || !dropdownButton || !optionsUrl || !optionsKind) {
            return;
        }

        let debounceTimer = null;
        let latestRequestNumber = 0;

        function fetchOptions() {
            latestRequestNumber += 1;

            const requestNumber = latestRequestNumber;
            const url = new URL(optionsUrl, window.location.origin);
            const searchValue = searchInput.value.trim();

            url.searchParams.set("kind", optionsKind);

            if (searchValue) {
                url.searchParams.set("q", searchValue);
            }

            if (dropdown.dataset.selectedId) {
                url.searchParams.set("selected", dropdown.dataset.selectedId);
            }

            if (dropdown.dataset.filterPublisherId) {
                url.searchParams.set("publisher", dropdown.dataset.filterPublisherId);
            }

            if (dropdown.dataset.filterRunId) {
                url.searchParams.set("run", dropdown.dataset.filterRunId);
            }

            fetch(url.toString(), {
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                },
            })
                .then(function (response) {
                    if (!response.ok) {
                        throw new Error("Dropdown option request failed.");
                    }

                    return response.json();
                })
                .then(function (data) {
                    if (requestNumber !== latestRequestNumber) {
                        return;
                    }

                    renderOptions(optionsContainer, noResultsMessage, data.options || []);
                })
                .catch(function () {
                    if (noResultsMessage) {
                        noResultsMessage.classList.remove("d-none");
                    }
                });
        }

        function scheduleFetchOptions() {
            window.clearTimeout(debounceTimer);

            debounceTimer = window.setTimeout(function () {
                fetchOptions();
            }, 150);
        }

        searchInput.addEventListener("input", scheduleFetchOptions);

        searchInput.addEventListener("click", function (event) {
            event.stopPropagation();
        });

        dropdownButton.addEventListener("shown.bs.dropdown", function () {
            searchInput.focus();
            searchInput.select();
        });
    });

    function getCountFromDataset(source, name) {
        const value = Number(source.dataset[name] || "0");

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

    function itemTypeLabel(itemType) {
        const labels = {
            run: "run",
            issue: "issue",
            volume: "volume",
        };

        return labels[itemType] || "item";
    }

    function unfollowPrompt(itemType) {
        if (itemType === "issue") {
            return "Are you sure you want to unfollow this issue?";
        }

        if (itemType === "volume") {
            return "Are you sure you want to remove this volume from My Comics?";
        }

        if (itemType === "run") {
            return "Are you sure you want to unfollow this run?";
        }

        return "Are you sure you want to unfollow this item?";
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
        clearElement(select);

        choices.forEach(function (choice) {
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
        individualLabel.setAttribute("for", "tracking-individual-issue-statuses");
        individualLabel.textContent = "Set status for individual issues";
        individualCheck.appendChild(individualInput);
        individualCheck.appendChild(individualLabel);

        sharedIssueStatusGroup.className = "mt-3";
        sharedIssueStatusGroup.dataset.sharedIssueStatusGroup = "";
        sharedIssueStatusLabel.className = "form-label erc-muted";
        sharedIssueStatusLabel.setAttribute("for", "tracking-issue-status-select");
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
            followIssuesSettings.classList.toggle("d-none", !followIssuesInput.checked);
        });

        individualInput.addEventListener("change", function () {
            sharedIssueStatusGroup.classList.toggle("d-none", individualInput.checked);
            individualIssueStatusGroup.classList.toggle("d-none", !individualInput.checked);
        });

        statusModalSelect.addEventListener("change", function () {
            if (!followIssuesInput.checked) {
                sharedIssueStatusSelect.value = statusModalSelect.value;
            }
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

    function renderIndividualIssueStatusRows(issues, choices, defaultStatus) {
        const controls = ensureStatusModalControls();

        clearElement(controls.individualIssueStatusList);

        if (!issues.length) {
            const emptyMessage = document.createElement("p");

            emptyMessage.className = "erc-muted mb-0";
            emptyMessage.textContent = "No issues are currently in this run.";
            controls.individualIssueStatusList.appendChild(emptyMessage);
            return;
        }

        issues.forEach(function (issue) {
            const row = document.createElement("div");
            const labelWrap = document.createElement("div");
            const label = document.createElement("div");
            const meta = document.createElement("div");
            const select = document.createElement("select");
            const selectedStatus = issue.status || defaultStatus;

            row.className = "d-flex flex-column flex-md-row gap-2 justify-content-between align-items-md-center py-2 border-top border-secondary";
            labelWrap.className = "me-md-3";
            label.className = "fw-semibold";
            label.textContent = issue.label || `Issue ${issue.id}`;
            meta.className = "erc-muted small";
            meta.textContent = issue.meta || "";
            select.className = "form-select form-select-sm";
            select.name = `issue_status_${issue.id}`;
            select.dataset.issueId = issue.id;

            populateSelect(select, choices, selectedStatus);

            labelWrap.appendChild(label);
            labelWrap.appendChild(meta);
            row.appendChild(labelWrap);
            row.appendChild(select);
            controls.individualIssueStatusList.appendChild(row);
        });
    }

    function resetRunModalControls(options) {
        const controls = ensureStatusModalControls();
        const issues = options && options.issues ? options.issues : [];
        const issueChoices = options && options.issue_status_choices ? options.issue_status_choices : optionObjectsFromSelect(statusModalSelect);

        controls.runOptions.classList.add("d-none");
        controls.followIssuesInput.checked = false;
        controls.followIssuesInput.disabled = false;
        controls.followIssuesSettings.classList.add("d-none");
        controls.individualInput.checked = false;
        controls.sharedIssueStatusGroup.classList.remove("d-none");
        controls.individualIssueStatusGroup.classList.add("d-none");

        populateSelect(controls.sharedIssueStatusSelect, issueChoices, statusModalSelect.value);
        renderIndividualIssueStatusRows(issues, issueChoices, statusModalSelect.value);

        if (statusModalContext && statusModalContext.itemType === "run") {
            controls.runOptions.classList.remove("d-none");

            if (!issues.length) {
                controls.followIssuesInput.disabled = true;
            }
        }
    }

    function buildStatusModalResult() {
        const controls = ensureStatusModalControls();

        if (!statusModalContext || statusModalContext.itemType !== "run") {
            return {
                status: statusModalSelect.value,
            };
        }

        const individualIssueStatuses = [];

        controls.individualIssueStatusList.querySelectorAll("select[data-issue-id]").forEach(function (select) {
            individualIssueStatuses.push({
                issueId: select.dataset.issueId,
                status: select.value,
            });
        });

        return {
            status: statusModalSelect.value,
            followIssues: controls.followIssuesInput.checked,
            issueStatusMode: controls.individualInput.checked ? "individual" : "single",
            issueStatus: controls.sharedIssueStatusSelect.value || statusModalSelect.value,
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
        statusModalCopy.textContent = `Choose the status to save for this ${itemTypeLabel(itemType)}.`;
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
        statusModalElement.addEventListener("hidden.bs.modal", function () {
            if (statusModalResolve) {
                const resolve = statusModalResolve;
                statusModalResolve = null;
                resolve(null);
            }

            statusModalContext = null;
        });
    }

    function addCell(row, text, options) {
        const cell = document.createElement("td");
        const cellOptions = options || {};
        const safeText = text || "";

        if (cellOptions.alignEnd) {
            cell.classList.add("text-end");
        }

        if (cellOptions.bold) {
            cell.classList.add("fw-semibold");
        }

        if (cellOptions.linkLike) {
            const content = cellOptions.href ? document.createElement("a") : document.createElement("span");

            if (cellOptions.href) {
                content.href = cellOptions.href;
            }

            content.className = "erc-data-link";
            content.textContent = safeText;
            cell.appendChild(content);
        } else if (cellOptions.muted) {
            const mutedText = document.createElement("span");
            mutedText.className = "erc-muted";
            mutedText.textContent = safeText;
            cell.appendChild(mutedText);
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
    }

    function createClickableRow(item) {
        const row = createClickableRowElement(item);

        bindClickableRow(row);

        return row;
    }

    function createClickableRowElement(item) {
        const row = document.createElement("tr");

        row.className = "clickable-row";
        row.dataset.rowUrl = item.row_url;
        row.tabIndex = 0;
        row.setAttribute("aria-label", item.aria_label || "Open details");

        return row;
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

    function bindAutoSubmitSelect(select) {
        if (select.dataset.autoSubmitBound === "1") {
            return;
        }

        select.dataset.autoSubmitBound = "1";

        select.addEventListener("change", function () {
            select.form.requestSubmit();
        });
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

        form.appendChild(createHiddenInput("csrfmiddlewaretoken", getCsrfToken()));
        form.appendChild(createHiddenInput("next", currentNextValue()));

        if (tracking.item_type === "run") {
            form.dataset.runIssueCount = String(tracking.catalog_issue_count || 0);
            form.dataset.trackedIssueCount = String(tracking.tracked_issue_count || 0);
            form.appendChild(createHiddenInput("apply_to_issues", ""));
            form.appendChild(createHiddenInput("issue_status", ""));
            form.appendChild(createHiddenInput("issue_status_mode", ""));
            form.appendChild(createHiddenInput("remove_issues", ""));
        }

        if (tracking.tracked) {
            form.dataset.currentStatus = tracking.status || "";

            const select = document.createElement("select");

            select.name = "status";
            select.className = "form-select form-select-sm";
            select.dataset.autoSubmit = "";

            (tracking.status_choices || []).forEach(function (choice) {
                const option = document.createElement("option");

                option.value = choice.value;
                option.textContent = choice.label;

                if (choice.value === tracking.status) {
                    option.selected = true;
                    option.defaultSelected = true;
                }

                select.appendChild(option);
            });

            const unfollowOption = document.createElement("option");
            unfollowOption.value = unfollowStatusValue;
            unfollowOption.textContent = tracking.item_type === "volume" ? "Remove" : "Unfollow";
            select.appendChild(unfollowOption);

            bindAutoSubmitSelect(select);
            form.appendChild(select);
        } else {
            form.dataset.trackFollow = "";

            const button = document.createElement("button");

            button.type = "submit";
            button.className = "btn btn-outline-light btn-sm erc-track-button";
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
        const row = createClickableRow(item);

        addCell(row, runTitleWithYear(item), {
            bold: true,
            linkLike: true,
            href: item.row_url,
        });
        addCell(row, item.publisher, {
            meta: item.status,
        });
        addCell(row, item.issue_count, {
            muted: item.issue_count_muted,
        });
        row.appendChild(createTrackingCell(item.tracking));

        return row;
    }

    function createVolumeRow(item) {
        const row = createClickableRow(item);

        addCell(row, item.volume, {
            bold: true,
            linkLike: true,
            href: item.row_url,
        });
        addCell(row, item.run, {
            linkLike: true,
        });
        addCell(row, item.release_date, {
            muted: item.release_date_muted,
        });
        row.appendChild(createTrackingCell(item.tracking));

        return row;
    }

    function createIssueRow(item) {
        const row = createClickableRow(item);

        addCell(row, item.issue, {
            bold: true,
            linkLike: true,
            href: item.row_url,
        });
        addCell(row, item.run, {
            linkLike: true,
        });
        addCell(row, item.published_date, {
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

        return createIssueRow(item);
    }

    function updateSectionControls(section) {
        const target = section.querySelector("[data-load-target]");
        const loadedCount = section.querySelector("[data-loaded-count]");
        const loadButton = section.querySelector("[data-load-more]");
        const hideButton = section.querySelector("[data-hide-more]");

        if (!target) {
            return;
        }

        const visibleCount = target.querySelectorAll("tr").length;

        if (loadedCount) {
            loadedCount.textContent = "Showing " + visibleCount + " loaded";
        }

        if (loadButton) {
            loadButton.dataset.offset = String(visibleCount);
        }

        if (hideButton) {
            const minVisible = Number(hideButton.dataset.minVisible || "5");
            hideButton.classList.toggle("d-none", visibleCount <= minVisible);
        }
    }

    function buildItemsUrl(button) {
        const url = new URL(button.dataset.itemsUrl, window.location.origin);

        url.searchParams.set("kind", button.dataset.kind);
        url.searchParams.set("offset", button.dataset.offset || "0");

        if (button.dataset.filterPublisherId) {
            url.searchParams.set("publisher", button.dataset.filterPublisherId);
        }

        if (button.dataset.filterRunId) {
            url.searchParams.set("run", button.dataset.filterRunId);
        }

        if (button.dataset.filterIssueId) {
            url.searchParams.set("issue", button.dataset.filterIssueId);
        }

        if (button.dataset.filterVolumeId) {
            url.searchParams.set("volume", button.dataset.filterVolumeId);
        }

        return url;
    }

    function setFormDisabled(form, disabled) {
        form.querySelectorAll("button, select, input").forEach(function (control) {
            if (control.type === "hidden") {
                return;
            }

            control.disabled = disabled;
        });
    }

    function normalizeUrl(value) {
        return new URL(value, window.location.origin).toString();
    }

    function sameActionUrl(left, right) {
        return normalizeUrl(left) === normalizeUrl(right);
    }

    function replaceTrackingCellForForm(form, tracking) {
        const cell = form.closest(".erc-track-cell");

        if (!cell || !tracking) {
            return;
        }

        cell.replaceWith(createTrackingCell(tracking));
    }

    function replaceMatchingTrackingCells(actionUrl, tracking) {
        document.querySelectorAll("[data-tracking-form]").forEach(function (form) {
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
            const message = data && data.error ? data.error : "Could not save tracking status.";
            throw new Error(message);
        }

        return data;
    }

    function runFollowOptionsUrl(actionUrl) {
        const url = new URL(actionUrl, window.location.origin);

        url.pathname = url.pathname.replace(/\/status\/?$/, "/follow-options/");

        return url;
    }

    async function fetchRunFollowOptions(form) {
        const response = await fetch(runFollowOptionsUrl(form.action).toString(), {
            headers: {
                "X-Requested-With": "XMLHttpRequest",
            },
        });

        const data = await response.json();

        if (response.status === 401 && data && data.redirect_url) {
            window.location.href = data.redirect_url;
            return null;
        }

        if (!response.ok || !data || data.ok === false) {
            throw new Error("Could not load the issues for this run.");
        }

        return data;
    }

    async function maybeHandleRunReadOffer(offer) {
        if (!offer || !offer.action_url || !offer.message) {
            return;
        }

        const confirmed = window.confirm(offer.message);

        if (!confirmed) {
            return;
        }

        const formData = new FormData();

        formData.set("csrfmiddlewaretoken", getCsrfToken());
        formData.set("next", currentNextValue());
        formData.set("status", "read");

        const data = await postTrackingForm(offer.action_url, formData);

        if (data && data.tracking) {
            replaceMatchingTrackingCells(offer.action_url, data.tracking);
        }
    }

    function addRunFollowFieldsToFormData(formData, selectedStatus) {
        if (!selectedStatus.followIssues) {
            formData.set("apply_to_issues", "");
            formData.set("issue_status", "");
            formData.set("issue_status_mode", "");
            return;
        }

        formData.set("apply_to_issues", "1");
        formData.set("issue_status_mode", selectedStatus.issueStatusMode);

        if (selectedStatus.issueStatusMode === "individual") {
            formData.set("issue_status", "");

            selectedStatus.individualIssueStatuses.forEach(function (issueStatus) {
                formData.set(`issue_status_${issueStatus.issueId}`, issueStatus.status);
            });

            return;
        }

        formData.set("issue_status", selectedStatus.issueStatus || selectedStatus.status);
    }

    async function buildTrackingFormData(form) {
        const formData = new FormData(form);
        const itemType = form.dataset.itemType;
        const select = form.querySelector("select[name='status']");
        const currentStatus = form.dataset.currentStatus || "";
        const totalIssues = getCountFromDataset(form, "runIssueCount");
        const trackedIssues = getCountFromDataset(form, "trackedIssueCount");

        formData.set("next", currentNextValue());

        if (form.dataset.trackFollow !== undefined) {
            let followOptions = {};

            if (itemType === "run") {
                try {
                    followOptions = await fetchRunFollowOptions(form);
                } catch (error) {
                    followOptions = {
                        error: error.message || "Could not load the issues for this run.",
                        issues: [],
                    };
                }
            }

            const selectedStatus = await openStatusModal(itemType, followOptions || {});

            if (!selectedStatus) {
                return null;
            }

            formData.set("status", selectedStatus.status);

            if (itemType === "run") {
                addRunFollowFieldsToFormData(formData, selectedStatus);
            }

            return formData;
        }

        if (!select) {
            return formData;
        }

        if (select.value === currentStatus) {
            return null;
        }

        if (select.value === unfollowStatusValue) {
            const confirmed = window.confirm(unfollowPrompt(itemType));

            if (!confirmed) {
                select.value = currentStatus;
                return null;
            }

            if (itemType === "run" && trackedIssues > 0) {
                const removeIssues = window.confirm(
                    `Also unfollow the ${trackedIssues} saved ${issueLabel(trackedIssues)} from this run?`
                );

                if (removeIssues) {
                    formData.set("remove_issues", "1");
                } else {
                    formData.set("remove_issues", "");
                }
            }

            formData.set("status", unfollowStatusValue);
            return formData;
        }

        if (itemType === "run") {
            const message = applyStatusMessage(select.value, totalIssues, trackedIssues);

            if (message && window.confirm(message)) {
                formData.set("apply_to_issues", "1");
            } else {
                formData.set("apply_to_issues", "");
            }
        }

        formData.set("status", select.value);
        return formData;
    }

    function bindTrackingForm(form) {
        if (form.dataset.trackingBound === "1") {
            return;
        }

        form.dataset.trackingBound = "1";

        form.addEventListener("submit", async function (event) {
            event.preventDefault();

            if (form.dataset.submitting === "1") {
                return;
            }

            form.dataset.submitting = "1";
            setFormDisabled(form, true);

            try {
                const formData = await buildTrackingFormData(form);

                if (!formData) {
                    setFormDisabled(form, false);
                    form.dataset.submitting = "";
                    return;
                }

                const data = await postTrackingForm(form.action, formData);

                if (!data) {
                    return;
                }

                if (data.tracking) {
                    replaceTrackingCellForForm(form, data.tracking);
                }

                await maybeHandleRunReadOffer(data.run_read_offer);
            } catch (error) {
                if (form.dataset.trackFollow !== undefined) {
                    showStatusModalError(error.message || "Could not save tracking status.");
                    statusModal.show();
                } else {
                    window.alert(error.message || "Could not save tracking status.");
                }

                setFormDisabled(form, false);
            } finally {
                form.dataset.submitting = "";
            }
        });
    }

    document.querySelectorAll("[data-auto-submit]").forEach(bindAutoSubmitSelect);
    document.querySelectorAll("[data-tracking-form]").forEach(bindTrackingForm);

    document.querySelectorAll("[data-load-more]").forEach(function (button) {
        button.addEventListener("click", function () {
            const section = button.closest("[data-load-section]");
            const target = section.querySelector("[data-load-target]");
            const originalText = button.textContent;
            const url = buildItemsUrl(button);

            button.disabled = true;
            button.textContent = "Loading...";

            fetch(url.toString(), {
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                },
            })
                .then(function (response) {
                    if (!response.ok) {
                        throw new Error("Load more request failed.");
                    }

                    return response.json();
                })
                .then(function (data) {
                    const items = data.items || [];

                    items.forEach(function (item) {
                        target.appendChild(createRow(button.dataset.kind, item));
                    });

                    button.disabled = false;
                    button.textContent = originalText;
                    button.classList.toggle("d-none", !data.has_more || items.length === 0);

                    updateSectionControls(section);
                })
                .catch(function () {
                    button.disabled = false;
                    button.textContent = "Could not load more. Try again.";
                });
        });
    });

    document.querySelectorAll("[data-hide-more]").forEach(function (button) {
        button.addEventListener("click", function () {
            const section = button.closest("[data-load-section]");
            const target = section.querySelector("[data-load-target]");
            const loadButton = section.querySelector("[data-load-more]");
            const minVisible = Number(button.dataset.minVisible || "5");
            const hideCount = Number(button.dataset.hideCount || "10");
            const rows = Array.from(target.querySelectorAll("tr"));
            const removableCount = Math.min(hideCount, Math.max(rows.length - minVisible, 0));

            for (let index = 0; index < removableCount; index += 1) {
                rows[rows.length - 1 - index].remove();
            }

            if (loadButton) {
                loadButton.classList.remove("d-none");
                loadButton.disabled = false;
            }

            updateSectionControls(section);
        });
    });

    document.querySelectorAll("[data-load-section]").forEach(function (section) {
        updateSectionControls(section);
    });
});