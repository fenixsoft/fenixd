/* Fenix Dashboard — 原生 JS 单页应用（无 CDN）
   视图: #overview（跨项目概览） / #project/<name>（SPEC 列表） / #spec/<proj>/<spec>（详情）
   刷新: 2 秒轮询；刷新不丢滚动位置；接口失败/空数据兜底展示。 */

const REFRESH_MS = 2000;
const RUN_EVENTS_TAIL = 150;   // 运行中实时渲染的事件条数上限

const el = (id) => document.getElementById(id);
const $ = (sel, root) => (root || document).querySelector(sel);

// ── 工具 ────────────────────────────────────────────────
function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function api(path) {
  return fetch(path).then((r) => {
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  });
}
function fmtTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return isNaN(d) ? String(iso) : d.toLocaleTimeString('zh-CN', { hour12: false });
}
function fmtDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return isNaN(d) ? String(iso) : d.toLocaleString('zh-CN', { hour12: false });
}
function pct(done, total) {
  return total > 0 ? Math.round((done / total) * 100) : 0;
}

// ── 状态元数据（图标 + 文字，颜色不单独承载语义） ──────
const STATUS_META = {
  drafted: { cls: 'st-muted', icon: '📝', label: '草稿' },
  ready: { cls: 'st-info', icon: '📌', label: '就绪' },
  implementing: { cls: 'st-warning', icon: '🔨', label: '实现中' },
  implemented: { cls: 'st-aqua', icon: '🧪', label: '已实现' },
  testing: { cls: 'st-info', icon: '🔍', label: '验证中' },
  verified: { cls: 'st-good', icon: '✅', label: '已验证' },
  'bug-found': { cls: 'st-critical', icon: '🐛', label: '有Bug' },
  done: { cls: 'st-good', icon: '🎯', label: '完成' },
  pushed: { cls: 'st-good', icon: '🚀', label: '已推送' },
};
function statusPill(status) {
  const m = STATUS_META[status] || { cls: 'st-muted', icon: '❓', label: status || '未知' };
  return `<span class="status-pill ${m.cls}">${m.icon} ${esc(m.label)}</span>`;
}
function runStatusPill(status) {
  const map = {
    running: { cls: 'st-warning', icon: '⏳', label: '运行中' },
    empty: { cls: 'st-warning', icon: '⏳', label: '启动中' },
    done: { cls: 'st-good', icon: '✅', label: '已完成' },
    error: { cls: 'st-critical', icon: '💥', label: '异常终止' },
    missing: { cls: 'st-muted', icon: '—', label: '无记录' },
  };
  const m = map[status] || { cls: 'st-muted', icon: '❓', label: status };
  return `<span class="status-pill ${m.cls}">${m.icon} ${esc(m.label)}</span>`;
}
function progressBar(done, total) {
  const p = pct(done, total);
  const cls = p === 100 ? 'good' : p >= 60 ? '' : p > 0 ? 'warn' : 'serious';
  return `<div class="progress ${cls}"><div class="fill" style="width:${p}%"></div></div>
    <div class="progress-labels"><span>${done}/${total}</span><span>${p}%</span></div>`;
}

// ── 路由与状态 ──────────────────────────────────────────
let currentState = { view: 'overview' };
let seq = 0;
let pollTimer = null;
const runEventCache = {};   // run_id -> {events,status,error}
const expandedRuns = new Set();
const runScrolls = {};      // run_id -> scrollTop

function parseHash() {
  const h = decodeURIComponent(location.hash.slice(1) || 'overview');
  const parts = h.split('/');
  if (parts[0] === 'project' && parts[1]) return { view: 'project', project: parts[1] };
  if (parts[0] === 'spec' && parts[1] && parts[2]) {
    return { view: 'spec', project: parts[1], spec: parts[2] };
  }
  return { view: 'overview' };
}
function nav(hash) {
  if ('#' + hash === location.hash) route();
  else location.hash = hash;
}
function route() {
  for (const k in runEventCache) delete runEventCache[k];
  expandedRuns.clear();
  currentState = parseHash();
  updateTopbar();
  schedulePoll();
  load();
}
function schedulePoll() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(load, REFRESH_MS);
}

