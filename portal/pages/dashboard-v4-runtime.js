// ========== STATE ==========
  let data = null;
  let agentStatuses = {};
  let activeFilter = 'all';
  let taskSearch = '';
  let pollInterval = null;
  let connected = false;

  const taskView = document.body.dataset.taskView || 'cards';

  const AGENTS = [
    { id: 'boot', label: '@boot', color: '#f97316' },
    { id: 'ig88', label: '@ig88', color: '#60a5fa' },
    { id: 'kelk', label: '@kelk', color: '#a78bfa' },
    { id: 'nan', label: '@nan', color: '#34d399' },
  ];

  const isFileProtocol = location.protocol === 'file:';

  // ========== INIT ==========
  function initOnboarding() {
    const el = document.getElementById('onboardingContent');
    if (isFileProtocol) {
      el.innerHTML = `
        <p class="onboarding-note">Run the GSD server to enable the dashboard:</p>
        <code class="onboarding-command">./serve.sh --open</code>
        <p class="onboarding-note onboarding-note-spacious">Or load tasks.json manually (read-only):</p>
        <button class="btn btn-primary" onclick="document.getElementById('fileInput').click()">Load tasks.json</button>
      `;
    } else {
      el.innerHTML = `<p>Connecting...</p>`;
      connect();
    }
  }

  // ========== FILE INPUT FALLBACK (file:// only) ==========
  document.getElementById('fileInput').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      data = JSON.parse(await file.text());
      connected = true;
      document.getElementById('onboarding').classList.add('hidden');
      document.getElementById('statusDot').classList.add('connected');
      document.getElementById('statusText').textContent = 'local file — read-only';
      document.getElementById('saveBtn').style.display = '';
      render();
    } catch (err) {
      alert('Could not parse tasks.json: ' + err.message);
    }
  });

  // ========== CONNECT (fetch from server) ==========
  async function connect() {
    try {
      const resp = await fetch('./tasks.json', { cache: 'no-store' });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      data = await resp.json();
      connected = true;

      document.getElementById('onboarding').classList.add('hidden');
      document.getElementById('statusDot').classList.add('connected');
      document.getElementById('statusText').textContent = 'connected';
      document.getElementById('saveBtn').style.display = 'none';

      await fetchAgentStatuses();
      render();
      startPolling();
    } catch (err) {
      console.error('Connection failed:', err);
      const el = document.getElementById('onboardingContent');
      el.innerHTML = `
        <p class="onboarding-note">Could not reach GSD server. Start it with:</p>
        <code class="onboarding-command">./serve.sh --open</code>
        <button class="btn btn-primary" onclick="connect()">Retry</button>
      `;
    }
  }

  function connectWorkspace() { connect(); }

  // ========== READ ==========
  async function readTasksFile() {
    if (isFileProtocol) return data;
    try {
      const resp = await fetch('./tasks.json', { cache: 'no-store' });
      return await resp.json();
    } catch { return data; }
  }

  async function fetchAgentStatuses() {
    agentStatuses = {};
    for (const agent of AGENTS) {
      try {
        const resp = await fetch(`./status/${agent.id}.json`, { cache: 'no-store' });
        if (resp.ok) {
          agentStatuses[agent.id] = await resp.json();
        }
      } catch {}
    }
  }

  // ========== WRITE ==========
  let writing = false;

  async function writeTasksFile() {
    if (!data) return;
    if (isFileProtocol) return;

    writing = true;
    try {
      const resp = await fetch('./tasks.json', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data, null, 2)
      });
      if (!resp.ok) throw new Error(`Write failed: HTTP ${resp.status}`);
    } catch (err) {
      console.error('Write failed:', err);
      document.getElementById('statusText').textContent = 'write error — check server';
    } finally {
      writing = false;
    }
  }

  function triggerDownload() {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'tasks.json';
    a.click();
    URL.revokeObjectURL(url);
  }

  // ========== REFRESH / POLL ==========
  async function refreshData() {
    if (writing) return; // don't overwrite in-flight changes
    const newData = await readTasksFile();
    if (writing) return; // double-check after async fetch
    if (newData) data = newData;
    if (!isFileProtocol) await fetchAgentStatuses();
    render();
  }

  function startPolling() {
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(refreshData, 5000);
  }

  // ========== MUTATIONS ==========
  function addLogEntry(actor, action, taskId, detail) {
    if (!data) return;
    data.log.push({
      timestamp: new Date().toISOString(),
      actor,
      action,
      task_id: taskId,
      detail: detail || ''
    });
  }

  async function toggleTaskStatus(taskId) {
    const task = data.tasks.find(t => t.id === taskId);
    if (!task) return;

    const oldStatus = task.status;
    if (task.status === 'done') {
      task.status = 'pending';
    } else if (task.status === 'blocked') {
      return; // can't toggle blocked tasks directly
    } else {
      task.status = 'done';
    }
    task.updated = new Date().toISOString();
    data.updated = new Date().toISOString();
    data.updated_by = 'chris';

    addLogEntry('chris', task.status === 'done' ? 'completed' : 'reopened', taskId);

    // Auto-unblock tasks that depended on this one
    if (task.status === 'done') {
      data.tasks.forEach(t => {
        if (t.blocked_by.includes(taskId)) {
          const allDepsResolved = t.blocked_by.every(dep =>
            data.tasks.find(d => d.id === dep)?.status === 'done'
          );
          if (allDepsResolved && t.status === 'blocked') {
            t.status = 'pending';
            t.updated = new Date().toISOString();
            addLogEntry('system', 'unblocked', t.id, `dependency ${taskId} resolved`);
          }
        }
      });
    }

    await writeTasksFile();
    render();
  }

  async function cycleTaskStatus(taskId) {
    const task = data.tasks.find(t => t.id === taskId);
    if (!task) return;

    const cycle = ['pending', 'in-progress', 'done'];
    if (task.status === 'blocked') return;

    const idx = cycle.indexOf(task.status);
    task.status = cycle[(idx + 1) % cycle.length];
    task.updated = new Date().toISOString();
    data.updated = new Date().toISOString();
    data.updated_by = 'chris';

    addLogEntry('chris', `status → ${task.status}`, taskId);

    if (task.status === 'done') {
      data.tasks.forEach(t => {
        if (t.blocked_by.includes(taskId)) {
          const allDepsResolved = t.blocked_by.every(dep =>
            data.tasks.find(d => d.id === dep)?.status === 'done'
          );
          if (allDepsResolved && t.status === 'blocked') {
            t.status = 'pending';
            t.updated = new Date().toISOString();
            addLogEntry('system', 'unblocked', t.id, `dependency ${taskId} resolved`);
          }
        }
      });
    }

    await writeTasksFile();
    render();
  }

  async function assignTask(taskId, assignee) {
    const task = data.tasks.find(t => t.id === taskId);
    if (!task) return;
    task.assignee = assignee || null;
    task.updated = new Date().toISOString();
    data.updated = new Date().toISOString();
    data.updated_by = 'chris';
    addLogEntry('chris', 'assigned', taskId, assignee ? `→ @${assignee}` : 'unassigned');
    await writeTasksFile();
    render();
  }

  async function addTask() {
    const input = document.getElementById('addTaskInput');
    const title = input.value.trim();
    if (!title || !data) return;

    const id = title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    const maxOrder = data.tasks.reduce((max, t) => Math.max(max, t.order), 0);

    data.tasks.push({
      id,
      title,
      description: '',
      status: 'pending',
      effort: 'unknown',
      order: maxOrder + 1,
      blocked_by: [],
      block: 'unassigned',
      assignee: null,
      created: new Date().toISOString(),
      updated: new Date().toISOString()
    });

    data.updated = new Date().toISOString();
    data.updated_by = 'chris';
    addLogEntry('chris', 'created', id, title);

    input.value = '';
    await writeTasksFile();
    render();
  }

  // ========== RENDERING ==========
  function render() {
    if (!data) return;
    renderDate();
    renderStats();
    renderFilters();
    renderTasks();
    renderAgents();
    renderDeps();
    renderLog();
    syncMobilePanels();
    applyMobileStickyInput();
  }

  function renderDate() {
    const d = new Date();
    const days = ['SUN','MON','TUE','WED','THU','FRI','SAT'];
    const el = document.getElementById('dateDisplay');
    if (!el) return;
    el.textContent =
      `${days[d.getDay()]} ${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
  }

  function renderStats() {
    const tasks = data.tasks;
    setTextById('statTotal', tasks.length);
    setTextById('statPending', tasks.filter(t => t.status === 'pending').length);
    setTextById('statActive', tasks.filter(t => t.status === 'in-progress').length);
    setTextById('statBlocked', tasks.filter(t => t.status === 'blocked').length);
    setTextById('statDone', tasks.filter(t => t.status === 'done').length);
    setTextById('statAgents', Object.keys(agentStatuses).length);
    setTextById('headerTaskCount', tasks.length);
    setTextById('headerTaskLabel', tasks.length === 1 ? 'task' : 'tasks');
  }

  function setTextById(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function renderFilters() {
    const row = document.getElementById('filterRow');
    const blocks = Object.entries(data.blocks);
    row.innerHTML = `<button class="filter-chip ${activeFilter === 'all' ? 'active' : ''}" onclick="setFilter('all')" aria-pressed="${activeFilter === 'all'}">All</button>`;
    blocks.forEach(([id, block]) => {
      const count = data.tasks.filter(t => t.block === id).length;
      if (count > 0) {
        row.innerHTML += `<button class="filter-chip filter-chip-custom ${activeFilter === id ? 'active' : ''}" onclick="setFilter('${id}')" aria-pressed="${activeFilter === id}" style="--filter-chip-color:${block.color}">${block.label} (${count})</button>`;
      }
    });
  }


function setFilter(f) {
  activeFilter = f;
  render();
}

function setTaskSearch(value) {
  taskSearch = (value || '').trim().toLowerCase();
  render();
}

function getVisibleTasks() {
  let tasks = [...data.tasks].sort((a, b) => a.order - b.order);
  if (activeFilter !== 'all') {
    tasks = tasks.filter(t => t.block === activeFilter);
  }
  if (taskSearch) {
    tasks = tasks.filter(task => {
      const blockLabel = data.blocks[task.block]?.label || task.block || '';
      const haystack = [
        task.title,
        task.description,
        task.status,
        task.effort,
        task.assignee,
        blockLabel,
        task.id,
      ].filter(Boolean).join(' ').toLowerCase();
      return haystack.includes(taskSearch);
    });
  }
  return tasks;
}

function renderTasks() {
  const container = document.getElementById('taskList');
  const gridHead = document.querySelector('.task-grid-head');
  const tasks = getVisibleTasks();

  if (gridHead) {
    gridHead.classList.toggle('task-grid-head-empty', tasks.length === 0);
  }

  if (taskView === 'explorer') {
    if (tasks.length === 0) {
      container.innerHTML = `<div class="task-grid-empty">No tasks match the current filters.</div>`;
      return;
    }

    container.innerHTML = tasks.map(task => {
      const blockColor = data.blocks[task.block]?.color || '#888';
      const isCompleted = task.status === 'done';
      const isBlocked = task.status === 'blocked';
      const isActive = task.status === 'in-progress';
      const statusBadge = isBlocked
        ? `<span class="badge badge-blocked">BLOCKED</span>`
        : isActive
          ? `<span class="badge badge-in-progress">IN PROGRESS</span>`
          : isCompleted
            ? `<span class="badge badge-done">DONE</span>`
            : `<span class="badge task-grid-status-neutral">PENDING</span>`;
      const effortClass = `badge-effort-${task.effort}`;
      const assigneeHtml = task.assignee
        ? `<button class="task-assignee" onclick="event.stopPropagation();showAssigneeDropdown('${task.id}',this)" aria-label="Reassign task: ${task.title}">@${task.assignee}</button>`
        : `<button class="task-assignee task-assignee-unassigned" onclick="event.stopPropagation();showAssigneeDropdown('${task.id}',this)" aria-label="Assign task: ${task.title}">assign</button>`;

      return `
        <div class="task-grid-row ${isCompleted ? 'completed' : ''}" style="--task-block-color:${blockColor}" ondblclick="cycleTaskStatus('${task.id}')" role="listitem">
          <div class="task-grid-cell task-grid-cell-order">
            <span class="task-order">#${task.order}</span>
          </div>
          <div class="task-grid-cell task-grid-cell-main">
            <div class="task-grid-title-wrap">
              <input type="checkbox" class="task-checkbox" ${isCompleted ? 'checked' : ''} onclick="event.stopPropagation();toggleTaskStatus('${task.id}')" ${isBlocked ? 'disabled' : ''} aria-label="Mark ${task.title} as ${isCompleted ? 'incomplete' : 'complete'}">
              <div class="task-grid-text">
                <div class="task-title">${task.title}</div>
                ${task.description ? `<div class="task-desc">${task.description}</div>` : ''}
              </div>
            </div>
          </div>
          <div class="task-grid-cell task-grid-cell-status">${statusBadge}</div>
          <div class="task-grid-cell task-grid-cell-effort"><span class="badge ${effortClass}">${task.effort}</span></div>
          <div class="task-grid-cell task-grid-cell-owner">${assigneeHtml}</div>
          <div class="task-grid-cell task-grid-cell-actions"><button class="btn btn-grid-action" onclick="event.stopPropagation();cycleTaskStatus('${task.id}')">cycle</button></div>
        </div>
      `;
    }).join('');
    return;
  }

  container.innerHTML = tasks.map(task => {
    const blockColor = data.blocks[task.block]?.color || '#888';
    const isCompleted = task.status === 'done';
    const isBlocked = task.status === 'blocked';
    const isActive = task.status === 'in-progress';

    let statusBadge = '';
    if (isBlocked) statusBadge = `<span class="badge badge-blocked">BLOCKED</span>`;
    else if (isActive) statusBadge = `<span class="badge badge-in-progress">IN PROGRESS</span>`;
    else if (isCompleted) statusBadge = `<span class="badge badge-done">DONE</span>`;

    const effortClass = `badge-effort-${task.effort}`;
    const assigneeHtml = task.assignee
      ? `<button class="task-assignee" onclick="event.stopPropagation();showAssigneeDropdown('${task.id}',this)" aria-label="Reassign task: ${task.title}">@${task.assignee}</button>`
      : `<button class="task-assignee task-assignee-unassigned" onclick="event.stopPropagation();showAssigneeDropdown('${task.id}',this)" aria-label="Assign task: ${task.title}">assign</button>`;

    return `
      <div class="task-card ${isCompleted ? 'completed' : ''}" style="--task-block-color:${blockColor}" ondblclick="cycleTaskStatus('${task.id}')" role="listitem">
        <div class="task-top">
          <span class="task-order">#${task.order}</span>
          <input type="checkbox" class="task-checkbox" ${isCompleted ? 'checked' : ''} onclick="event.stopPropagation();toggleTaskStatus('${task.id}')" ${isBlocked ? 'disabled' : ''} aria-label="Mark ${task.title} as ${isCompleted ? 'incomplete' : 'complete'}">
          <div class="task-body">
            <div class="task-title">${task.title}</div>
            ${task.description ? `<div class="task-desc">${task.description}</div>` : ''}
            <div class="task-meta">
              ${statusBadge}
              <span class="badge ${effortClass}">${task.effort}</span>
              ${assigneeHtml}
            </div>
          </div>
        </div>
      </div>
    `;
  }).join('');
}

  let openDropdown = null;
  function showAssigneeDropdown(taskId, el) {
    if (openDropdown) { openDropdown.remove(); openDropdown = null; }
    const card = el.closest('.task-card, .task-grid-row');
    const dropdown = document.createElement('div');
    dropdown.className = 'assignee-dropdown';
    dropdown.innerHTML = `
      <div class="assignee-option" onclick="assignTask('${taskId}',null);closeDropdown()">unassign</div>
      <div class="assignee-option" onclick="assignTask('${taskId}','chris');closeDropdown()">chris</div>
      ${AGENTS.map(a => `<div class="assignee-option" onclick="assignTask('${taskId}','${a.id}');closeDropdown()">${a.label}</div>`).join('')}
    `;
    card.style.position = 'relative';
    card.appendChild(dropdown);
    openDropdown = dropdown;
    setTimeout(() => document.addEventListener('click', closeDropdown, { once: true }), 0);
  }

  function closeDropdown() {
    if (openDropdown) { openDropdown.remove(); openDropdown = null; }
  }

  function renderAgents() {
    const container = document.getElementById('agentList');
    container.innerHTML = AGENTS.map(agent => {
      const status = agentStatuses[agent.id];
      const isOnline = !!status;
      const isWorking = status?.status === 'working';
      const dotClass = isWorking ? 'working' : (isOnline ? 'online' : 'offline');
      const rawStatus = status?.current_task
        ? `Working on: ${status.current_task}`
        : (isOnline ? status?.notes || 'idle' : 'offline');
      const statusText = rawStatus.length > 140 ? rawStatus.slice(0, 140) + '…' : rawStatus;

      return `
        <div class="agent-card">
          <div class="agent-avatar" style="--agent-avatar-color:${agent.color}">${agent.id.slice(0,2).toUpperCase()}</div>
          <div class="agent-info">
            <div class="agent-name">${agent.label}</div>
            <div class="agent-status-text">${statusText}</div>
          </div>
          <div class="agent-dot ${dotClass}"></div>
        </div>
      `;
    }).join('');
  }

  function renderDeps() {
    const container = document.getElementById('depGraph');
    const blockedTasks = data.tasks.filter(t => t.blocked_by.length > 0);
    if (blockedTasks.length === 0) {
      container.innerHTML = `<div class="deps-empty-note">No active dependencies</div>`;
      return;
    }

    let html = '';
    blockedTasks.forEach(task => {
      task.blocked_by.forEach(depId => {
        const dep = data.tasks.find(t => t.id === depId);
        if (!dep) return;
        const depColor = data.blocks[dep.block]?.color || '#888';
        const taskColor = data.blocks[task.block]?.color || '#888';
        const depDone = dep.status === 'done';
        html += `
          <div class="dep-row ${depDone ? 'is-resolved' : ''}">
            <div class="dep-color" style="--dep-color:${depColor}"></div>
            <span>${dep.title}</span>
          </div>
          <div class="dep-arrow-row">${depDone ? '✓' : '↓'} ${depDone ? 'resolved' : 'blocks'}</div>
          <div class="dep-row ${depDone ? 'is-resolved' : ''}">
            <div class="dep-color" style="--dep-color:${taskColor}"></div>
            <span>${task.title}</span>
          </div>
        `;
      });
    });
    container.innerHTML = html;
  }

  function renderLog() {
    const container = document.getElementById('activityLog');
    const entries = [...data.log].reverse().slice(0, 30);
    container.innerHTML = entries.map(entry => {
      const time = new Date(entry.timestamp);
      const timeStr = `${String(time.getHours()).padStart(2,'0')}:${String(time.getMinutes()).padStart(2,'0')}`;
      const taskRef = entry.task_id ? ` <em>${entry.task_id}</em>` : '';
      return `
        <div class="log-entry">
          <span class="log-time">${timeStr}</span>
          <span class="log-actor">${entry.actor}</span>
          <span class="log-text">${entry.action}${taskRef} ${entry.detail || ''}</span>
        </div>
      `;
    }).join('');
  }

  // ========== MOBILE TAB SWITCHING ==========
  let mobileTab = 'tasks';

  function isMobileView() {
    return window.innerWidth <= 640;
  }

  function setMobileTab(tab) {
    mobileTab = tab;
    // Update nav button states
    document.querySelectorAll('.mobile-nav-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tab === tab);
    });
    // Toggle panels
    const taskPanel = document.querySelector('.task-panel');
    const agentsPanel = document.getElementById('mobileAgentsPanel');
    const logPanel = document.getElementById('mobileLogPanel');

    taskPanel.classList.toggle('mobile-hidden', tab !== 'tasks');
    agentsPanel.classList.toggle('mobile-visible', tab === 'agents');
    logPanel.classList.toggle('mobile-visible', tab === 'log');
  }

  // Sync mobile panel content after render
  function syncMobilePanels() {
    const mAgents = document.getElementById('mobileAgentList');
    const mDeps = document.getElementById('mobileDepGraph');
    const mLog = document.getElementById('mobileActivityLog');
    if (mAgents) mAgents.innerHTML = document.getElementById('agentList').innerHTML;
    if (mDeps) mDeps.innerHTML = document.getElementById('depGraph').innerHTML;
    if (mLog) mLog.innerHTML = document.getElementById('activityLog').innerHTML;
  }

  // Make add-task row sticky on mobile
  function applyMobileStickyInput() {
    if (!isMobileView()) return;
    const addRow = document.querySelector('.task-panel .add-task-row');
    if (addRow) addRow.classList.add('add-task-row-mobile-sticky');
  }


function initTaskSearch() {
  const input = document.getElementById('taskSearchInput');
  if (!input) return;
  input.addEventListener('input', (e) => setTaskSearch(e.target.value));
}

// ========== BOOT ==========
renderDate();
setInterval(renderDate, 30000);
initTaskSearch();
initOnboarding();
