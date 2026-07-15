document.addEventListener("DOMContentLoaded", function () {
    const unfollowStatusValue = "__unfollow__";
    const dropdownOptionPageSize = 10;
    const sectionPageSize = 10;
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

    function countRenderedOptions(optionsContainer) {
        return optionsContainer.querySelectorAll("[data-dropdown-option]").length;
    }

    function renderOptions(optionsContainer, noResultsMessage, options, append) {
        if (!append) {
            clearElement(optionsContainer);
        }

        options.forEach(function (option) {
            optionsContainer.appendChild(createOptionElement(option));
        });

        if (noResultsMessage) {
            noResultsMessage.classList.toggle(
                "d-none",
                countRenderedOptions(optionsContainer) !== 0,
            );
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
        let isLoadingOptions = false;
        let nextOffset = countRenderedOptions(optionsContainer);
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

            if (dropdown.dataset.filterPublisherId) {
                url.searchParams.set("publisher", dropdown.dataset.filterPublisherId);
            }

            if (dropdown.dataset.filterRunId) {
                url.searchParams.set("run", dropdown.dataset.filterRunId);
            }

            return url;
        }

        function fetchOptions(options) {
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
                        throw new Error("Dropdown option request failed.");
                    }

                    return response.json();
                })
                .then(function (data) {
                    if (requestNumber !== latestRequestNumber) {
                        return;
                    }

                    const optionRows = data.options || [];

                    renderOptions(optionsContainer, noResultsMessage, optionRows, append);

                    nextOffset = Number(data.next_offset || offset + optionRows.length);
                    hasMoreOptions = Boolean(data.has_more);
                    hasLoadedOptions = true;
                })
                .catch(function () {
                    if (noResultsMessage) {
                        noResultsMessage.classList.remove("d-none");
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
            const scrollBottom = optionsContainer.scrollTop + optionsContainer.clientHeight;
            const nearBottom = scrollBottom >= optionsContainer.scrollHeight - 32;

            if (nearBottom) {
                fetchOptions({ append: true });
            }
        });

        dropdownButton.addEventListener("shown.bs.dropdown", function () {
            searchInput.focus();
            searchInput.select();

            if (!hasLoadedOptions && countRenderedOptions(optionsContainer) === 0) {
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
    });

    function getCountFromDataset(source, name) {
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

    function itemTypeLabel(itemType) {
        const labels = {
            run: "run",
            issue: "issue",
            volume: "volume",
            one_shot: "one-shot",
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

        if (itemType === "one_shot") {
            return "Are you sure you want to unfollow this one-shot?";
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

    function createIndividualIssueStatusRow(issue, choices, selectedStatus) {
        const wrapper = document.createElement("div");
        const label = document.createElement("label");
        const select = document.createElement("select");

        wrapper.className = "d-flex flex-column gap-1 mb-3";
        label.className = "form-label erc-muted mb-0";
        label.textContent = issue.label || "Issue";
        select.className = "form-select";
        select.dataset.issueId = String(issue.id);
        populateSelect(select, choices, issue.status || selectedStatus || "planned");

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
        const isRun = statusModalContext && statusModalContext.itemType === "run";
        const issueChoices = options.issueStatusChoices || optionObjectsFromSelect(statusModalSelect);
        const selectedStatus = statusModalSelect ? statusModalSelect.value : "planned";
        const issues = options.issues || [];

        controls.runOptions.classList.toggle("d-none", !isRun);
        controls.followIssuesInput.checked = false;
        controls.followIssuesSettings.classList.add("d-none");
        controls.individualInput.checked = false;
        controls.sharedIssueStatusGroup.classList.remove("d-none");
        controls.individualIssueStatusGroup.classList.add("d-none");
        populateSelect(controls.sharedIssueStatusSelect, issueChoices, selectedStatus);
        clearElement(controls.individualIssueStatusList);

        issues.forEach(function (issue) {
            controls.individualIssueStatusList.appendChild(
                createIndividualIssueStatusRow(issue, issueChoices, selectedStatus),
            );
        });
    }

    function buildStatusModalResult() {
        const controls = ensureStatusModalControls();
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

    function createClickableRow(item) {
        const row = createClickableRowElement(item);
        bindClickableRow(row);
        return row;
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
        addCell(row, runTitleWithYear(item), { bold: true, linkLike: true, href: item.row_url });
        addCell(row, item.publisher, { meta: item.status });
        addCell(row, item.issue_count, { muted: item.issue_count_muted });
        row.appendChild(createTrackingCell(item.tracking));
        return row;
    }

    function createVolumeRow(item) {
        const row = createClickableRow(item);
        addCell(row, item.volume, { bold: true, linkLike: true, href: item.row_url });
        addCell(row, item.run, { linkLike: true });
        addCell(row, item.release_date, { muted: item.release_date_muted });
        row.appendChild(createTrackingCell(item.tracking));
        return row;
    }

    function createIssueRow(item) {
        const row = createClickableRow(item);
        addCell(row, item.issue, { bold: true, linkLike: true, href: item.row_url });
        addCell(row, item.run, { linkLike: true });
        addCell(row, item.published_date, { muted: item.published_date_muted });
        row.appendChild(createTrackingCell(item.tracking));
        return row;
    }

    function createOneShotRow(item) {
        const row = createClickableRow(item);
        addCell(row, item.title, { bold: true, linkLike: true, href: item.row_url });
        addCell(row, item.publisher);
        addCell(row, item.published_date, { muted: item.published_date_muted });
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

    function rowCount(section) {
        const target = section.querySelector("[data-load-target]");
        return target ? target.querySelectorAll("tr").length : 0;
    }

    function updateSectionControls(section) {
        const loadedCount = section.querySelector("[data-loaded-count]");
        const visibleCount = rowCount(section);

        section.dataset.offset = String(visibleCount);

        if (loadedCount) {
            loadedCount.textContent = "Showing " + visibleCount + " loaded";
        }
    }

    function buildItemsUrl(section) {
        const url = new URL(section.dataset.itemsUrl, window.location.origin);

        url.searchParams.set("kind", section.dataset.kind || section.dataset.loadSection || "");
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

        if (section.dataset.filterVolumeId) {
            url.searchParams.set("volume", section.dataset.filterVolumeId);
        }

        if (section.dataset.filterOneShotId) {
            url.searchParams.set("one_shot", section.dataset.filterOneShotId);
        }

        return url;
    }

    function setSectionLoading(section, isLoading) {
        section.dataset.loading = isLoading ? "1" : "0";
    }

    function appendEmptyRow(section) {
        const target = section.querySelector("[data-load-target]");
        const colCount = section.querySelectorAll("thead th").length || 4;
        const label = section.dataset.emptyMessage || "No items match this filter.";

        if (!target || target.querySelector("[data-empty-row]")) {
            return;
        }

        const row = document.createElement("tr");
        row.dataset.emptyRow = "";

        const cell = document.createElement("td");
        cell.colSpan = colCount;
        cell.className = "text-center erc-muted py-4";
        cell.textContent = label;

        row.appendChild(cell);
        target.appendChild(row);
    }

    function removeEmptyRows(section) {
        section.querySelectorAll("[data-empty-row]").forEach(function (row) {
            row.remove();
        });
    }

    function loadSectionRows(section) {
        const target = section.querySelector("[data-load-target]");

        if (!target || section.dataset.loading === "1" || section.dataset.hasMore === "0") {
            return Promise.resolve();
        }

        setSectionLoading(section, true);

        return fetch(buildItemsUrl(section).toString(), {
            headers: {
                "X-Requested-With": "XMLHttpRequest",
            },
        })
            .then(function (response) {
                if (!response.ok) {
                    throw new Error("Could not load more rows.");
                }

                return response.json();
            })
            .then(function (data) {
                const items = data.items || [];

                removeEmptyRows(section);

                items.forEach(function (item) {
                    target.appendChild(createRow(section.dataset.kind || section.dataset.loadSection, item));
                });

                section.dataset.hasMore = data.has_more ? "1" : "0";
                section.dataset.browseSectionLoaded = "1";
                updateSectionControls(section);

                if (rowCount(section) === 0) {
                    appendEmptyRow(section);
                }
            })
            .catch(function (error) {
                window.alert(error.message);
            })
            .finally(function () {
                setSectionLoading(section, false);
            });
    }

    function maybeLoadMoreFromScroll(scrollContainer) {
        const section = scrollContainer.closest("[data-load-section]");

        if (!section || section.hidden || section.dataset.hasMore === "0") {
            return;
        }

        const scrollBottom = scrollContainer.scrollTop + scrollContainer.clientHeight;
        const nearBottom = scrollBottom >= scrollContainer.scrollHeight - 96;

        if (nearBottom) {
            loadSectionRows(section);
        }
    }

    function ensureSectionLoaded(section) {
        if (!section || section.dataset.browseSectionLoaded === "1") {
            return;
        }

        loadSectionRows(section);
    }

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

        if (shouldShow) {
            ensureSectionLoaded(section);
        }
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

    document.querySelectorAll("[data-section-scroll]").forEach(function (scrollContainer) {
        scrollContainer.addEventListener("scroll", function () {
            maybeLoadMoreFromScroll(scrollContainer);
        });
    });

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
        const response = await fetch(runFollowOptionsUrl(form.action), {
            headers: {
                "X-Requested-With": "XMLHttpRequest",
            },
        });

        if (!response.ok) {
            throw new Error("Could not load run issue options.");
        }

        return response.json();
    }

    function setRunIssueFormData(formData, modalResult) {
        formData.set("apply_to_issues", modalResult.followIssues ? "1" : "");

        if (!modalResult.followIssues) {
            formData.set("issue_status", "");
            formData.set("issue_status_mode", "");
            return;
        }

        formData.set("issue_status_mode", modalResult.issueStatusMode || "single");

        if (modalResult.issueStatusMode === "individual") {
            formData.set("issue_status", "");

            (modalResult.individualIssueStatuses || []).forEach(function (issueStatus) {
                formData.set(`issue_status_${issueStatus.issueId}`, issueStatus.status);
            });
        } else {
            formData.set("issue_status", modalResult.issueStatus || modalResult.status);
        }
    }

    function selectCurrentValue(select) {
        const defaultOption = Array.from(select.options).find(function (option) {
            return option.defaultSelected;
        });

        if (defaultOption) {
            select.value = defaultOption.value;
        }
    }

    async function handleTrackedStatusSubmit(form, select, event) {
        const currentStatus = form.dataset.currentStatus || "";

        if (!select || select.value === currentStatus) {
            event.preventDefault();
            return;
        }

        if (select.value === unfollowStatusValue) {
            const confirmed = window.confirm(unfollowPrompt(form.dataset.itemType || ""));

            if (!confirmed) {
                event.preventDefault();
                selectCurrentValue(select);
                return;
            }

            if (form.dataset.itemType === "run") {
                const trackedIssues = getCountFromDataset(form, "trackedIssueCount");

                if (trackedIssues > 0) {
                    const removeIssues = window.confirm(
                        `Also unfollow the ${trackedIssues} saved ${issueLabel(trackedIssues)} from this run?`,
                    );

                    if (removeIssues) {
                        const removeInput = form.querySelector("input[name='remove_issues']");

                        if (removeInput) {
                            removeInput.value = "1";
                        }
                    }
                }
            }

            return;
        }

        if (form.dataset.itemType === "run") {
            const totalIssues = getCountFromDataset(form, "runIssueCount");
            const trackedIssues = getCountFromDataset(form, "trackedIssueCount");
            const message = applyStatusMessage(select.value, totalIssues, trackedIssues);
            const applyInput = form.querySelector("input[name='apply_to_issues']");

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
        const submitter = event.submitter || form.querySelector("button[type='submit']");
        const originalButtonText = submitter ? submitter.textContent : "";
        let runOptions = null;

        if (submitter) {
            submitter.disabled = true;
            submitter.textContent = "Loading...";
        }

        try {
            if (itemType === "run") {
                const followOptions = await fetchRunFollowOptions(form);

                runOptions = {
                    issues: followOptions.issues || [],
                    issueStatusChoices: followOptions.issue_status_choices || [],
                };
            }

            const modalResult = await openStatusModal(itemType, runOptions || {});

            if (!modalResult) {
                return;
            }

            const formData = new FormData(form);
            formData.set("status", modalResult.status || "planned");

            if (itemType === "run") {
                setRunIssueFormData(formData, modalResult);
            }

            if (submitter) {
                submitter.textContent = "Saving...";
            }

            const data = await postTrackingForm(form.action, formData);

            if (data && data.tracking) {
                replaceMatchingTrackingCells(form.action, data.tracking);
            }
        } catch (error) {
            if (itemType === "run") {
                const modalResult = await openStatusModal(itemType, {
                    ...(runOptions || {}),
                    error: error.message,
                });

                if (!modalResult) {
                    return;
                }
            } else {
                window.alert(error.message);
            }
        } finally {
            if (submitter && document.body.contains(submitter)) {
                submitter.disabled = false;
                submitter.textContent = originalButtonText;
            }
        }
    }

    function bindTrackingForm(form) {
        if (form.dataset.trackingBound === "1") {
            return;
        }

        form.dataset.trackingBound = "1";

        form.addEventListener("submit", async function (event) {
            const select = form.querySelector("select[name='status']");

            if (form.dataset.trackFollow !== undefined) {
                await handleFollowSubmit(form, event);
                return;
            }

            if (select) {
                await handleTrackedStatusSubmit(form, select, event);
            }
        });
    }

    document.querySelectorAll("[data-tracking-form]").forEach(bindTrackingForm);

    document.querySelectorAll("[data-auto-submit]").forEach(function (select) {
        bindAutoSubmitSelect(select);
    });

    document.querySelectorAll(".clickable-row").forEach(bindClickableRow);
    document.querySelectorAll("[data-load-section]").forEach(updateSectionControls);
    applyAllSectionVisibilityToggles();
});