// ── 数据获取（含运行中 run 的实时流） ──────────────────
function fetchFor(state) {
  const p = encodeURIComponent(state.project || '');
  if (state.view === 'overview') return api('/api/overview');
  if (state.view === 'project') return api('/api/specs?project=' + p);
  // spec 详情 + 运行中 run 的产物流并行拉取
  const s = encodeURIComponent(state.spec);
  return api('/api/specs/' + s + '?project=' + p).then((detail) => {
    const running = (detail.runs || []).filter((r) => r.status === 'running' || r.status === 'empty');
    const fetches = running.map((r) =>
      api('/api/runs/' + encodeURIComponent(r.run_id) + '?project=' + p)
        .then((rd) => ({ id: r.run_id, run: rd }))
        .catch(() => ({ id: r.run_id, run: null }))
    );
    return Promise.all(fetches).then((rds) => {
      detail._runStreams = {};
      rds.forEach((x) => { if (x.run) detail._runStreams[x.id] = x.run; });
      return detail;
    });
  });
}

function load() {
  const mySeq = ++seq;
  captureScrolls();
  fetchFor(currentState)
    .then((data) => {
      if (mySeq !== seq) return;
      const scrollY = window.scrollY;
      renderView(currentState, data);
      restoreScrolls();
      window.scrollTo(0, scrollY);
      setOnline();
      hydratePending();
    })
    .catch((err) => {
      if (mySeq !== seq) return;
      showError(err);
      setOffline();
    });
}

// ── 滚动保持 ───────────────────────────────────────────
function captureScrolls() {
  document.querySelectorAll('[data-run-scroll]').forEach((el2) => {
    runScrolls[el2.dataset.runScroll] = el2.scrollTop;
  });
}
function restoreScrolls() {
  document.querySelectorAll('[data-run-scroll]').forEach((el2) => {
    const id = el2.dataset.runScroll;
    const prev = runScrolls[id];
    const nearBottom = prev == null || (el2.scrollHeight - el2.scrollTop - el2.clientHeight < 60);
    el2.scrollTop = nearBottom ? el2.scrollHeight : prev;
  });
}

// ── 顶栏 ───────────────────────────────────────────────
function updateTopbar() {
  const ov = el('btn-overview');
  ov.classList.toggle('active', currentState.view === 'overview');
  const sel = el('project-select');
  // 拉取项目列表（概览数据里已有，避免额外请求：仅填充一次）
  if (sel.options.length === 0) {
    api('/api/projects')
      .then((d) => {
        (d.projects || []).forEach((p) => {
          const o = document.createElement('option');
          o.value = p.name;
          o.textContent = p.name + (p.discovered ? '（自动）' : '');
          sel.appendChild(o);
        });
        syncSelect();
      })
      .catch(() => {});
  } else {
    syncSelect();
  }
}
function syncSelect() {
  const sel = el('project-select');
  sel.value = currentState.project || '';
}
el('btn-overview').addEventListener('click', () => nav('overview'));
el('project-select').addEventListener('change', (e) => {
  if (e.target.value) nav('project/' + encodeURIComponent(e.target.value));
  else nav('overview');
});
window.addEventListener('hashchange', route);

// ── 在线/离线指示 ──────────────────────────────────────
function setOnline() {
  el('refresh-dot').classList.remove('off');
  el('refresh-text').textContent = '2s 自动刷新';
}
function setOffline() {
  el('refresh-dot').classList.add('off');
  el('refresh-text').textContent = '接口不可达';
}
function showError(err) {
  const main = el('main');
  main.innerHTML =
    `<div class="error-banner">⚠️ 无法连接 Dashboard API：${esc(err.message)}<br>
    请确认服务仍在运行（tmux session <code>fenix-dashboard</code>）。</div>` +
    (main._lastHtml || '<div class="empty-state">无缓存内容</div>');
}

