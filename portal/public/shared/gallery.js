/* gallery.js — Mermaid setup/rendering, color normalization, diagram interaction, keyboard wiring */
import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";

var diagramHeaders = Array.from(document.querySelectorAll(".diagram-header"));
var currentHeaderIndex = -1;
var renderRun = 0;

function getMermaidTones() {
  return {
    neutral: {
      fill: cssVar("--mermaid-neutral-fill"),
      border: cssVar("--mermaid-neutral-border"),
      text: cssVar("--mermaid-neutral-text"),
    },
    blue: {
      fill: cssVar("--mermaid-blue-fill"),
      border: cssVar("--mermaid-blue-border"),
      text: cssVar("--mermaid-blue-text"),
    },
    green: {
      fill: cssVar("--mermaid-green-fill"),
      border: cssVar("--mermaid-green-border"),
      text: cssVar("--mermaid-green-text"),
    },
    amber: {
      fill: cssVar("--mermaid-amber-fill"),
      border: cssVar("--mermaid-amber-border"),
      text: cssVar("--mermaid-amber-text"),
    },
    red: {
      fill: cssVar("--mermaid-red-fill"),
      border: cssVar("--mermaid-red-border"),
      text: cssVar("--mermaid-red-text"),
    },
    violet: {
      fill: cssVar("--mermaid-violet-fill"),
      border: cssVar("--mermaid-violet-border"),
      text: cssVar("--mermaid-violet-text"),
    },
  };
}

function parseColorToken(token) {
  var value = token.trim().toLowerCase();
  if (!value) {
    return null;
  }
  var match = value.match(/^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i);
  if (match) {
    var hex = match[1];
    if (hex.length === 3) {
      hex = hex.split("").map(function(part) { return part + part; }).join("");
    }
    if (hex.length === 8) {
      hex = hex.slice(0, 6);
    }
    return {
      r: parseInt(hex.slice(0, 2), 16),
      g: parseInt(hex.slice(2, 4), 16),
      b: parseInt(hex.slice(4, 6), 16),
    };
  }
  match = value.match(/^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)/i);
  if (match) {
    return {
      r: Number(match[1]),
      g: Number(match[2]),
      b: Number(match[3]),
    };
  }
  return null;
}

function classifyColorToken(token) {
  var parsed = parseColorToken(token);
  if (!parsed) {
    return "neutral";
  }
  var r = parsed.r, g = parsed.g, b = parsed.b;
  var max = Math.max(r, g, b);
  var min = Math.min(r, g, b);
  var delta = max - min;
  if (delta < 18) {
    return "neutral";
  }
  var saturation = max === 0 ? 0 : delta / max;
  if (saturation < 0.18) {
    return "neutral";
  }
  var hue = 0;
  if (delta !== 0) {
    if (max === r) {
      hue = ((g - b) / delta) % 6;
    } else if (max === g) {
      hue = (b - r) / delta + 2;
    } else {
      hue = (r - g) / delta + 4;
    }
    hue *= 60;
    if (hue < 0) {
      hue += 360;
    }
  }
  if (hue < 18 || hue >= 338) {
    return "red";
  }
  if (hue < 72) {
    return "amber";
  }
  if (hue < 170) {
    return "green";
  }
  if (hue < 255) {
    return "blue";
  }
  return "violet";
}

function normalizeStyleProperties(propertyText) {
  var tones = getMermaidTones();
  var props = propertyText
    .split(",")
    .map(function(part) { return part.trim(); })
    .filter(Boolean);
  if (!props.length) {
    return propertyText;
  }
  return props
    .map(function(entry) {
      var parts = entry.split(/:(.+)/);
      if (parts.length < 3) {
        return entry;
      }
      var key = parts[0].trim();
      var value = parts[1].trim();
      var tone = tones[classifyColorToken(value)] || tones.neutral;
      if (/^fill$/i.test(key) || /bkg/i.test(key)) {
        return key + ":" + tone.fill;
      }
      if (/^stroke$/i.test(key) || /border/i.test(key) || /line/i.test(key)) {
        return key + ":" + tone.border;
      }
      if (/color/i.test(key) || /text/i.test(key)) {
        return key + ":" + tone.text;
      }
      return entry;
    })
    .join(",");
}

function formatMermaidRectColor(token) {
  var parsed = parseColorToken(token);
  if (!parsed) {
    return token;
  }
  return "rgb(" + Math.round(parsed.r) + ", " + Math.round(parsed.g) + ", " + Math.round(parsed.b) + ")";
}

