(function (global) {
  "use strict";

  const loaderScript = document.currentScript;
  const comicListsUrl = loaderScript
    ? loaderScript.dataset.comicListsUrl || ""
    : "";

  function onReady(callback) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", callback, { once: true });
      return;
    }

    callback();
  }

  function markDetailTables() {
    const page = document.querySelector("[data-collapsible-lists-page]");

    if (!page) {
      return false;
    }

    const tables = Array.from(
      page.querySelectorAll(".erc-data-card .erc-data-table"),
    );

    tables.forEach(function (table, index) {
      const target = table.tBodies.length ? table.tBodies[0] : null;
      const section =
        table.closest(".erc-volume-run-card") ||
        table.closest(".erc-data-card");
      const scrollContainer = table.closest(".table-responsive");

      if (!target || !section || !scrollContainer) {
        return;
      }

      section.dataset.comicSection =
        section.dataset.comicSection || `detail-list-${index + 1}`;
      section.dataset.comicSectionMode = "local";
      section.dataset.localInitialCount =
        section.dataset.localInitialCount || "10";
      section.dataset.localStepCount =
        section.dataset.localStepCount || "10";

      target.dataset.comicLoadTarget = "";
      scrollContainer.dataset.comicSectionScroll = "";
      scrollContainer.classList.add("erc-section-scroll");
      scrollContainer.style.maxHeight =
        scrollContainer.style.maxHeight || "26rem";
      scrollContainer.style.overflow = "auto";

      Array.from(target.rows).forEach(function (row) {
        if (row.querySelector("td[colspan]")) {
          row.dataset.emptyRow = "";
        }
      });
    });

    return tables.length > 0;
  }

  function initializeDetailLists() {
    const comicLists = global.EzyReadComicsComicLists;

    if (!comicLists || !markDetailTables()) {
      return;
    }

    comicLists.init();
  }

  function loadComicLists() {
    if (global.EzyReadComicsComicLists) {
      initializeDetailLists();
      return;
    }

    if (!comicListsUrl) {
      return;
    }

    const script = document.createElement("script");
    script.src = comicListsUrl;
    script.addEventListener("load", initializeDetailLists, { once: true });
    document.body.appendChild(script);
  }

  onReady(function () {
    if (!document.querySelector("[data-collapsible-lists-page]")) {
      return;
    }

    loadComicLists();
  });
})(window);