// ── 视图渲染 ───────────────────────────────────────────
function renderView(state, data) {
  const main = el('main');
  if (state.view === 'overview') main.innerHTML = renderOverview(data);
  else if (state.view === 'project') main.innerHTML = renderProject(data);
  else main.innerHTML = renderSpec(data);
  main._lastHtml = main.innerHTML;
}

function renderOverview(data) {
  const t = data.totals || {};
  const p = pct(t.task_done, t.task_total);
  const projects = data.projects || [];
  return `
    <div class="page-title">跨项目概览</div>
    <div class="page-sub">监控 ${projects.length} 个项目 · 每 2 秒自动刷新</div>
    <div class="totals-row">
      <div class="stat-tile"><div class="num">${t.spec_count ?? 0}</div><div class="label">SPEC 总数</div></div>
      <div class="stat-tile"><div class="num">${t.task_done ?? 0}/${t.task_total ?? 0}</div><div class="label">任务进度</div></div>
      <div class="stat-tile"><div class="num" style="color:${(t.problems || 0) ? 'var(--critical)' : ''}">${t.problems ?? 0}</div><div class="label">问题/阻塞</div></div>
      <div class="stat-tile"><div class="num" style="color:${(t.active_runs || 0) ? 'var(--warning)' : ''}">${t.active_runs ?? 0}</div><div class="label">活跃 Agent 运行</div></div>
      <div class="stat-tile"><div class="num">${p}%</div><div class="label">总体实现进度</div></div>
    </div>
    <div class="cards-grid">
      ${projects.map(projectCard).join('') || '<div class="empty-state">尚未注册任何项目 — 在任意 Fenixd 项目内执行 /fenix-dashboard</div>'}
    </div>`;
}

function projectCard(p) {
  if (!p.exists) {
    return `<div class="card no-hover" style="border-color:rgba(208,59,59,.4)">
      <h3>${esc(p.name)} <span class="status-pill st-critical">⚠ 路径不存在</span></h3>
      <div class="card-meta">${esc(p.path)}</div></div>`;
  }
  const pills = Object.entries(p.status_counts || {})
    .map(([st, n]) => {
      const m = STATUS_META[st] || { cls: 'st-muted', icon: '❓', label: st };
      return `<span class="status-pill ${m.cls}">${m.icon} ${esc(m.label)} ${n}</span>`;
    })
    .join(' ');
  const pp = pct(p.task_done, p.task_total);
  return `
  <div class="card" onclick="nav('project/${encodeURIComponent(p.name)}')">
    <h3>${esc(p.name)}
      ${p.discovered ? '<span class="status-pill st-muted">自动发现</span>' : ''}
    </h3>
    <div class="card-meta">${esc(p.path)}</div>
    <div class="kv-row"><span class="k">SPEC 数</span><span class="v">${p.spec_count}</span></div>
    <div class="kv-row"><span class="k">问题/阻塞</span><span class="v" style="color:${(p.problems || 0) ? 'var(--critical)' : ''}">${p.problems}</span></div>
    <div class="kv-row"><span class="k">活跃运行</span><span class="v" style="color:${(p.active_runs || 0) ? 'var(--warning)' : ''}">${p.active_runs}</span></div>
    ${progressBar(p.task_done, p.task_total)}
    <div style="margin-top:10px;display:flex;flex-wrap:wrap;gap:6px">${pills}</div>
  </div>`;
}

function renderProject(data) {
  const specs = data.specs || [];
  const project = esc(data.project);
  return `
    <div class="breadcrumb"><button onclick="nav('overview')">← 概览</button><span class="sep">/</span>${project}</div>
    <div class="page-title">${project}</div>
    <div class="page-sub">${specs.length} 个 SPEC · 每 2 秒自动刷新</div>
    ${specs.map((s) => specRow(data.project, s)).join('')}
    ${specs.length === 0 ? '<div class="empty-state">该项目暂无 SPEC</div>' : ''}`;
}

