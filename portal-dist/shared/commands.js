/* commands.js — search/filtering, copy-to-clipboard, section toggle, export-to-markdown, keyboard wiring */

var sectionHeaders = Array.from(document.querySelectorAll(".section-header"));
var headerArray = Array.from(sectionHeaders);
var currentHeaderIndex = -1;

function getVisibleHeaders() {
  return headerArray.filter(function(header) {
    var card = header.closest(".section-card");
    return !card || !card.classList.contains("is-hidden");
  });
}

function setFocusedSectionCard(header) {
  document.querySelectorAll(".section-card.is-focused").forEach(function(card) {
    card.classList.remove("is-focused");
  });
  if (!header) return;
  var card = header.closest(".section-card");
  if (card) card.classList.add("is-focused");
}

function toggleSection(header, force) {
  var body = header.nextElementSibling;
  var shouldCollapse = force !== undefined ? force : !header.classList.contains("collapsed");
  header.classList.toggle("collapsed", shouldCollapse);
  body.classList.toggle("collapsed", shouldCollapse);
  header.setAttribute("aria-expanded", String(!shouldCollapse));
}

function setAllSections(collapsed) {
  headerArray.forEach(function(header) {
    toggleSection(header, collapsed);
  });
}

/* Default all sections to collapsed on load */
setAllSections(true);

