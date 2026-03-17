/**
 * explainers-docs.js — Shared behavior for explainers doc pages
 * ES Module. Import selectively or use the default init().
 *
 * Usage:
 *   import init from '/shared/explainers-docs.js';
 *   init();
 *
 *   // Or selectively:
 *   import { initCollapsible, initMermaid } from '/shared/explainers-docs.js';
 */

// ---------------------------------------------------------------------------
// Collapsible sections
// ---------------------------------------------------------------------------

/**
 * Initialize collapsible sections for both diagram cards and command sections.
 * Uses JS-driven scrollHeight (not max-height hack) for smooth animation.
 */
export function initCollapsible(options = {}) {
  // Find all collapsible headers: diagram card headers + command section headers
  function getHeaders() {
    return [
      ...document.querySelectorAll('.ex-diagram-card__header'),
      ...document.querySelectorAll('.ex-cmd-section-header'),
    ];
  }

  function getBody(header) {
    if (header.classList.contains('ex-diagram-card__header')) {
      return header.nextElementSibling; // .ex-diagram-card__body
    }
    // For table rows: find rows with matching data-section
    const section = header.dataset.section;
    if (section) {
      return { _isSectionRows: true, section };
    }
    return null;
  }

  function getSectionRows(section) {
    return [...document.querySelectorAll(`.ex-cmd-section-row[data-section="${section}"]`)]
      .map(row => row); // returns tr elements
  }

  function expand(header) {
    const body = getBody(header);
    if (!body) return;
    header.setAttribute('aria-expanded', 'true');

    if (body._isSectionRows) {
      getSectionRows(body.section).forEach(row => row.style.display = '');
      return;
    }

    // Height animation for div bodies
    body.style.height = '0';
    body.style.overflow = 'hidden';
    // Force reflow
    body.offsetHeight;
    const targetH = body.scrollHeight;
    body.style.height = targetH + 'px';
    body.addEventListener('transitionend', function onEnd() {
      body.style.height = 'auto';
      body.style.overflow = '';
      body.removeEventListener('transitionend', onEnd);
    }, { once: true });
  }

  function collapse(header) {
    const body = getBody(header);
    if (!body) return;
    header.setAttribute('aria-expanded', 'false');

    if (body._isSectionRows) {
      getSectionRows(body.section).forEach(row => row.style.display = 'none');
      return;
    }

    // Snapshot current height, then animate to 0
    const currentH = body.scrollHeight;
    body.style.height = currentH + 'px';
    body.style.overflow = 'hidden';
    // rAF to ensure browser picks up the starting height
    requestAnimationFrame(() => {
      body.style.height = '0';
    });
  }

  function toggle(header) {
    const expanded = header.getAttribute('aria-expanded') !== 'false';
    if (expanded) collapse(header); else expand(header);
  }

  // Set initial state: all expanded (aria-expanded="true"), bodies at auto height
  getHeaders().forEach(header => {
    const isExpanded = header.getAttribute('aria-expanded') !== 'false';
    const body = getBody(header);
    if (!body) return;

    if (body._isSectionRows) {
      if (!isExpanded) getSectionRows(body.section).forEach(r => r.style.display = 'none');
      return;
    }

    if (isExpanded) {
      body.style.height = 'auto';
      body.style.overflow = '';
    } else {
      body.style.height = '0';
      body.style.overflow = 'hidden';
    }
  });

  // Click handlers
  getHeaders().forEach(header => {
    header.addEventListener('click', () => toggle(header));
  });

  // Keyboard navigation on document
  document.addEventListener('keydown', (e) => {
    const tag = document.activeElement.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA') return;

    const headers = getHeaders();
    const focused = document.activeElement;
    const idx = headers.indexOf(focused);

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        if (idx >= 0 && idx < headers.length - 1) {
          headers[idx + 1].focus();
          headers[idx + 1].scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        } else if (idx === -1 && headers.length > 0) {
          headers[0].focus();
          headers[0].scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
        break;
      case 'ArrowUp':
        e.preventDefault();
        if (idx > 0) {
          headers[idx - 1].focus();
          headers[idx - 1].scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        } else if (idx === -1 && headers.length > 0) {
          headers[headers.length - 1].focus();
          headers[headers.length - 1].scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
        break;
      case 'ArrowLeft':
        if (idx >= 0) {
          e.preventDefault();
          collapse(focused);
          focused.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
        break;
      case 'ArrowRight':
        if (idx >= 0) {
          e.preventDefault();
          expand(focused);
          focused.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
        break;
      case 'a':
      case 'A':
        e.preventDefault();
        getHeaders().forEach(expand);
        break;
      case 'Escape':
        e.preventDefault();
        getHeaders().forEach(collapse);
        break;
    }
  });
}

// ---------------------------------------------------------------------------
// Copy to clipboard
// ---------------------------------------------------------------------------

/**
 * Initialize click-to-copy on .ex-cmd-pill elements.
 * Strips emoji before copying. Flashes .copied class for 300ms.
 */
export function initCopyToClipboard(options = {}) {
  const EMOJI_RE = /[\u{1F300}-\u{1F9FF}\u{2600}-\u{27BF}]/gu;

  document.querySelectorAll('.ex-cmd-pill').forEach(pill => {
    pill.addEventListener('click', async () => {
      const raw = pill.dataset.copy || pill.innerText;
      const text = raw.replace(EMOJI_RE, '').trim();

      try {
        await navigator.clipboard.writeText(text);
      } catch {
        // execCommand fallback
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
      }

      pill.classList.add('copied');
      setTimeout(() => pill.classList.remove('copied'), 300);
    });
  });
}

// ---------------------------------------------------------------------------
// Mermaid rendering
// ---------------------------------------------------------------------------

/**
 * Initialize Mermaid diagram rendering using ESM import + IntersectionObserver.
 * Only renders diagrams when their card is visible AND expanded.
 */
export async function initMermaid(options = {}) {
  const { default: mermaid } = await import(
    'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs'
  );

  const accent = getComputedStyle(document.documentElement)
    .getPropertyValue('--ex-accent').trim() || '#2dd4bf';

  mermaid.initialize({
    startOnLoad: false,
    theme: 'dark',
    themeVariables: {
      primaryColor: '#2d3748',
      primaryBorderColor: accent,
      lineColor: '#404040',
      textColor: '#e0e0e0',
      fontFamily: 'InputSans, ui-monospace, monospace',
      edgeLabelBackground: '#1a2a2a',
    },
    flowchart: {
      htmlLabels: true,
      useMaxWidth: true,
      curve: 'basis',
      nodeSpacing: 50,
      rankSpacing: 50,
      diagramPadding: 20,
      wrappingWidth: 200,
    },
    sequence: {
      actorMargin: 60,
      messageMargin: 30,
      useMaxWidth: true,
    },
    class: {
      useMaxWidth: true,
    },
    er: {
      useMaxWidth: true,
    },
  });

  // Type detection
  const TYPE_MAP = {
    flowchart: 'flowchart',
    graph: 'graph',
    sequenceDiagram: 'sequence',
    classDiagram: 'class',
    erDiagram: 'er',
  };
  function detectType(src) {
    return TYPE_MAP[src.trim().split(/\s+/)[0]] || null;
  }

  // SVG cleanup — remove fixed width/height attrs; CSS width:100% max-width:100% handles scaling.
  function cleanupSvg(svgEl) {
    svgEl.removeAttribute('width');
    svgEl.removeAttribute('height');
    svgEl.style.removeProperty('width');
    svgEl.style.removeProperty('height');
    svgEl.style.removeProperty('max-width');
  }

  // Per-type skeleton heights (match CSS max-height values)
  const TYPE_HEIGHTS = { flowchart: 700, graph: 700, sequence: 800, class: 650, er: 500 };

  // Panzoom lazy loader — use jsdelivr +esm shim for ESM compatibility
  let panzoomLib = null;
  async function loadPanzoom() {
    if (panzoomLib) return panzoomLib;
    const mod = await import('https://cdn.jsdelivr.net/npm/panzoom@9.4.3/+esm');
    panzoomLib = mod.default || mod;
    return panzoomLib;
  }

  function initPanzoom(svgEl, container) {
    loadPanzoom().then(Panzoom => {
      if (container._panzoomInstance) {
        try { container._panzoomInstance.dispose(); } catch(e) {}
        container._panzoomInstance = null;
      }
      const existing = container.querySelector('.ex-panzoom-hint');
      if (existing) existing.remove();
      const existingWrapper = container.querySelector('.ex-panzoom-wrap');
      if (existingWrapper) existingWrapper.replaceWith(svgEl);

      // Get natural dimensions from viewBox
      const vb = svgEl.getAttribute('viewBox');
      const vbParts = vb ? vb.split(' ') : [];
      const naturalW = parseFloat(vbParts[2]) || svgEl.getBoundingClientRect().width;
      const naturalH = parseFloat(vbParts[3]) || svgEl.getBoundingClientRect().height;

      // Set SVG to natural pixel size — panzoom viewport model requires this
      svgEl.style.width = naturalW + 'px';
      svgEl.style.height = naturalH + 'px';

      // Wrap SVG — panzoom targets wrapper div, not SVG (avoids viewBox coord conflict)
      const wrapper = document.createElement('div');
      wrapper.className = 'ex-panzoom-wrap';
      wrapper.style.cssText = `width:${naturalW}px; height:${naturalH}px; cursor:grab;`;
      svgEl.parentNode.insertBefore(wrapper, svgEl);
      wrapper.appendChild(svgEl);

      // Container becomes a fixed-height viewport
      const viewportH = parseInt(container.style.maxHeight) ||
                        parseInt(getComputedStyle(container).maxHeight) || 500;
      container.style.height = viewportH + 'px';
      container.style.maxHeight = '';
      container.style.overflow = 'hidden';

      // Compute initial zoom to fit diagram width in container
      const containerW = container.clientWidth;
      const fitZoom = Math.min(1, (containerW - 40) / naturalW);

      const instance = Panzoom(wrapper, {
        maxZoom: 4,
        minZoom: 0.1,
        smoothScroll: false,
        startScale: fitZoom,
        startX: 0,
        startY: 0,
      });
      container._panzoomInstance = instance;
      container.addEventListener('wheel', instance.zoomWithWheel, { passive: true });

      const hint = document.createElement('div');
      hint.className = 'ex-panzoom-hint';
      hint.textContent = 'scroll to zoom \u00b7 drag to pan';
      container.appendChild(hint);
    }).catch(err => {
      console.warn('Panzoom load failed:', err);
    });
  }

  // Modal — single shared instance
  function initModal() {
    let modal = document.querySelector('.ex-diagram-modal');
    if (!modal) {
      modal = document.createElement('div');
      modal.className = 'ex-diagram-modal';
      modal.setAttribute('role', 'dialog');
      modal.setAttribute('aria-modal', 'true');
      modal.innerHTML = `
        <div class="ex-diagram-modal__inner">
          <div class="ex-diagram-modal__title" id="ex-modal-title"></div>
          <button class="ex-diagram-modal__close" aria-label="Close diagram">Close \u2715</button>
          <div class="ex-diagram-modal__svg-wrap"></div>
        </div>
      `;
      modal.setAttribute('aria-labelledby', 'ex-modal-title');
      document.body.appendChild(modal);
    }

    const closeBtn = modal.querySelector('.ex-diagram-modal__close');
    const titleEl = modal.querySelector('.ex-diagram-modal__title');
    const svgWrap = modal.querySelector('.ex-diagram-modal__svg-wrap');
    let returnFocus = null;

    function openModal(title, src) {
      returnFocus = document.activeElement;
      titleEl.textContent = title;
      svgWrap.innerHTML = '';
      modal.classList.add('is-open');
      closeBtn.focus();

      const id = `mermaid-modal-${Math.random().toString(36).slice(2)}`;
      mermaid.render(id, src).then(({ svg }) => {
        svgWrap.innerHTML = svg;
        const svgEl = svgWrap.querySelector('svg');
        if (svgEl) {
          svgEl.removeAttribute('width');
          svgEl.removeAttribute('height');
          svgEl.style.width = 'auto';
          svgEl.style.height = 'auto';
        }
      }).catch(err => {
        svgWrap.textContent = 'Could not render diagram.';
        console.warn('Modal render error:', err);
      });
    }

    function closeModal() {
      modal.classList.remove('is-open');
      if (returnFocus) { returnFocus.focus(); returnFocus = null; }
    }

    closeBtn.addEventListener('click', closeModal);

    // Backdrop click
    modal.addEventListener('click', (e) => {
      if (e.target === modal) closeModal();
    });

    // Escape key
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && modal.classList.contains('is-open')) {
        e.preventDefault();
        closeModal();
      }
    });

    // Basic focus trap
    modal.addEventListener('keydown', (e) => {
      if (!modal.classList.contains('is-open') || e.key !== 'Tab') return;
      const focusable = [...modal.querySelectorAll('button, [tabindex="0"]')];
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey) {
        if (document.activeElement === first) { e.preventDefault(); last.focus(); }
      } else {
        if (document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    });

    return { openModal };
  }

  const { openModal } = initModal();

  function addExpandButton(container, title, src) {
    const existing = container.querySelector('.ex-expand-btn');
    if (existing) return;
    const btn = document.createElement('button');
    btn.className = 'ex-expand-btn';
    btn.textContent = 'Expand \u2922';
    btn.setAttribute('aria-label', `Expand ${title} diagram fullscreen`);
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      openModal(title, src);
    });
    container.appendChild(btn);
  }

  const rendered = new Set();

  async function renderCard(card) {
    if (rendered.has(card)) return;
    const header = card.querySelector('.ex-diagram-card__header');
    if (header?.getAttribute('aria-expanded') === 'false') return;

    const pre = card.querySelector('.mermaid');
    if (!pre) return;
    rendered.add(card);

    // Store original source before first render
    if (!pre.dataset.src) pre.dataset.src = pre.textContent.trim();
    const src = pre.dataset.src;

    const container = pre.closest('.ex-mermaid-container') || pre.parentElement;
    const cardTitleEl = card.querySelector('.ex-diagram-card__title');
    const cardTitle = cardTitleEl ? cardTitleEl.textContent.trim() : 'Diagram';

    // Detect type and apply class
    const type = detectType(src);
    if (type && !container.classList.contains(`ex-mermaid-type-${type}`)) {
      container.classList.add(`ex-mermaid-type-${type}`);
    }

    // Apply data-diagram-height override
    const heightOverride = container.dataset.diagramHeight;
    if (heightOverride) {
      container.style.maxHeight = heightOverride + 'px';
      container.style.overflowY = 'auto';
    }

    // Dispose existing panzoom instance before re-render
    if (container._panzoomInstance) {
      container._panzoomInstance.dispose();
      container._panzoomInstance = null;
    }

    // Show skeleton
    const skeletonHeight = heightOverride || TYPE_HEIGHTS[type] || 300;
    pre.style.display = 'none';
    const existingSvg = container.querySelector('svg');
    if (existingSvg) existingSvg.remove();
    const skeleton = document.createElement('div');
    skeleton.className = 'ex-skeleton';
    skeleton.style.height = skeletonHeight + 'px';
    container.insertBefore(skeleton, pre);

    let retried = false;
    async function attempt() {
      try {
        const id = `mermaid-${Math.random().toString(36).slice(2)}`;
        const { svg } = await mermaid.render(id, src);
        skeleton.remove();
        pre.style.display = '';
        pre.innerHTML = svg;
        pre.removeAttribute('data-processed');

        const svgEl = pre.querySelector('svg');
        if (svgEl) {
          cleanupSvg(svgEl);

          // Panzoom
          if (container.dataset.panzoom === 'true') {
            requestAnimationFrame(() => initPanzoom(svgEl, container));
          }

          // Expand button (only added once)
          if (container.dataset.expandable === 'true' && !container.querySelector('.ex-expand-btn')) {
            addExpandButton(container, cardTitle, src);
          }
        }
      } catch (err) {
        if (!retried) {
          retried = true;
          await new Promise(r => setTimeout(r, 500));
          await attempt();
        } else {
          skeleton.remove();
          pre.style.display = '';
          console.warn('Mermaid render error:', err);
        }
      }
    }

    await attempt();
  }

  // IntersectionObserver
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) renderCard(entry.target);
    });
  }, { threshold: 0.1 });

  document.querySelectorAll('.ex-diagram-card').forEach(card => {
    observer.observe(card);
  });

  // Re-render on expand click
  document.querySelectorAll('.ex-diagram-card__header').forEach(header => {
    header.addEventListener('click', () => {
      requestAnimationFrame(() => {
        if (header.getAttribute('aria-expanded') === 'true') {
          const card = header.closest('.ex-diagram-card');
          if (card) {
            rendered.delete(card);
            renderCard(card);
          }
        }
      });
    });
  });

  // ResizeObserver — re-render on significant width change
  const resizeObserver = new ResizeObserver((entries) => {
    for (const entry of entries) {
      const container = entry.target;
      const card = container.closest('.ex-diagram-card');
      if (!card) continue;
      const newWidth = entry.contentRect.width;
      const lastWidth = container._lastRenderedWidth || 0;
      if (Math.abs(newWidth - lastWidth) < 20) continue;
      container._lastRenderedWidth = newWidth;
      clearTimeout(container._resizeTimer);
      container._resizeTimer = setTimeout(() => {
        rendered.delete(card);
        renderCard(card);
      }, 300);
    }
  });

  document.querySelectorAll('.ex-mermaid-container').forEach(container => {
    resizeObserver.observe(container);
  });
}