function specRow(project, s) {
  const pp = pct(s.task_done, s.task_total);
  const cls = pp === 100 ? 'good' : pp >= 60 ? '' : pp > 0 ? 'warn' : 'serious';
  const verify = s.verify_total > 0
    ? `<span title="验证进度">验证 ${s.verify_done}/${s.verify_total}</span>`
    : '';
  const err = s.error
    ? `<span class="err-tag" title="${esc(s.error)}">⚠ ${esc(String(s.error).slice(0, 50))}</span>`
    : '';
  return `
  <div class="spec-row" onclick="nav('spec/${encodeURIComponent(project)}/${encodeURIComponent(s.name)}')">
    ${statusPill(s.status)}
    <span class="spec-name">${esc(s.name)}</span>
    <div class="spec-metrics">
      <span title="优先级">P${s.priority ?? '?'}</span>
      <div class="progress ${cls}" style="width:120px"><div class="fill" style="width:${pp}%"></div></div>
      <span title="任务进度">${s.task_done}/${s.task_total}</span>
      ${verify}
    </div>
    ${err}
  </div>`;
}

function renderSpec(d) {
  return `
    <div class="breadcrumb">
      <button onclick="nav('project/${encodeURIComponent(d.project)}')">← ${esc(d.project)}</button>
      <span class="sep">/</span>${esc(d.name)}
    </div>
    <div class="page-title">${esc(d.name)} ${statusPill(d.status)}</div>
    <div class="page-sub">
      P${d.priority ?? '?'} · 创建 ${fmtDate(d.created)} · 更新 ${fmtDate(d.updated)}
      ${d.depends_on ? ` · 依赖 ${esc(d.depends_on)}` : ''}
    </div>
    ${d.error ? `<div class="error-banner">⚠ ${esc(d.error)}</div>` : ''}
    ${renderVerify(d)}
    ${renderTasks(d)}
    ${renderScenarios(d)}
    ${renderBugs(d)}
    ${renderScreenshots(d)}
    ${renderRuns(d)}`;
}

function renderVerify(d) {
  const v = d.verify_progress || {};
  if (!v.exists) return '';
  const p = pct(v.done, v.total);
  const corrupt = v.error ? `<div class="kv-row"><span class="k">进度文件</span><span class="v st-critical">损坏</span></div>` : '';
  return `
  <div class="section">
    <div class="section-title">验证进度</div>
    <div class="card no-hover">
      ${corrupt}
      ${progressBar(v.done, v.total)}
      <div class="kv-row"><span class="k">当前</span><span class="v">${esc(v.current || '—')}</span></div>
    </div>
  </div>`;
}

function renderTasks(d) {
  const groups = d.tasks || [];
  if (!groups.length) return '';
  const all = groups.flatMap((g) => g.tasks || []);
  const done = all.filter((t) => t.done).length;
  return `
  <div class="section">
    <div class="section-title">任务清单<span class="count">${done}/${all.length}</span></div>
    <div class="card no-hover">
      ${progressBar(done, all.length)}
      ${groups.map((g) => `
        <div class="task-group">
          <h4>${esc(g.title)} <span class="count">${g.done}/${g.total}</span></h4>
          ${(g.tasks || []).map((t) => `
            <div class="task-item ${t.done ? 'done' : ''}">
              <span class="tick ${t.done ? 'on' : ''}">${t.done ? '☑' : '☐'}</span>
              <code>${esc(t.id)}</code> ${esc(t.desc)}
            </div>`).join('')}
        </div>`).join('')}
    </div>
  </div>`;
}

