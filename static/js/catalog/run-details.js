document.addEventListener("DOMContentLoaded", function () {
    const unfollowStatusValue = "__unfollow__";
    const statusModalElement = document.getElementById("tracking-status-modal");
    const statusModalTitle = document.getElementById("tracking-status-modal-title");
    const statusModalCopy = document.getElementById("tracking-status-modal-copy");
    const statusModalSelect = document.getElementById("tracking-status-select");
    const statusModalConfirm = document.querySelector("[data-status-modal-confirm]");
    const statusModal = statusModalElement ? bootstrap.Modal.getOrCreateInstance(statusModalElement) : null;

    let statusModalResolve = null;

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
        };

        return labels[itemType] || "item";
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

    document.querySelectorAll("[data-auto-submit]").forEach(function (select) {
        select.addEventListener("change", function () {
            select.form.requestSubmit();
        });
    });

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
                return;
            }

            if (select.value === unfollowStatusValue) {
                const confirmed = window.confirm("Are you sure you want to unfollow this run?");

                if (!confirmed) {
                    event.preventDefault();
                    select.value = currentStatus;
                    return;
                }

                if (trackedIssues > 0) {
                    const removeIssues = window.confirm(
                        `Also unfollow the ${trackedIssues} saved ${issueLabel(trackedIssues)} from this run?`
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
            const totalIssues = getCount(form, "runIssueCount");
            const trackedIssues = getCount(form, "trackedIssueCount");

            if (!statusInput || !applyToIssuesInput) {
                return;
            }

            const selectedStatus = await openStatusModal("run");

            if (!selectedStatus) {
                return;
            }

            statusInput.value = selectedStatus;
            applyToIssuesInput.value = "";

            const message = applyStatusMessage(selectedStatus, totalIssues, trackedIssues);

            if (message && window.confirm(message)) {
                applyToIssuesInput.value = "1";
            }

            HTMLFormElement.prototype.submit.call(form);
        });
    });

    document.querySelectorAll("[data-issue-follow-form]").forEach(function (form) {
        form.addEventListener("submit", async function (event) {
            event.preventDefault();

            const statusInput = form.querySelector("input[name='status']");

            if (!statusInput) {
                return;
            }

            const selectedStatus = await openStatusModal("issue");

            if (!selectedStatus) {
                return;
            }

            statusInput.value = selectedStatus;
            HTMLFormElement.prototype.submit.call(form);
        });
    });

    document.querySelectorAll("[data-issue-status-form]").forEach(function (form) {
        form.addEventListener("submit", function (event) {
            const select = form.querySelector("select[name='status']");
            const currentStatus = form.dataset.currentStatus;

            if (!select || select.value !== unfollowStatusValue) {
                return;
            }

            const confirmed = window.confirm("Are you sure you want to unfollow this issue?");

            if (!confirmed) {
                event.preventDefault();
                select.value = currentStatus;
            }
        });
    });
});