// ---------------------------------------------------------------------------
// Search / filter
// ---------------------------------------------------------------------------

/**
 * Initialize debounced search/filter for repo-commands pages.
 * Filters .ex-cmd-section-row elements, hides empty sections.
 */
export function initSearch(options = {}) {
  const input = document.querySelector('.ex-search');
  const countEl = document.querySelector('.ex-search-count');
  if (!input) return;

  let debounceTimer;

  function filterCommands(query) {
    const q = query.toLowerCase().trim();
    const allRows = [...document.querySelectorAll('.ex-cmd-section-row')];
    const allHeaders = [...document.querySelectorAll('.ex-cmd-section-header')];

    if (!q) {
      // Show everything
      allRows.forEach(r => r.style.display = '');
      allHeaders.forEach(h => h.style.display = '');
      if (countEl) { countEl.textContent = 'All commands'; }
      return;
    }

    let visibleCount = 0;
    const sectionVisible = {};

    allRows.forEach(row => {
      const text = row.textContent.toLowerCase();
      const match = text.includes(q);
      row.style.display = match ? '' : 'none';
      if (match) {
        visibleCount++;
        const section = row.dataset.section;
        if (section) sectionVisible[section] = true;
      }
    });

    // Show/hide section headers based on whether they have visible rows
    allHeaders.forEach(header => {
      const section = header.dataset.section;
      header.style.display = sectionVisible[section] ? '' : 'none';
    });

    if (countEl) {
      countEl.textContent = `${visibleCount} result${visibleCount !== 1 ? 's' : ''}`;
    }
  }

  input.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => filterCommands(input.value), 180);
  });
}