function renderScenarios(d) {
  const scenarios = d.scenarios || [];
  const rep = d.report || {};
  if (!scenarios.length) {
    if (rep.error) return `<div class="section"><div class="section-title">场景结果</div><div class="empty-state">report.json 损坏或不可读</div></div>`;
    return '';
  }
  const summary = rep.summary || {};
  const sum = summary.total
    ? `<span class="count">通过 ${summary.passed} · 警告 ${summary.warnings} · 失败 ${summary.failed} · 错误 ${summary.errors}</span>`
    : '';
  return `
  <div class="section">
    <div class="section-title">场景级测试结果<span class="count">${scenarios.length} 个场景</span>${sum}</div>
    ${scenarios.map(scenarioCard).join('')}
  </div>`;
}

const SCENARIO_META = {
  pass: { cls: 'st-good', icon: '✅', label: '通过' },
  warning: { cls: 'st-warning', icon: '⚠️', label: '警告' },
  fail: { cls: 'st-critical', icon: '✗', label: '失败' },
  error: { cls: 'st-critical', icon: '✗', label: '错误' },
};
function scenarioPill(status) {
  const m = SCENARIO_META[status] || { cls: 'st-muted', icon: '❓', label: status || '未知' };
  return `<span class="status-pill ${m.cls}">${m.icon} ${esc(m.label)}</span>`;
}

function scenarioCard(sc) {
  const status = sc.status || 'unknown';
  const asserts = (sc.assertion_results || []).map((a) => {
    const ok = a.pass !== false;
    const msg = ok ? '' : ` — ${esc(a.message || a.detail || a.actual || '')}`;
    return `<div class="assertion ${ok ? 'ok' : 'bad'}">
      <span class="a-status">${ok ? '✓' : '✗'}</span>
      <span class="a-label">${esc(a.type || '?')}: ${esc(a.label || a.message || '')}</span>
      <span class="a-msg">${msg}</span>
    </div>`;
  }).join('');
  const steps = (sc.step_results || []).filter((s) => !s.success).map((s) =>
    `<div class="assertion bad"><span class="a-status">✗</span><span class="a-label">步骤失败: ${esc(s.action || '?')} ${esc(s.description || '')}</span><span class="a-msg">${esc(s.error || s.message || '')}</span></div>`
  ).join('');
  return `
  <div class="scenario ${status}">
    <div class="sc-head">
      ${scenarioPill(status)}
      <span class="sc-id">${esc(sc.scenario_id || '?')}</span>
      <span class="sc-desc">${esc(sc.description || '')}</span>
    </div>
    ${(steps || asserts) ? `<div class="assertions">${steps}${asserts}</div>` : ''}
  </div>`;
}

function renderBugs(d) {
  const bugs = d.bugs || [];
  if (!bugs.length) return '';
  const sevCls = (s) => (s === 'critical' ? 'st-critical' : s === 'minor' ? 'st-muted' : 'st-serious');
  return `
  <div class="section">
    <div class="section-title">Bug 列表<span class="count">${bugs.length}</span></div>
    ${bugs.map((b) => `
      <div class="bug-card">
        <div class="bug-sev ${sevCls(b.severity)}">${esc(b.severity || 'major')} · ${esc(b.source || 'report')}</div>
        <div class="bug-desc">${esc(b.description || '')}</div>
        <div class="bug-meta">
          ${(b.scenario_ids || []).map((x) => esc(x)).join(', ')}
          ${b.assertion_type ? '· 断言 ' + esc(b.assertion_type) : ''}
          ${b.section ? '· ' + esc(b.section) : ''}
        </div>
        ${b.evidence ? `<div class="bug-evidence">${esc(b.evidence)}</div>` : ''}
        ${(b.screenshots || []).map((f) => screenshotThumb(d, f)).join('')}
      </div>`).join('')}
  </div>`;
}

