document.addEventListener("DOMContentLoaded", function () {
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

  document.querySelectorAll("[data-row-url]").forEach(bindClickableRow);
});