function focusHeaderElement(header) {
  if (!header) return;
  currentHeaderIndex = headerArray.indexOf(header);
  header.focus();
  header.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function focusVisibleHeader(index) {
  var visibleHeaders = getVisibleHeaders();
  if (index >= 0 && index < visibleHeaders.length) {
    focusHeaderElement(visibleHeaders[index]);
  }
}

document.querySelectorAll(".value-block").forEach(function(el) {
  el.addEventListener("click", async function() {
    var text = el.dataset.copy || el.textContent || "";
    try {
      await navigator.clipboard.writeText(text);
      el.classList.add("copied");
      setTimeout(function() { el.classList.remove("copied"); }, 420);
    } catch (error) {
      var area = document.createElement("textarea");
      area.value = text;
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      document.body.removeChild(area);
      el.classList.add("copied");
      setTimeout(function() { el.classList.remove("copied"); }, 420);
    }
  });
});

sectionHeaders.forEach(function(header, index) {
  header.addEventListener("click", function() { toggleSection(header); });
  header.addEventListener("keydown", function(event) {
    if (event.key === " " || event.key === "Enter") {
      event.preventDefault();
      toggleSection(header);
    }
  });
  header.addEventListener("focus", function() {
    currentHeaderIndex = index;
  });
});

document.addEventListener("focusin", function(event) {
  var target = event.target;
  var header = target instanceof Element ? target.closest(".section-header") : null;
  setFocusedSectionCard(header);
});

var searchInput = document.getElementById("search");
var countEl = document.getElementById("search-count");
var clearBtn = document.getElementById("search-clear");

function applySearch() {
  if (!searchInput) return;
  var q = searchInput.value.trim().toLowerCase();
  var rows = Array.from(document.querySelectorAll(".command-row"));
  var visible = 0;
  rows.forEach(function(row) {
    var match = !q || (row.dataset.search || "").includes(q);
    row.classList.toggle("hidden", !match);
    if (match) {
      visible += 1;
      if (q) {
        var card = row.closest(".section-card");
        var header = card ? card.querySelector(".section-header") : null;
        if (header && header.classList.contains("collapsed")) {
          toggleSection(header, false);
        }
      }
    }
  });

  document.querySelectorAll(".section-card").forEach(function(card) {
    var totalVisible = card.querySelectorAll(".command-row:not(.hidden)").length;
    card.classList.toggle("is-hidden", q && totalVisible === 0);
    var badge = card.querySelector(".section-count");
    if (badge) {
      var total = card.querySelectorAll(".command-row").length;
      badge.textContent = q ? totalVisible + "/" + total : String(total);
    }
  });

  countEl.textContent = q ? visible + " match" + (visible === 1 ? "" : "es") : "";
  clearBtn.classList.toggle("visible", !!q);
}

if (searchInput) {
  searchInput.addEventListener("input", applySearch);
  clearBtn.addEventListener("click", function() {
    searchInput.value = "";
    applySearch();
    searchInput.focus();
  });
}

function exportToMarkdown() {
  var btn = document.getElementById("export-btn");
  var resetExportButton = function() {
    if (!btn) return;
    btn.textContent = btn.dataset.defaultLabel || "Export to Markdown";
    btn.classList.remove("is-confirmed", "is-error");
  };

  var flashExportButton = function(label, stateClass) {
    if (!btn) return;
    btn.dataset.defaultLabel = btn.dataset.defaultLabel || btn.textContent;
    btn.textContent = label;
    btn.classList.remove("is-confirmed", "is-error");
    void btn.offsetWidth;
    btn.classList.add(stateClass);
    if (btn._resetTimer) {
      window.clearTimeout(btn._resetTimer);
    }
    btn._resetTimer = window.setTimeout(resetExportButton, 1200);
  };

  var copyMarkdown = async function(value) {
    try {
      await navigator.clipboard.writeText(value);
      return true;
    } catch (error) {
      try {
        var area = document.createElement("textarea");
        area.value = value;
        document.body.appendChild(area);
        area.select();
        document.execCommand("copy");
        document.body.removeChild(area);
        return true;
      } catch (fallbackError) {
        return false;
      }
    }
  };

  var repoTitle = document.querySelector(".hero h1");
  var titleText = repoTitle ? repoTitle.textContent.trim() : "Command Reference";

  var sections = Array.from(document.querySelectorAll(".section-card"))
    .filter(function(card) { return !card.classList.contains("is-hidden"); })
    .map(function(card) {
      var header = card.querySelector(".section-header");
      if (header && header.classList.contains("collapsed")) {
        return null;
      }
      var title = (card.querySelector(".section-title") || {}).textContent || "";
      title = title.trim();
      var rows = Array.from(card.querySelectorAll(".command-row"))
        .filter(function(row) { return !row.classList.contains("hidden"); })
        .map(function(row) {
          var task = (row.querySelector(".task-text") || {}).textContent || "";
          task = task.trim();
          var valueBlock = row.querySelector(".value-block");
          var command = valueBlock ? (valueBlock.dataset.copy || "").trim() : "";
          var desc = (row.querySelector(".desc-text") || {}).textContent || "";
          desc = desc.trim();
          if (!(task || command || desc)) {
            return null;
          }
          return {
            task: task.replace(/\|/g, "\\|"),
            command: command.replace(/\n/g, "<br>").replace(/\|/g, "\\|"),
            desc: desc.replace(/\n/g, "<br>").replace(/\|/g, "\\|"),
          };
        })
        .filter(Boolean);
      if (!rows.length) {
        return null;
      }
      return { title: title, rows: rows };
    })
    .filter(Boolean);

  if (!sections.length) {
    flashExportButton("No visible rows", "is-error");
    return;
  }

  var md = "# " + titleText + " - Command Reference\n\n";
  sections.forEach(function(card) {
    md += "## " + card.title + "\n\n";
    md += "| Task | Command / Snippet | Description |\n";
    md += "| --- | --- | --- |\n";
    card.rows.forEach(function(row) {
      md += "| " + row.task + " | `" + row.command + "` | " + row.desc + " |\n";
    });
    md += "\n";
  });
  copyMarkdown(md).then(function(success) {
    flashExportButton(success ? "\u2713 Copied Markdown" : "Copy failed", success ? "is-confirmed" : "is-error");
  });
}

var exportBtn = document.getElementById("export-btn");
if (exportBtn) {
  exportBtn.addEventListener("click", exportToMarkdown);
}

document.addEventListener("keydown", function(event) {
  var inSearch = searchInput && document.activeElement === searchInput;
  var isExportShortcut =
    (event.metaKey || event.ctrlKey) &&
    event.shiftKey &&
    !event.altKey &&
    event.key.toLowerCase() === "e";

  if (isExportShortcut) {
    event.preventDefault();
    exportToMarkdown();
    return;
  }

  if (event.key === "\\") {
    event.preventDefault();
    var current = getCurrentTheme();
    var next = THEME_ORDER[(THEME_ORDER.indexOf(current) + 1) % THEME_ORDER.length];
    applyTheme(next);
    return;
  }

  if (event.key === "Escape") {
    event.preventDefault();
    setAllSections(true);
    if (inSearch) {
      searchInput.value = "";
      applySearch();
      searchInput.blur();
    }
    return;
  }

  if (event.key === "Tab" && searchInput) {
    event.preventDefault();
    if (inSearch) {
      searchInput.blur();
    } else {
      searchInput.focus();
      searchInput.select();
    }
    return;
  }

  if (inSearch) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      focusVisibleHeader(0);
    }
    return;
  }

  if (!event.metaKey && !event.ctrlKey && !event.altKey && event.key.toLowerCase() === "a") {
    event.preventDefault();
    setAllSections(false);
    return;
  }

  var focused = document.activeElement;
  if (focused && focused.classList.contains("section-header")) {
    currentHeaderIndex = headerArray.indexOf(focused);
  }
  var visibleHeaders = getVisibleHeaders();
  var visibleIndex = focused && focused.classList.contains("section-header")
    ? visibleHeaders.indexOf(focused)
    : -1;

  switch (event.key) {
    case "ArrowDown":
      event.preventDefault();
      if (visibleHeaders.length) {
        focusHeaderElement(
          visibleHeaders[
            visibleIndex < 0 ? 0 : Math.min(visibleIndex + 1, visibleHeaders.length - 1)
          ]
        );
      }
      break;
    case "ArrowUp":
      event.preventDefault();
      if (visibleIndex <= 0) {
        if (searchInput) {
          searchInput.focus();
          searchInput.select();
        } else if (visibleHeaders.length) {
          focusHeaderElement(visibleHeaders[0]);
        }
      } else {
        focusHeaderElement(visibleHeaders[visibleIndex - 1]);
      }
      break;
    case "ArrowRight":
      if (focused && focused.classList.contains("section-header") && focused.classList.contains("collapsed")) {
        event.preventDefault();
        toggleSection(focused, false);
      }
      break;
    case "ArrowLeft":
      if (focused && focused.classList.contains("section-header") && !focused.classList.contains("collapsed")) {
        event.preventDefault();
        toggleSection(focused, true);
      }
      break;
    case "Enter":
    case " ":
      if (focused && focused.classList.contains("section-header")) {
        event.preventDefault();
        toggleSection(focused);
      }
      break;
  }
});