function screenshotUrl(d, file) {
  return `/screenshots/${encodeURIComponent(d.project)}/${encodeURIComponent(d.name)}/${encodeURIComponent(file)}`;
}
function screenshotThumb(d, file) {
  return `<img class="thumb" src="${screenshotUrl(d, file)}" alt="${esc(file)}" onclick="event.stopPropagation();openLightbox('${screenshotUrl(d, file)}')" />`;
}
function renderScreenshots(d) {
  const shots = d.screenshots || [];
  if (!shots.length) return '';
  return `
  <div class="section">
    <div class="section-title">失败截图<span class="count">${shots.length}</span><span class="count">（点击放大）</span></div>
    <div class="thumb-grid">${shots.map((s) => screenshotThumb(d, s.file)).join('')}</div>
  </div>`;
}

// ── 运行记录 + 实时 LLM 对话 ───────────────────────────
function renderRuns(d) {
  const runs = d.runs || [];
  const items = runs.map((r) => {
    const live = r.status === 'running' || r.status === 'empty';
    const stream = d._runStreams ? d._runStreams[r.run_id] : null;
    return runCard(d, r, stream, live);
  }).join('');
  const total = runs.length;
  return `
  <div class="section">
    <div class="section-title">运行记录<span class="count">${total}</span></div>
    ${items || '<div class="empty-state">暂无运行记录</div>'}
  </div>`;
}

function runCard(d, r, stream, live) {
  const expanded = live || expandedRuns.has(r.run_id);
  let body;
  if (live) {
    body = liveRunBody(stream);
  } else if (runEventCache[r.run_id]) {
    body = cachedRunBody(runEventCache[r.run_id]);
  } else if (expanded) {
    body = '<div class="empty-state">加载中…</div>';
    pendingHydrates.push(r.run_id);
  } else {
    body = '<div class="empty-state">点击展开加载对话</div>';
  }
  return `
  <div class="run-card">
    <div class="run-head" onclick="toggleRun('${esc(r.run_id)}')">
      <span class="run-id">${esc(r.run_id)}</span>
      <span class="run-type">${esc(r.agent_type)}</span>
      ${runStatusPill(r.status)}
      <span class="run-type">${fmtTime(r.started)}</span>
    </div>
    <div class="run-body ${expanded ? '' : 'hidden'}" id="run-body-${esc(r.run_id)}">${body}</div>
  </div>`;
}

let pendingHydrates = [];
function hydratePending() {
  if (!pendingHydrates.length) return;
  const list = pendingHydrates;
  pendingHydrates = [];
  list.forEach((id) => {
    const body = document.getElementById('run-body-' + id);
    if (body) hydrateRun(id, body);
  });
}
function hydrateRun(runId, body) {
  api('/api/runs/' + encodeURIComponent(runId) + '?project=' + encodeURIComponent(currentState.project))
    .then((d) => {
      runEventCache[runId] = d;
      if (body.isConnected) body.innerHTML = cachedRunBody(d);
    })
    .catch(() => { if (body.isConnected) body.innerHTML = '<div class="empty-state">加载失败</div>'; });
}
function toggleRun(runId) {
  const body = document.getElementById('run-body-' + runId);
  if (!body) return;
  const hidden = body.classList.contains('hidden');
  if (hidden) {
    expandedRuns.add(runId);
    body.classList.remove('hidden');
    if (!runEventCache[runId]) hydrateRun(runId, body);
  } else {
    expandedRuns.delete(runId);
    body.classList.add('hidden');
  }
}

function liveRunBody(stream) {
  if (!stream || !(stream.events || []).length) {
    return '<div class="empty-state">等待事件…（jsonl 尚未产生内容，实时轮询中）</div>';
  }
  const events = stream.events;
  const tail = events.slice(-RUN_EVENTS_TAIL);
  return `<div class="run-events-scroll" data-run-scroll="${esc(stream.run_id)}">${tail.map(runEvent).join('')}</div>
    <div class="kv-row"><span class="k">已捕获 ${events.length} 条事件（显示最近 ${tail.length} 条）</span><span class="k st-warning">● 实时</span></div>`;
}
function cachedRunBody(d) {
  const events = d.events || [];
  const bodyHtml = events.slice(-200).map(runEvent).join('');
  const err = d.status === 'error' && d.error ? runEvent(d.error) : '';
  return `<div class="run-events-scroll" data-run-scroll="${esc(d.run_id)}">${err}${bodyHtml}</div>
    <div class="kv-row"><span class="k">共 ${events.length} 条事件</span></div>`;
}

