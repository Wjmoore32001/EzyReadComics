document.addEventListener("DOMContentLoaded", function () {
    const unfollowStatusValue = "__unfollow__";
    const dropdowns = Array.from(document.querySelectorAll(".searchable-dropdown"));
    const statusModalElement = document.getElementById("tracking-status-modal");
    const statusModalTitle = document.getElementById("tracking-status-modal-title");
    const statusModalCopy = document.getElementById("tracking-status-modal-copy");
    const statusModalSelect = document.getElementById("tracking-status-select");
    const statusModalConfirm = document.querySelector("[data-status-modal-confirm]");
    const statusModal = statusModalElement ? bootstrap.Modal.getOrCreateInstance(statusModalElement) : null;

    let statusModalResolve = null;

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

    function openStatusModal(itemType) {
        if (!statusModal || !statusModalElement || !statusModalSelect) {
            return Promise.resolve("planned");
        }

        statusModalTitle.textContent = `Follow ${itemTypeLabel(itemType)}`;
        statusModalCopy.textContent = `Choose the status to save for this ${itemTypeLabel(itemType)}.`;
        statusModalSelect.value = "planned";

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
            resolveStatusModal(statusModalSelect.value);
        });
    }

    if (statusModalElement) {
        statusModalElement.addEventListener("hidden.bs.modal", function () {
            if (statusModalResolve) {
                const resolve = statusModalResolve;
                statusModalResolve = null;
                resolve(null);
            }
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

    async function buildTrackingFormData(form) {
        const formData = new FormData(form);
        const itemType = form.dataset.itemType;
        const select = form.querySelector("select[name='status']");
        const currentStatus = form.dataset.currentStatus || "";
        const totalIssues = getCountFromDataset(form, "runIssueCount");
        const trackedIssues = getCountFromDataset(form, "trackedIssueCount");

        formData.set("next", currentNextValue());

        if (form.dataset.trackFollow !== undefined) {
            const selectedStatus = await openStatusModal(itemType);

            if (!selectedStatus) {
                return null;
            }

            formData.set("status", selectedStatus);

            if (itemType === "run") {
                const message = applyStatusMessage(selectedStatus, totalIssues, trackedIssues);

                if (message && window.confirm(message)) {
                    formData.set("apply_to_issues", "1");
                } else {
                    formData.set("apply_to_issues", "");
                }
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
                window.alert(error.message || "Could not save tracking status.");
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