function normalizeMermaidSource(raw) {
  var tones = getMermaidTones();
  var next = raw.replace(/%%\{init:[\s\S]*?%%\s*/g, "");
  next = next.replace(/^(\s*rect\s+)(#[0-9a-fA-F]{3,8}|rgba?\([^)]+\))(.*)$/gm, function(_match, prefix, color, suffix) {
    var tone = tones[classifyColorToken(color)] || tones.neutral;
    return prefix + formatMermaidRectColor(tone.fill) + suffix;
  });
  next = next.replace(/^(\s*style\s+\S+\s+)(.+)$/gm, function(_match, prefix, properties) {
    return prefix + normalizeStyleProperties(properties);
  });
  next = next.replace(/^(\s*classDef\s+[^\s]+\s+)(.+)$/gm, function(_match, prefix, properties) {
    return prefix + normalizeStyleProperties(properties);
  });
  next = next.replace(/^(\s*linkStyle\s+.+?\s+)(.+)$/gm, function(_match, prefix, properties) {
    return prefix + normalizeStyleProperties(properties);
  });
  return next;
}

function getMermaidThemeCss() {
  var text = cssVar("--text");
  var panel = cssVar("--bg-panel");
  var border = cssVar("--border-strong");
  var line = cssVar("--mermaid-line");
  var lineMuted = cssVar("--mermaid-line-muted");
  var labelFill = cssVar("--mermaid-label-fill");
  var labelText = cssVar("--mermaid-label-text");
  var accentSoft = cssVar("--accent-soft");
  return "\n" +
    "    svg {\n" +
    "      color: " + text + " !important;\n" +
    "    }\n" +
    "    text,\n" +
    "    tspan,\n" +
    "    .nodeLabel,\n" +
    "    .nodeLabel p,\n" +
    "    .nodeLabel div,\n" +
    "    .nodeLabel span,\n" +
    "    .messageText,\n" +
    "    .messageText tspan,\n" +
    "    .loopText,\n" +
    "    .loopText tspan,\n" +
    "    .sectionTitle text,\n" +
    "    .taskText,\n" +
    "    .taskTextOutsideLeft,\n" +
    "    .taskTextOutsideRight,\n" +
    "    .actor text,\n" +
    "    .actor tspan,\n" +
    "    .classTitle,\n" +
    "    .classTitle tspan,\n" +
    "    .classText,\n" +
    "    .entityLabel,\n" +
    "    .cluster-label text {\n" +
    "      fill: " + text + " !important;\n" +
    "      color: " + text + " !important;\n" +
    "      font-family: \"Geist Mono UltraLight\", ui-monospace, monospace !important;\n" +
    "      font-weight: 200 !important;\n" +
    "    }\n" +
    "    .noteText,\n" +
    "    .noteText tspan,\n" +
    "    .label text,\n" +
    "    .label foreignObject,\n" +
    "    .label foreignObject div,\n" +
    "    .label foreignObject span,\n" +
    "    .edgeLabel text,\n" +
    "    .edgeLabel foreignObject,\n" +
    "    .edgeLabel span,\n" +
    "    .edgeLabel p,\n" +
    "    .labelText,\n" +
    "    .boxText {\n" +
    "      fill: " + labelText + " !important;\n" +
    "      color: " + labelText + " !important;\n" +
    "      font-family: \"Geist Mono UltraLight\", ui-monospace, monospace !important;\n" +
    "      font-weight: 200 !important;\n" +
    "    }\n" +
    "    .node rect,\n" +
    "    .node circle,\n" +
    "    .node ellipse,\n" +
    "    .node polygon,\n" +
    "    .node path,\n" +
    "    .classBox,\n" +
    "    .entityBox {\n" +
    "      stroke-width: 1.35px !important;\n" +
    "    }\n" +
    "    .cluster rect,\n" +
    "    .cluster polygon,\n" +
    "    .labelBox,\n" +
    "    .note,\n" +
    "    .actor rect,\n" +
    "    .activation0,\n" +
    "    .activation1,\n" +
    "    .activation2,\n" +
    "    .activation3,\n" +
    "    .activation4 {\n" +
    "      fill: " + panel + " !important;\n" +
    "      stroke: " + border + " !important;\n" +
    "    }\n" +
    "    .edgeLabel rect,\n" +
    "    .labelBkg,\n" +
    "    .label-container rect {\n" +
    "      fill: " + labelFill + " !important;\n" +
    "      stroke: " + border + " !important;\n" +
    "      opacity: 1 !important;\n" +
    "    }\n" +
    "    .messageLine0,\n" +
    "    .messageLine1,\n" +
    "    .relation,\n" +
    "    .transition,\n" +
    "    .flowchart-link,\n" +
    "    .actor-line,\n" +
    "    .loopLine,\n" +
    "    .separator {\n" +
    "      stroke: " + line + " !important;\n" +
    "      stroke-width: 2px !important;\n" +
    "    }\n" +
    "    .messageLine0,\n" +
    "    .messageLine1,\n" +
    "    .relation,\n" +
    "    .transition {\n" +
    "      fill: none !important;\n" +
    "    }\n" +
    "    .marker,\n" +
    "    .marker path,\n" +
    "    .arrowheadPath,\n" +
    "    .arrowMarkerPath {\n" +
    "      fill: " + line + " !important;\n" +
    "      stroke: " + line + " !important;\n" +
    "    }\n" +
    "    .actor-line,\n" +
    "    .loopLine {\n" +
    "      stroke: " + lineMuted + " !important;\n" +
    "    }\n" +
    "    .today {\n" +
    "      fill: " + accentSoft + " !important;\n" +
    "      stroke: " + line + " !important;\n" +
    "    }\n" +
    "  ";
}

function getMermaidConfig() {
  var theme = getCurrentTheme();
  return {
    startOnLoad: false,
    securityLevel: "loose",
    theme: "base",
    themeCSS: getMermaidThemeCss(),
    themeVariables: {
      darkMode: theme !== "light",
      fontFamily: '"Geist Mono UltraLight", ui-monospace, monospace',
      primaryColor: cssVar("--bg-panel"),
      primaryTextColor: cssVar("--text"),
      primaryBorderColor: cssVar("--border-strong"),
      lineColor: cssVar("--mermaid-line"),
      secondaryColor: cssVar("--bg-panel-strong"),
      tertiaryColor: cssVar("--bg-panel-hover"),
      background: cssVar("--bg-deep"),
      mainBkg: cssVar("--bg-panel"),
      secondBkg: cssVar("--bg-panel-strong"),
      tertiaryBkg: cssVar("--bg-panel-hover"),
      nodeBorder: cssVar("--border-strong"),
      clusterBkg: cssVar("--bg-panel"),
      clusterBorder: cssVar("--border-strong"),
      titleColor: cssVar("--text"),
      textColor: cssVar("--text"),
      edgeLabelBackground: cssVar("--bg-deep"),
      noteBkgColor: cssVar("--bg-panel"),
      noteBorderColor: cssVar("--border-strong"),
      actorBkg: cssVar("--bg-panel"),
      actorBorder: cssVar("--border-strong"),
      actorTextColor: cssVar("--text"),
      actorLineColor: cssVar("--mermaid-line-muted"),
      activationBkgColor: cssVar("--bg-panel-hover"),
      activationBorderColor: cssVar("--border-strong"),
      signalColor: cssVar("--mermaid-line"),
      signalTextColor: cssVar("--mermaid-label-text"),
      labelBoxBkgColor: cssVar("--mermaid-label-fill"),
      labelBoxBorderColor: cssVar("--border-strong"),
      labelTextColor: cssVar("--mermaid-label-text"),
      loopTextColor: cssVar("--mermaid-label-text"),
      noteTextColor: cssVar("--mermaid-label-text"),
      sequenceNumberColor: cssVar("--mermaid-label-text"),
    },
    flowchart: {
      useMaxWidth: true,
      htmlLabels: true,
      curve: "basis",
      nodeSpacing: 70,
      rankSpacing: 90,
      padding: 24,
    },
    sequence: {
      useMaxWidth: true,
      mirrorActors: false,
      diagramMarginX: 40,
      diagramMarginY: 20,
      boxMargin: 10,
      boxTextMargin: 8,
      noteMargin: 10,
      messageMargin: 35,
    },
    stateDiagram: { useMaxWidth: true },
    classDiagram: { useMaxWidth: true },
    er: { useMaxWidth: true },
    gitGraph: { useMaxWidth: true },
  };
}

function escapeHtml(value) {
  return value.replace(/[&<>"]/g, function(char) { return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[char]; });
}

async function renderAllDiagrams() {
  var cards = Array.from(document.querySelectorAll(".diagram-card[data-diagram-id]"));
  if (!cards.length) {
    return;
  }
  var runId = ++renderRun;
  mermaid.initialize(getMermaidConfig());
  for (var i = 0; i < cards.length; i++) {
    var card = cards[i];
    var sourceNode = card.querySelector(".mermaid-source");
    var host = card.querySelector(".diagram-canvas");
    var raw = "";
    if (sourceNode) {
      try {
        raw = JSON.parse(sourceNode.textContent).trim();
      } catch (_error) {
        raw = sourceNode.textContent.trim();
      }
    }
    if (!raw || !host) {
      continue;
    }
    try {
      var normalized = normalizeMermaidSource(raw);
      var result = await mermaid.render("gallery-mermaid-" + runId + "-" + i, normalized);
      if (runId !== renderRun) {
        return;
      }
      host.innerHTML = result.svg;
    } catch (error) {
      host.innerHTML = '<pre class="diagram-error">' + escapeHtml(String(error)) + "</pre>";
    }
  }
}

function setFocusedCard(header) {
  document.querySelectorAll(".diagram-card.is-focused").forEach(function(card) {
    card.classList.remove("is-focused");
  });
  if (!header) {
    return;
  }
  var card = header.closest(".diagram-card");
  if (card) card.classList.add("is-focused");
}

function toggleDiagram(header, force) {
  var card = header.closest(".diagram-card");
  var content = card ? card.querySelector(".diagram-content") : null;
  if (!card || !content) {
    return;
  }
  var shouldCollapse = force !== undefined ? force : !card.classList.contains("collapsed");
  card.classList.toggle("collapsed", shouldCollapse);
  header.classList.toggle("collapsed", shouldCollapse);
  content.classList.toggle("collapsed", shouldCollapse);
  header.setAttribute("aria-expanded", String(!shouldCollapse));
}

function setAllDiagrams(collapsed) {
  diagramHeaders.forEach(function(header) { toggleDiagram(header, collapsed); });
}

/* Default all diagrams to collapsed on load */
setAllDiagrams(true);

function focusHeader(index) {
  if (!diagramHeaders.length) {
    return;
  }
  currentHeaderIndex = Math.max(0, Math.min(index, diagramHeaders.length - 1));
  var header = diagramHeaders[currentHeaderIndex];
  header.focus();
  header.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

diagramHeaders.forEach(function(header, index) {
  header.addEventListener("click", function() {
    toggleDiagram(header);
    currentHeaderIndex = index;
  });
  header.addEventListener("focus", function() {
    currentHeaderIndex = index;
  });
});

document.addEventListener("focusin", function(event) {
  var target = event.target;
  var header = target instanceof Element ? target.closest(".diagram-header") : null;
  setFocusedCard(header);
});

document.querySelectorAll(".nav-chip").forEach(function(link) {
  link.addEventListener("click", function(event) {
    event.preventDefault();
    var targetId = link.getAttribute("data-target");
    var card = targetId ? document.getElementById(targetId) : null;
    var header = card ? card.querySelector(".diagram-header") : null;
    if (!card || !header) {
      return;
    }
    toggleDiagram(header, false);
    header.scrollIntoView({ behavior: "smooth", block: "start" });
    header.focus();
  });
});

document.addEventListener("keydown", async function(event) {
  var isTextField = event.target instanceof HTMLElement && (
    event.target.tagName === "INPUT" ||
    event.target.tagName === "TEXTAREA" ||
    event.target.isContentEditable
  );

  if (!isTextField && !event.metaKey && !event.ctrlKey && !event.altKey && event.code === "Backslash") {
    event.preventDefault();
    var current = getCurrentTheme();
    var next = THEME_ORDER[(THEME_ORDER.indexOf(current) + 1) % THEME_ORDER.length];
    applyTheme(next);
    await renderAllDiagrams();
    return;
  }

  if (!isTextField && event.key === "Escape") {
    event.preventDefault();
    setAllDiagrams(true);
    return;
  }

  if (!isTextField && !event.metaKey && !event.ctrlKey && !event.altKey && event.key.toLowerCase() === "a") {
    event.preventDefault();
    setAllDiagrams(false);
    return;
  }

  var focused = document.activeElement;
  if (!(focused instanceof HTMLElement) || !focused.classList.contains("diagram-header")) {
    if (event.key === "ArrowDown" && diagramHeaders.length) {
      event.preventDefault();
      focusHeader(0);
    }
    return;
  }

  var index = diagramHeaders.indexOf(focused);
  if (index >= 0) {
    currentHeaderIndex = index;
  }

  switch (event.key) {
    case "ArrowDown":
      event.preventDefault();
      focusHeader(Math.min(currentHeaderIndex + 1, diagramHeaders.length - 1));
      break;
    case "ArrowUp":
      event.preventDefault();
      focusHeader(Math.max(currentHeaderIndex - 1, 0));
      break;
    case "ArrowRight":
      event.preventDefault();
      toggleDiagram(focused, false);
      break;
    case "ArrowLeft":
      event.preventDefault();
      toggleDiagram(focused, true);
      break;
    case "Enter":
    case " ":
      event.preventDefault();
      toggleDiagram(focused);
      break;
    case "Home":
      event.preventDefault();
      focusHeader(0);
      break;
    case "End":
      event.preventDefault();
      focusHeader(diagramHeaders.length - 1);
      break;
  }
});

renderAllDiagrams();