// ---------------------------------------------------------------------------
// Breadcrumb
// ---------------------------------------------------------------------------

/**
 * Auto-inject breadcrumb from data-repo + data-doc-type on <html>.
 */
export function initBreadcrumb(options = {}) {
  const el = document.querySelector('.ex-doc-breadcrumb');
  if (!el) return;

  const repo = document.documentElement.dataset.repo || '';
  const docType = document.documentElement.dataset.docType || '';
  const docLabel = docType.replace(/-/g, ' ');

  const sep = '<span aria-hidden="true">/</span>';
  el.innerHTML = `<a href="/">explainers</a>${sep}` +
    (repo ? `<span>${repo}</span>${sep}` : '') +
    (docLabel ? `<span>${docLabel}</span>` : '');
}

// ---------------------------------------------------------------------------
// Keyboard hints panel
// ---------------------------------------------------------------------------

/**
 * Render and initialize the keyboard hints panel (.ex-kbd-hints).
 * Content varies by data-doc-type.
 */
export function initKeyboardHints() {
  const panel = document.querySelector('.ex-kbd-hints');
  if (!panel) return;

  const docType = document.documentElement.dataset.docType || '';

  const commonHints = [
    ['&#8593; / &#8595;', 'Navigate sections'],
    ['&#8592; / &#8594;', 'Collapse / Expand'],
    ['Space', 'Toggle section'],
    ['A', 'Expand all'],
    ['Esc', 'Collapse all'],
  ];

  const commandHints = [
    ...commonHints,
    ['Type', 'Filter commands'],
  ];

  const hints = docType === 'repo-commands' ? commandHints : commonHints;

  const rows = hints.map(([key, desc]) =>
    `<div class="ex-kbd-row"><span class="ex-kbd">${key}</span><span>${desc}</span></div>`
  ).join('');

  panel.innerHTML = `
    <button class="ex-kbd-hints__toggle" aria-expanded="false">
      Keyboard shortcuts
    </button>
    <div class="ex-kbd-hints__body" style="height:0;overflow:hidden;">
      <div class="ex-kbd-hints__inner">${rows}</div>
    </div>
  `;

  const toggle = panel.querySelector('.ex-kbd-hints__toggle');
  const body = panel.querySelector('.ex-kbd-hints__body');

  toggle.addEventListener('click', () => {
    const expanded = toggle.getAttribute('aria-expanded') !== 'false';
    if (expanded) {
      const h = body.scrollHeight;
      body.style.height = h + 'px';
      requestAnimationFrame(() => { body.style.height = '0'; });
      toggle.setAttribute('aria-expanded', 'false');
    } else {
      const h = body.querySelector('.ex-kbd-hints__inner').scrollHeight;
      body.style.height = h + 'px';
      body.addEventListener('transitionend', () => {
        body.style.height = 'auto';
        body.style.overflow = '';
      }, { once: true });
      toggle.setAttribute('aria-expanded', 'true');
    }
  });
}

// ---------------------------------------------------------------------------
// Default init — runs all appropriate modules based on data-doc-type
// ---------------------------------------------------------------------------

/**
 * Auto-initialize all appropriate modules based on html[data-doc-type].
 * Call this for the default setup, or import individual functions for custom control.
 */
export default function init() {
  const docType = document.documentElement.dataset.docType;

  initBreadcrumb();
  initKeyboardHints();
  initCollapsible();

  if (docType === 'architecture-gallery') {
    initMermaid();
  }
  if (docType === 'repo-commands') {
    initCopyToClipboard();
    initSearch();
  }
}