function runEvent(ev) {
  const t = ev.type;
  const cls =
    t === 'assistant' ? 'assistant' :
    t === 'user' ? 'user' :
    t === 'tool_use' ? 'tool' :
    t === 'tool_result' ? 'tool-result' :
    t === 'error' ? 'error' :
    t === 'stderr' ? 'stderr' :
    t === 'result' ? 'assistant' : '';
  let content = '';
  if (t === 'assistant') {
    // stream-json 中 tool_use 是 assistant 消息的内容块，非顶层事件
    const msg = ev.message || {};
    const blocks = msg.content || [];
    const text = blocks.filter((c) => c && c.type === 'text').map((c) => c.text).join(' ');
    const tool = blocks.find((c) => c && c.type === 'tool_use');
    let out = '';
    if (tool) {
      out += `🔧 ${esc(tool.name || 'tool')}<span class="pre-wrap"> ${esc(JSON.stringify(tool.input).slice(0, 500))}</span>`;
    }
    if (text) out += (out ? '<br>' : '') + esc(text).slice(0, 2000);
    content = out || esc(JSON.stringify(ev).slice(0, 300));
  } else if (t === 'user') {
    // tool_result 是 user 消息的内容块
    const msg = ev.message || {};
    const blocks = msg.content || [];
    const text = blocks.filter((x) => typeof x === 'string').join(' ');
    let out = blocks
      .filter((x) => x && x.type === 'tool_result')
      .map((c) => `⚙️${c.is_error ? '（错误）' : ''} ${esc(String(c.content).slice(0, 300))}`)
      .join('<br>');
    if (text) out += (out ? '<br>' : '') + `🧑 ${esc(text.slice(0, 300))}`;
    content = out || esc(JSON.stringify(ev).slice(0, 300));
  } else if (t === 'tool_use') {
    content = `🔧 ${esc(ev.name || 'tool')}<span class="pre-wrap"> ${esc(JSON.stringify(ev.input || {}).slice(0, 500))}</span>`;
  } else if (t === 'tool_result') {
    content = `⚙️ ${esc(String(ev.content || '').slice(0, 300))}`;
  } else if (t === 'result') {
    content = `🏁 ${esc(String(ev.result || '')).slice(0, 500)}（turns: ${ev.num_turns ?? '?'}）`;
  } else if (t === 'error') {
    content = `💥 ${esc(ev.error || '异常终止')}${ev.exit_code != null ? `（exit_code: ${ev.exit_code}）` : ''}`;
  } else if (t === 'stderr') {
    content = `⚠ ${esc(ev.line || '')}`;
  } else if (t === 'system') {
    content = `⚙ 系统: ${esc(ev.subtype || '')}`;
  } else {
    content = esc(JSON.stringify(ev).slice(0, 300));
  }
  return `<div class="run-event ${cls}"><span class="pre-wrap">${content}</span></div>`;
}

// ── 截图灯箱 ───────────────────────────────────────────
function openLightbox(src) {
  el('lightbox-img').src = src;
  el('lightbox').classList.remove('hidden');
}
el('lightbox').addEventListener('click', () => el('lightbox').classList.add('hidden'));
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') el('lightbox').classList.add('hidden');
});

// 导出到全局供内联 onclick 使用
window.nav = nav;
window.toggleRun = toggleRun;
window.openLightbox = openLightbox;

// ── 启动 ───────────────────────────────────────────────
route();
