document.addEventListener("DOMContentLoaded", function () {
    const unfollowStatusValue = "__unfollow__";
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
        const labels = {
            run: "run",
            issue: "issue",
            volume: "volume",
            one_shot: "one-shot",
        };

        return `Are you sure you want to unfollow this ${labels[itemType] || "item"}?`;
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

    function clearElement(element) {
        while (element.firstChild) {
            element.removeChild(element.firstChild);
        }
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

        if (!statusModalElement) {
            return null;
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

        if (!controls) {
            return;
        }

        controls.error.classList.add("d-none");
        controls.error.textContent = "";
    }

    function showStatusModalError(message) {
        const controls = ensureStatusModalControls();

        if (!controls) {
            return;
        }

        controls.error.textContent = message;
        controls.error.classList.remove("d-none");
    }

    function renderIndividualIssueStatusRows(issues, choices, defaultStatus) {
        const controls = ensureStatusModalControls();

        if (!controls) {
            return;
        }

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

        if (!controls || !statusModalSelect) {
            return;
        }

        const issues = options && options.issues ? options.issues : [];
        const issueChoices = options && options.issue_status_choices
            ? options.issue_status_choices
            : optionObjectsFromSelect(statusModalSelect);
        const isRun = statusModalContext && statusModalContext.itemType === "run";

        controls.runOptions.classList.toggle("d-none", !isRun);
        controls.followIssuesInput.checked = false;
        controls.followIssuesInput.disabled = false;
        controls.followIssuesSettings.classList.add("d-none");
        controls.individualInput.checked = false;
        controls.sharedIssueStatusGroup.classList.remove("d-none");
        controls.individualIssueStatusGroup.classList.add("d-none");

        populateSelect(controls.sharedIssueStatusSelect, issueChoices, statusModalSelect.value);
        renderIndividualIssueStatusRows(issues, issueChoices, statusModalSelect.value);

        if (isRun && !issues.length) {
            controls.followIssuesInput.disabled = true;
        }
    }

    function buildStatusModalResult() {
        const controls = ensureStatusModalControls();

        if (!statusModalContext || statusModalContext.itemType !== "run" || !controls) {
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

    function bindAutoSubmitSelect(select) {
        if (select.dataset.autoSubmitBound === "1") {
            return;
        }

        select.dataset.autoSubmitBound = "1";

        select.addEventListener("change", function () {
            select.form.requestSubmit();
        });
    }

    document.querySelectorAll("[data-auto-submit]").forEach(bindAutoSubmitSelect);

    document.querySelectorAll(".clickable-row").forEach(function (row) {
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
    });

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

    function removeGeneratedIssueStatusInputs(form) {
        form.querySelectorAll("[data-generated-run-follow-input]").forEach(function (input) {
            input.remove();
        });
    }

    function addHiddenInput(form, name, value) {
        const input = document.createElement("input");

        input.type = "hidden";
        input.name = name;
        input.value = value;
        input.dataset.generatedRunFollowInput = "";

        form.appendChild(input);
    }

    function applyRunFollowModalResultToForm(form, selectedStatus) {
        const statusInput = form.querySelector("input[name='status']");
        const applyToIssuesInput = form.querySelector("input[name='apply_to_issues']");

        removeGeneratedIssueStatusInputs(form);

        statusInput.value = selectedStatus.status;
        applyToIssuesInput.value = selectedStatus.followIssues ? "1" : "";

        if (!selectedStatus.followIssues) {
            return;
        }

        addHiddenInput(form, "issue_status_mode", selectedStatus.issueStatusMode);

        if (selectedStatus.issueStatusMode === "individual") {
            selectedStatus.individualIssueStatuses.forEach(function (issueStatus) {
                addHiddenInput(form, `issue_status_${issueStatus.issueId}`, issueStatus.status);
            });

            return;
        }

        addHiddenInput(form, "issue_status", selectedStatus.issueStatus || selectedStatus.status);
    }

    document.querySelectorAll("[data-run-status-form]").forEach(function (form) {
        form.addEventListener("submit", function (event) {
            const select = form.querySelector("select[name='status']");
            const applyToIssuesInput = form.querySelector("input[name='apply_to_issues']");
            const removeIssuesInput = form.querySelector("input[name='remove_issues']");
            const currentStatus = form.dataset.currentStatus;
            const totalIssues = getCount(form, "runIssueCount");
            const trackedIssues = getCount(form, "trackedIssueCount");

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
                const confirmed = window.confirm(unfollowPrompt("run"));

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

            const message = applyStatusMessage(select.value, totalIssues, trackedIssues);

            if (message && window.confirm(message)) {
                applyToIssuesInput.value = "1";
            }
        });
    });

    document.querySelectorAll("[data-run-follow-form]").forEach(function (form) {
        form.addEventListener("submit", async function (event) {
            event.preventDefault();

            const statusInput = form.querySelector("input[name='status']");
            const applyToIssuesInput = form.querySelector("input[name='apply_to_issues']");

            if (!statusInput || !applyToIssuesInput) {
                return;
            }

            let followOptions = {};

            try {
                followOptions = await fetchRunFollowOptions(form);
            } catch (error) {
                followOptions = {
                    error: error.message || "Could not load the issues for this run.",
                    issues: [],
                };
            }

            const selectedStatus = await openStatusModal("run", followOptions || {});

            if (!selectedStatus) {
                return;
            }

            applyRunFollowModalResultToForm(form, selectedStatus);
            HTMLFormElement.prototype.submit.call(form);
        });
    });

    document.querySelectorAll("[data-simple-follow-form]").forEach(function (form) {
        form.addEventListener("submit", async function (event) {
            event.preventDefault();

            const statusInput = form.querySelector("input[name='status']");
            const itemType = form.dataset.itemType || "item";

            if (!statusInput) {
                return;
            }

            const selectedStatus = await openStatusModal(itemType, {});

            if (!selectedStatus) {
                return;
            }

            statusInput.value = selectedStatus.status;
            HTMLFormElement.prototype.submit.call(form);
        });
    });

    document.querySelectorAll("[data-simple-status-form]").forEach(function (form) {
        form.addEventListener("submit", function (event) {
            const select = form.querySelector("select[name='status']");
            const currentStatus = form.dataset.currentStatus;
            const itemType = form.dataset.itemType || "item";

            if (!select) {
                return;
            }

            if (select.value === currentStatus) {
                event.preventDefault();
                return;
            }

            if (select.value !== unfollowStatusValue) {
                return;
            }

            const confirmed = window.confirm(unfollowPrompt(itemType));

            if (!confirmed) {
                event.preventDefault();
                select.value = currentStatus;
            }
        });
    });
});
