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
function fmtDuration(sec) {
  if (sec == null || isNaN(sec)) return '';
  sec = Math.max(0, Math.round(sec));
  if (sec < 60) return sec + '秒';
  const m = Math.floor(sec / 60), s = sec % 60;
  if (m < 60) return (s ? m + '分' + s + '秒' : m + '分');
  return Math.floor(m / 60) + '时' + (m % 60) + '分' + (s ? s + '秒' : '');
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
let autoRefresh = true;   // 右上角开关：关闭后停止 2s 轮询，便于复制内容
const runEventCache = {};   // run_id -> {events,status,error}
const expandedRuns = new Set();
const runScrolls = {};      // run_id -> scrollTop
const specFilter = { q: '', status: '' };  // 项目视图过滤状态，跨刷新保持

function parseHash() {
  const h = decodeURIComponent(location.hash.slice(1) || 'overview');
  const parts = h.split('/');
  if (parts[0] === 'project' && parts[1]) return { view: 'project', project: parts[1] };
  if (parts[0] === 'spec' && parts[1] && parts[2]) {
    return { view: 'spec', project: parts[1], spec: parts[2] };
  }
  if (parts[0] === 'config') {
    // config/<project>  或 config（无项目则选第一个）
    return { view: 'config', project: parts[1] || '' };
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
// 刷新是否暂停：开关关闭，或当前处于「配置」页（表单编辑中不可被轮询整页重绘）
function refreshPaused() {
  return !autoRefresh || currentState.view === 'config';
}
function refreshLabel() {
  if (!autoRefresh) return '自动刷新已暂停';
  if (currentState.view === 'config') return '配置页不自动刷新';
  return '2s 自动刷新';
}
function schedulePoll() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
  if (refreshPaused()) {
    el('refresh-dot').classList.add('off');
    el('refresh-text').textContent = refreshLabel();
    return;
  }
  el('refresh-dot').classList.remove('off');
  el('refresh-text').textContent = '2s 自动刷新';
  pollTimer = setInterval(load, REFRESH_MS);
}
function toggleAutoRefresh() {
  autoRefresh = !!el('auto-refresh').checked;
  schedulePoll();
  // 恢复时立即刷新一次；但配置页不重载，避免冲掉正在编辑的表单
  if (autoRefresh && currentState.view !== 'config') load();
}

// ── 数据获取（含运行中 run 的实时流） ──────────────────
function fetchFor(state) {
  const p = encodeURIComponent(state.project || '');
  if (state.view === 'overview') return api('/api/overview');
  if (state.view === 'project') return api('/api/specs?project=' + p);
  if (state.view === 'config') return api('/api/config?project=' + p);
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
      if (currentState.view === 'config') hydrateConfigPage();
      if (currentState.view === 'project') hydrateProjectFilter();
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
  const cfg = el('btn-config');
  if (cfg) cfg.classList.toggle('active', currentState.view === 'config');
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
if (el('btn-config')) {
  el('btn-config').addEventListener('click', () => {
    const p = currentState.project || '';
    nav('config/' + encodeURIComponent(p));
  });
}
el('project-select').addEventListener('change', (e) => {
  if (e.target.value) nav('project/' + encodeURIComponent(e.target.value));
  else nav('overview');
});
el('auto-refresh').addEventListener('change', toggleAutoRefresh);
window.addEventListener('hashchange', route);

// ── 在线/离线指示 ──────────────────────────────────────
function setOnline() {
  el('refresh-dot').classList.toggle('off', refreshPaused());
  el('refresh-text').textContent = refreshLabel();
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
  const html = state.view === 'overview' ? renderOverview(data)
    : state.view === 'project' ? renderProject(data)
    : state.view === 'config' ? renderConfig(data)
    : renderSpec(data);
  if (main._rendered && window.morphdom) {
    // 增量更新（VuePress 热重载同思路）：只 patch 变化部分，避免整页替换导致
    // 图片重载 / 滚动重置 / CSS 过渡重启。`#tl-root` 由 React 自行管理，跳过。
    window.morphdom(main, '<main id="main">' + html + '</main>', {
      onBeforeElUpdated: (fromEl) => {
        if (fromEl && fromEl.id === 'tl-root') return false;   // 交给 React 增量更新
      },
    });
  } else {
    main.innerHTML = html;
    main._rendered = true;
  }
  main._lastHtml = html;
  mountTimeline();   // React 垂直时间轴（复用 root，React 只更新变化节点）
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

  // 前端排序：按 created 倒序（新在前），缺失 created 排最后
  const sorted = specs.slice().sort((a, b) => {
    const ac = a.created || '';
    const bc = b.created || '';
    if (!ac && !bc) return 0;
    if (!ac) return 1;
    if (!bc) return -1;
    return bc.localeCompare(ac);
  });

  // 前端过滤
  const q = specFilter.q.toLowerCase();
  const filtered = sorted.filter((s) => {
    if (q && !s.name.toLowerCase().includes(q)) return false;
    if (specFilter.status && s.status !== specFilter.status) return false;
    return true;
  });

  // 状态下拉选项：全部状态 + STATUS_META 各状态
  const statusOptions = Object.entries(STATUS_META).map(([k, m]) =>
    `<option value="${esc(k)}" ${specFilter.status === k ? 'selected' : ''}>${m.icon} ${esc(m.label)}</option>`
  ).join('');

  const rowsHtml = filtered.length
    ? filtered.map((s) => specRow(data.project, s)).join('')
    : '';

  const emptyHtml = specs.length === 0
    ? '<div class="empty-state">该项目暂无 SPEC</div>'
    : filtered.length === 0
      ? '<div class="empty-state">无匹配的 SPEC</div>'
      : '';

  return `
    <div class="breadcrumb"><button onclick="nav('overview')">← 概览</button><span class="sep">/</span>${project}</div>
    <div class="page-title">${project}</div>
    <div class="page-sub">${specs.length} 个 SPEC · 每 2 秒自动刷新</div>
    <div class="spec-filter">
      <input type="text" id="spec-filter-q" placeholder="搜索名称…" value="${esc(specFilter.q)}" />
      <select id="spec-filter-status">
        <option value="" ${specFilter.status === '' ? 'selected' : ''}>全部状态</option>
        ${statusOptions}
      </select>
    </div>
    ${rowsHtml ? `
    <div class="spec-table-wrap">
      <table class="spec-table">
        <thead>
          <tr>
            <th>状态</th>
            <th>名称</th>
            <th>优先级</th>
            <th>创建时间</th>
            <th>任务进度</th>
            <th>验证</th>
            <th>错误</th>
          </tr>
        </thead>
        <tbody>${rowsHtml}</tbody>
      </table>
    </div>` : ''}
    ${emptyHtml}`;
}

function specRow(project, s) {
  const pp = pct(s.task_done, s.task_total);
  const cls = pp === 100 ? 'good' : pp >= 60 ? '' : pp > 0 ? 'warn' : 'serious';
  const verify = s.verify_total > 0
    ? `<span title="验证进度">${s.verify_done}/${s.verify_total}</span>`
    : '<span class="muted">—</span>';
  const err = s.error
    ? `<span class="err-tag" title="${esc(s.error)}">⚠ ${esc(String(s.error).slice(0, 50))}</span>`
    : '';
  const created = s.created ? fmtDate(s.created) : '<span class="muted">—</span>';
  return `
  <tr class="spec-row" onclick="nav('spec/${encodeURIComponent(project)}/${encodeURIComponent(s.name)}')">
    <td>${statusPill(s.status)}</td>
    <td class="spec-name-cell">${esc(s.name)}</td>
    <td>P${s.priority ?? '?'}</td>
    <td class="created-cell">${created}</td>
    <td class="progress-cell">
      <div class="progress ${cls}"><div class="fill" style="width:${pp}%"></div></div>
      <div class="progress-labels"><span>${s.task_done}/${s.task_total}</span><span>${pp}%</span></div>
    </td>
    <td>${verify}</td>
    <td>${err}</td>
  </tr>`;
}

function hydrateProjectFilter() {
  const qInput = el('spec-filter-q');
  const sSelect = el('spec-filter-status');
  if (!qInput || !sSelect) return;

  if (qInput._bound) return;
  qInput._bound = true;
  sSelect._bound = true;

  qInput.addEventListener('input', (e) => {
    specFilter.q = e.target.value;
    load();
  });
  sSelect.addEventListener('change', (e) => {
    specFilter.status = e.target.value;
    load();
  });
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
    ${renderVerdict(d)}
    ${renderVerify(d)}
    ${renderTasks(d)}
    ${renderTimeline(d)}
    ${renderScenarios(d)}
    ${renderBugs(d)}
    ${renderScreenshots(d)}`;
}

function renderVerdict(d) {
  const v = d.verdict;
  if (!v || !v.exists) return '';
  const s = v.summary || {};
  const bugs = parseInt(s.product_bugs, 10) || 0;
  const env = parseInt(s.env_issues, 10) || 0;
  const status = v.status || '';
  let tone = 'pass', icon = '✅';
  if (bugs > 0 || /未通过|Bug Found|失败/.test(status)) { tone = 'fail'; icon = '❌'; }
  else if (env > 0 || /环境|无法验证|不可达|unreachable/i.test(status)) { tone = 'env'; icon = '⚠️'; }
  const bits = [];
  if (s.passed != null) bits.push(`通过 ${s.passed}`);
  if (s.failed != null) bits.push(`失败 ${s.failed}`);
  if (s.errors != null) bits.push(`错误 ${s.errors}`);
  if (s.product_bugs != null) bits.push(`产品Bug ${s.product_bugs}`);
  if (s.env_issues != null) bits.push(`环境问题 ${s.env_issues}`);
  return `
  <div class="section">
    <div class="section-title">验证结论</div>
    <div class="verdict ${tone}">
      <div class="verdict-head">${icon} ${esc(status || '已验证')}
        ${v.status_detail ? ` <span class="verdict-detail">${esc(v.status_detail)}</span>` : ''}
      </div>
      ${bits.length ? `<div class="verdict-summary">${bits.map((b) => `<span class="chip">${esc(b)}</span>`).join('')}</div>` : ''}
      ${v.conclusion ? `<div class="verdict-body">${esc(v.conclusion)}</div>` : ''}
    </div>
  </div>`;
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

// ── Markdown 渲染（vendored marked，支持 GFM 表格等复杂语法） ──
if (window.marked) {
  const __r = new window.marked.Renderer();
  // 原始 HTML 一律转义（防注入）；Markdown 语法（表格/加粗/列表等）正常渲染。
  // marked v18 的 html 渲染器统一接收 { text, block }，同时覆盖块级与行内 HTML。
  __r.html = (tok) => esc((tok && tok.text) || '');
  // 链接仅放行 http/https/mailto（手动渲染，避免委托触发 marked 内部 parseInline 缺失）
  __r.link = (tok) => {
    const href = (tok && tok.href) || '';
    const text = (tok && tok.text) || href;
    if (!/^(https?:|mailto:)/i.test(href)) return esc(text);
    return `<a href="${esc(href)}" target="_blank" rel="noopener">${esc(text)}</a>`;
  };
  window.marked.use({ renderer: __r, gfm: true, breaks: true });
}

function mdRender(text) {
  if (text == null) return '';
  try {
    const html = window.marked.parse(String(text));
    return `<div class="md">${html}</div>`;
  } catch (e) {
    return `<div class="md">${esc(String(text))}</div>`;
  }
}

// 弹窗内的事件渲染：assistant/user 文本走 Markdown，工具调用保持等宽
function runEventMd(ev) {
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
    const msg = ev.message || {};
    const blocks = msg.content || [];
    const text = blocks.filter((c) => c && c.type === 'text').map((c) => c.text).join(' ');
    const tool = blocks.find((c) => c && c.type === 'tool_use');
    let out = '';
    if (tool) out += `🔧 <code>${esc(tool.name || 'tool')}</code> <span class="pre-wrap">${esc(JSON.stringify(tool.input).slice(0, 600))}</span>`;
    if (text) out += (out ? '<br>' : '') + mdRender(text).slice(0, 8000);
    content = out || esc(JSON.stringify(ev).slice(0, 300));
  } else if (t === 'user') {
    const msg = ev.message || {};
    const blocks = msg.content || [];
    const text = blocks.filter((x) => typeof x === 'string').join(' ');
    let out = blocks
      .filter((x) => x && x.type === 'tool_result')
      .map((c) => {
        const errCls = c.is_error ? ' tool-error' : '';
        return `<span class="pre-wrap${errCls}">${c.is_error ? '（错误）' : ''}${esc(String(c.content).slice(0, 400))}</span>`;
      })
      .join('<br>');
    if (text) out += (out ? '<br>' : '') + mdRender(text).slice(0, 3000);
    content = out || esc(JSON.stringify(ev).slice(0, 300));
  } else if (t === 'tool_use') {
    content = `🔧 <code>${esc(ev.name || 'tool')}</code><span class="pre-wrap"> ${esc(JSON.stringify(ev.input || {}).slice(0, 600))}</span>`;
  } else if (t === 'tool_result') {
    const errCls = ev.is_error ? ' tool-error' : '';
    content = `<span class="pre-wrap${errCls}">${ev.is_error ? '（错误）' : ''}${esc(String(ev.content || '').slice(0, 400))}</span>`;
  } else if (t === 'result') {
    content = `🏁 <span class="pre-wrap">${mdRender(String(ev.result || '')).slice(0, 4000)}</span>（turns: ${ev.num_turns ?? '?'}）`;
  } else if (t === 'error') {
    content = `💥 ${esc(ev.error || '异常终止')}${ev.exit_code != null ? `（exit_code: ${ev.exit_code}）` : ''}`;
  } else if (t === 'stderr') {
    content = `⚠ <span class="pre-wrap">${esc(ev.line || '')}</span>`;
  } else if (t === 'system') {
    const merged = ev._merged && ev._merged > 1 ? `（合并 ${ev._merged} 条）` : '';
    content = `⚙ 系统: ${esc(ev.subtype || '')}${merged}`;
  } else {
    content = esc(JSON.stringify(ev).slice(0, 300));
  }
  return `<div class="run-event ${cls}"><span class="pre-wrap">${content}</span></div>`;
}

// 合并连续的系统 thinking_tokens 事件为一条（如逐条递增的 token 统计）
function collapseThinkingTokens(events) {
  const out = [];
  let count = 0;
  for (const ev of events) {
    if (ev && ev.type === 'system' && ev.subtype === 'thinking_tokens') {
      count++;
      if (count === 1) out.push({ ...ev, _merged: count });
      continue;
    }
    if (count > 1 && out.length) out[out.length - 1]._merged = count;
    count = 0;
    out.push(ev);
  }
  if (count > 1 && out.length) out[out.length - 1]._merged = count;
  return out;
}

// ── RunView: FlowToken 驱动的运行记录 React 视图 ──────────
let __runModalRoot = null;
let __runModalRootEl = null;

function runEventElement(React, ev) {
  const t = ev.type;
  const cls =
    t === 'assistant' ? 'assistant' :
    t === 'user' ? 'user' :
    t === 'tool_use' ? 'tool' :
    t === 'tool_result' ? 'tool-result' :
    t === 'error' ? 'error' :
    t === 'stderr' ? 'stderr' :
    t === 'result' ? 'assistant' : '';

  let content;
  const AM = window.FlowToken?.AnimatedMarkdown;

  if (t === 'assistant') {
    const msg = ev.message || {};
    const blocks = msg.content || [];
    const text = blocks.filter((c) => c && c.type === 'text').map((c) => c.text).join(' ');
    const tool = blocks.find((c) => c && c.type === 'tool_use');
    const parts = [];
    if (tool) {
      parts.push(React.createElement('div', { key: 'tool', className: 'run-inline-tool' },
        '🔧 ',
        React.createElement('code', null, tool.name || 'tool'),
        ' ',
        React.createElement('span', { className: 'pre-wrap' }, JSON.stringify(tool.input).slice(0, 600))
      ));
    }
    if (text) {
      if (AM) {
        parts.push(React.createElement('div', { key: 'md', className: 'flowtoken-md' },
          React.createElement(AM, { content: text, animation: null })
        ));
      } else {
        parts.push(React.createElement('div', { key: 'md', className: 'md', dangerouslySetInnerHTML: { __html: mdRender(text) } }));
      }
    }
    if (!parts.length) {
      parts.push(React.createElement('span', { className: 'pre-wrap' }, esc(JSON.stringify(ev).slice(0, 300))));
    }
    content = parts;
  } else if (t === 'user') {
    const msg = ev.message || {};
    const blocks = msg.content || [];
    const text = blocks.filter((x) => typeof x === 'string').join(' ');
    const parts = [];
    const toolResults = blocks.filter((x) => x && x.type === 'tool_result');
    if (toolResults.length) {
      toolResults.forEach((c, i) => {
        const errCls = c.is_error ? ' tool-error' : '';
        parts.push(React.createElement('span', { key: 'tr' + i, className: 'pre-wrap' + errCls },
          (c.is_error ? '（错误）' : '') + String(c.content).slice(0, 400)
        ));
      });
    }
    if (text) {
      if (AM) {
        parts.push(React.createElement('div', { key: 'md', className: 'flowtoken-md' },
          React.createElement(AM, { content: text, animation: null })
        ));
      } else {
        parts.push(React.createElement('div', { key: 'md', dangerouslySetInnerHTML: { __html: mdRender(text) } }));
      }
    }
    if (!parts.length) {
      parts.push(React.createElement('span', { className: 'pre-wrap' }, esc(JSON.stringify(ev).slice(0, 300))));
    }
    content = parts;
  } else if (t === 'tool_use') {
    content = React.createElement('span', { className: 'pre-wrap' },
      '🔧 ',
      React.createElement('code', null, ev.name || 'tool'),
      ' ' + JSON.stringify(ev.input || {}).slice(0, 600)
    );
  } else if (t === 'tool_result') {
    const errCls = ev.is_error ? ' tool-error' : '';
    content = React.createElement('span', { className: 'pre-wrap' + errCls },
      (ev.is_error ? '（错误）' : '') + String(ev.content || '').slice(0, 400)
    );
  } else if (t === 'result') {
    const resultText = String(ev.result || '');
    const turns = ev.num_turns ?? '?';
    content = React.createElement('span', null,
      '🏁 ',
      AM
        ? React.createElement('span', { className: 'flowtoken-md' },
            React.createElement(AM, { content: resultText, animation: null })
          )
        : React.createElement('span', { dangerouslySetInnerHTML: { __html: mdRender(resultText) } }),
      `（turns: ${turns}）`
    );
  } else if (t === 'error') {
    content = `💥 ${ev.error || '异常终止'}${ev.exit_code != null ? `（exit_code: ${ev.exit_code}）` : ''}`;
  } else if (t === 'stderr') {
    content = React.createElement('span', { className: 'pre-wrap' }, '⚠ ' + (ev.line || ''));
  } else if (t === 'system') {
    const merged = ev._merged && ev._merged > 1 ? `（合并 ${ev._merged} 条）` : '';
    content = `⚙ 系统: ${ev.subtype || ''}${merged}`;
  } else {
    content = esc(JSON.stringify(ev).slice(0, 300));
  }

  return React.createElement('div', { className: 'run-event ' + cls, key: ev._key || null },
    React.createElement('span', { className: 'pre-wrap' }, typeof content === 'string' ? content : content)
  );
}

function RunView(React, props) {
  const events = collapseThinkingTokens(props.events || []);
  const tail = events.slice(-300);
  const elements = tail.map((ev, i) => {
    ev._key = i;
    return runEventElement(React, ev);
  });
  if (props.status === 'error' && props.error) {
    elements.unshift(runEventElement(React, { ...props.error, _key: 'err' }));
  }
  const total = (props.events || []).length;
  return React.createElement('div', null,
    React.createElement('div', { className: 'runmodal-scroll' }, elements),
    React.createElement('div', { className: 'kv-row' },
      React.createElement('span', { className: 'k' }, `共 ${total} 条事件`)
    )
  );
}

function mountRunModalRoot(body) {
  const React = window.FlowToken?.React;
  const ReactDOM = window.FlowToken?.ReactDOM;
  if (!React || !ReactDOM) return null;
  if (__runModalRoot && __runModalRootEl === body) return __runModalRoot;
  unmountRunModalRoot();
  __runModalRootEl = body;
  __runModalRoot = ReactDOM.createRoot(body);
  return __runModalRoot;
}

function unmountRunModalRoot() {
  if (__runModalRoot && __runModalRootEl) {
    try { __runModalRoot.unmount(); } catch (e) { /* ignore */ }
  }
  __runModalRoot = null;
  __runModalRootEl = null;
}

function renderRunModalBody(d) {
  const raw = d.events || [];
  const events = collapseThinkingTokens(raw);
  const html = events.slice(-300).map(runEventMd).join('');
  const err = d.status === 'error' && d.error ? runEventMd(d.error) : '';
  return `<div class="runmodal-scroll">${err}${html}</div>
    <div class="kv-row"><span class="k">共 ${raw.length} 条事件</span></div>`;
}

// ── 运行时间轴（react-vertical-timeline，垂直） ────────
function renderTimeline(d) {
  const tl = d.timeline || [];
  if (!tl.length) return '';
  window.__tlData = d;   // 供 mountTimeline 读取（React 需在 DOM 就位后挂载）
  return `
  <div class="section">
    <div class="section-title">运行时间轴<span class="count">${tl.length}</span></div>
    <div class="card no-hover">
      <div id="tl-root"></div>
      <div class="tl-hint">🖱 点击节点查看运行记录（80% 弹窗） · ↩ 状态回退（附原因）</div>
    </div>
  </div>`;
}

function mountTimeline() {
  const rootEl = document.getElementById('tl-root');
  if (!rootEl) return;
  const d = window.__tlData;
  if (!d || !window.FenixReact || !window.VerticalTimeline) return;
  const React = window.FenixReact;
  const VT = window.VerticalTimeline;
  const VTE = window.VerticalTimelineElement;
  const tl = d.timeline || [];
  const nodes = tl.map((e, i) => {
    const pos = i % 2 === 0 ? 'left' : 'right';
    const arrow = { borderRight: '7px solid var(--surface)' };
    if (e.kind === 'state') {
      const back = !!e.reason;
      const icon = React.createElement('span', { className: 'tl-ico' }, back ? '↩' : '·');
      const content = React.createElement('div', null,
        React.createElement('div', { className: 'tl-state-label' }, `${e.from} → ${e.to}`),
        back
          ? React.createElement('div', { className: 'tl-reason' }, '↩ ' + (e.reason || '状态回退'))
          : null);
      return React.createElement(VTE, {
        key: 's' + i, date: fmtTime(e.time), position: pos, animate: false,
        icon: icon,
        iconStyle: back ? { background: '#ec835a', color: '#0d0d0d' } : { background: '#3987e5', color: '#fff' },
        contentStyle: back ? { background: 'var(--surface)', borderTop: '3px solid #ec835a' } : { background: 'var(--surface)' },
        contentArrowStyle: arrow,
      }, content);
    }
    const st = e.status;
    const color = st === 'error' ? '#d03b3b' : (st === 'running' || st === 'empty') ? '#fab219' : '#199e70';
    const iconChar = st === 'error' ? '✕' : (st === 'running' || st === 'empty') ? '…' : '✓';
    const dur = e.duration_seconds != null ? fmtDuration(e.duration_seconds) : '';
    // fix-* SPEC 的运行：显示实际 spec 名，避免与父 SPEC 混淆
    const isFix = e.spec && String(e.spec).startsWith('fix-');
    const content = React.createElement('div', null,
      React.createElement('div', { className: 'tl-run-head' },
        React.createElement('span', { className: 'tl-run-type' }, e.agent_type),
        React.createElement('span', { className: 'tl-run-status', style: { color: color } }, st),
        isFix ? React.createElement('span', { className: 'tl-run-spec' }, '🔧 ' + e.spec) : null),
      dur ? React.createElement('div', { className: 'tl-run-dur' }, '耗时：' + dur) : null,
      React.createElement('button', {
        className: 'tl-btn', onClick: () => openRunModal({ project: d.project, spec: d.name, runId: e.run_id }),
      }, '查看运行记录'));
    return React.createElement(VTE, {
      key: 'r' + i, date: fmtTime(e.time), position: pos, animate: false,
      icon: React.createElement('span', { className: 'tl-ico' }, iconChar),
      iconStyle: { background: color, color: '#0d0d0d' },
      contentStyle: { background: 'var(--surface)', borderTop: '3px solid ' + color },
      contentArrowStyle: arrow,
    }, content);
  });
  const tree = React.createElement(VT, { lineColor: '#55544d', animate: false }, nodes);
  if (window.__tlRoot && window.__tlRootEl === rootEl) {
    window.__tlRoot.render(tree);   // 复用 root：React 只更新变化节点，时间轴不抖动
  } else {
    window.__tlRootEl = rootEl;
    window.__tlRoot = window.FenixReactDOM.createRoot(rootEl);
    window.__tlRoot.render(tree);
  }
}

// ── 运行记录弹窗（80% 屏） ─────────────────────────────
let runModalPoll = null;   // 运行记录弹窗的流式轮询定时器

function isRunLive(status) {
  return status === 'running' || status === 'empty';
}

function stopRunModalPoll() {
  if (runModalPoll) { clearInterval(runModalPoll); runModalPoll = null; }
}

function renderRunModalBodyLive(body, d) {
  // 粘性滚动：更新前贴近底部则更新后自动滚到最新；用户上翻阅读历史时不强制拽回
  const nearBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 80;
  const React = window.FlowToken?.React;
  const root = mountRunModalRoot(body);
  if (root && React) {
    root.render(RunView(React, {
      events: d.events || [],
      status: d.status,
      error: d.error,
    }));
  } else {
    body.innerHTML = renderRunModalBody(d);
  }
  if (nearBottom) body.scrollTop = body.scrollHeight;
}

function openRunModal(payload) {
  stopRunModalPoll();
  unmountRunModalRoot();
  const box = el('runmodal');
  const body = el('runmodal-body');
  if (payload && payload.runId) {
    el('runmodal-title').textContent = payload.runId;
    body.innerHTML = '<div class="empty-state">加载中…</div>';
    box.classList.remove('hidden');
    const runId = payload.runId;
    const project = payload.project || '';
    const fetchRun = () => {
      api('/api/runs/' + encodeURIComponent(runId) + '?project=' + encodeURIComponent(project))
        .then((d) => {
          if (box.classList.contains('hidden')) { stopRunModalPoll(); return; }
          renderRunModalBodyLive(body, d);
          if (!isRunLive(d.status)) stopRunModalPoll();   // 运行结束即停止轮询
        })
        .catch(() => {});
    };
    fetchRun();
    runModalPoll = setInterval(fetchRun, 1000);   // 1s 流式轮询
  } else if (payload && payload.state) {
    const st = payload.state;
    el('runmodal-title').textContent = `状态转换 ${st.from} → ${st.to}`;
    body.innerHTML = `
      <div class="kv-row"><span class="k">从</span><span class="v">${esc(st.from)}</span></div>
      <div class="kv-row"><span class="k">到</span><span class="v">${esc(st.to)}</span></div>
      ${st.reason ? `<div class="kv-row"><span class="k">原因</span><span class="v">${esc(st.reason)}</span></div>` : ''}
      ${st.reason ? `<div class="verdict env">↩ 状态回退：${esc(st.reason)}</div>` : ''}
      <div class="kv-row"><span class="k">说明</span><span class="v">这是 SPEC 生命周期中的一次状态转换${st.reason ? '，因验证发现问题等原因被回退' : ''}。</span></div>`;
    box.classList.remove('hidden');
  }
}
function closeRunModal() {
  stopRunModalPoll();
  unmountRunModalRoot();
  el('runmodal').classList.add('hidden');
  el('runmodal-body').innerHTML = '';
}
el('runmodal').addEventListener('click', (e) => { if (e.target === el('runmodal')) closeRunModal(); });
el('runmodal-close').addEventListener('click', closeRunModal);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeRunModal(); });

// ── 配置页 ─────────────────────────────────────────────

const KNOWN_AGENT_TYPES = [
  { key: 'implementer', label: 'Implementer（执行）' },
  { key: 'planner-plan', label: 'Planner Plan（生成场景）' },
  { key: 'planner-judge', label: 'Planner Judge（判定结果）' },
  { key: 'verifier', label: 'Verifier（旧版验证）' },
];

function renderConfig(data) {
  const project = esc(data.project || '');
  const llm = data.llm || {};
  const providers = llm.providers || [];
  const agents = data.agents || {};
  const models = agents.models || {};
  const gates = data.gates || {};
  const approveMode = gates.approve_mode || 'manual';
  const error = data.error || '';
  const hasConfig = data.raw_exists;

  return `
  <div class="config-page">
    <div class="page-title">配置管理${project ? ' · ' + project : ''}</div>
    <div class="page-sub">
      修改后需重启 daemon 生效。配置文件位于 <code>.fenix/config.yaml</code>。
      ${hasConfig ? '' : '<span class="status-pill st-warning">⚠ 项目尚无配置文件</span>'}
    </div>
    ${error ? `<div class="config-error">⚠ ${esc(error)}</div>` : ''}

    <div id="config-save-banner" class="config-banner hidden"></div>

    <div class="config-section">
      <h3>🤖 LLM Provider 列表</h3>
      <p class="section-hint">定义可用的 LLM 提供者（baseurl / apikey / 默认模型）。</p>
      <div id="provider-list" class="provider-list">
        ${providers.map((p, i) => renderProviderCard(p, i)).join('')}
      </div>
      <button class="btn btn-secondary" id="btn-add-provider">+ 新增 Provider</button>
    </div>

    <div class="config-section">
      <h3>🧩 Agent 模型分配</h3>
      <p class="section-hint">为每种 Agent 角色分配 Provider 与模型。未分配的角色使用默认模型。</p>
      <div class="agent-assign-grid">
        ${KNOWN_AGENT_TYPES.map((at) => renderAgentAssignment(at, providers, models)).join('')}
      </div>
    </div>

    <div class="config-section">
      <h3>⚡ 并行度设置</h3>
      <p class="section-hint">
        同时运行的 Agent 进程数上限。调度采用<strong>严格优先级并行</strong>：
        高优先级任务先执行；同一优先级内可并行至该上限；
        不同优先级不并行（低优先级等高优先级全部完成后才启动）。
      </p>
      <div class="form-row">
        <label>并行度（agents.max_concurrent）</label>
        <input type="number" id="cfg-max-concurrent" min="1" step="1"
          value="${esc(agents.max_concurrent ?? 2)}" />
        <small>默认 2。修改后需重启 daemon 生效。</small>
      </div>
    </div>

    <div class="config-section">
      <h3>🚪 审批模式</h3>
      <p class="section-hint">
        SPEC 到达 done 后的行为。<strong>auto 模式将自动执行 git push 到远端</strong>，请谨慎使用。
      </p>
      <div class="approve-mode-row">
        <label class="radio-item">
          <input type="radio" name="approve_mode" value="manual" ${approveMode === 'manual' ? 'checked' : ''} />
          <span><strong>manual</strong> — 人工审批（默认）</span>
          <small>SPEC 完成后停留在 done，等待 /fenix-approve 人工推送。</small>
        </label>
        <label class="radio-item">
          <input type="radio" name="approve_mode" value="auto" ${approveMode === 'auto' ? 'checked' : ''} />
          <span><strong>auto</strong> — 自动推送</span>
          <small class="auto-warn">⚠ SPEC 完成后 daemon 自动执行 <code>git push origin fenix/&lt;spec&gt;</code>。</small>
        </label>
      </div>
    </div>

    <div class="config-actions">
      <button class="btn btn-primary" id="btn-save-config">💾 保存配置</button>
      <span class="config-note">保存后需重启 daemon 生效</span>
    </div>
  </div>`;
}

function renderEnvRow(k, v) {
  return `
    <div class="env-row">
      <input type="text" class="env-key" placeholder="参数名（如 CLAUDE_CODE_MAX_CONTEXT_TOKENS）"
        value="${esc(k)}" />
      <input type="text" class="env-value" placeholder="值（如 1000000）"
        value="${esc(v)}" />
      <button type="button" class="btn btn-ghost btn-danger" data-action="remove-env" title="删除此参数">✕</button>
    </div>`;
}
function renderEnvRows(env) {
  return Object.entries(env || {}).map(([k, v]) => renderEnvRow(k, v)).join('');
}

function renderProviderCard(p, idx) {
  return `
  <div class="provider-card" data-idx="${idx}">
    <div class="provider-head">
      <input type="text" class="provider-name" placeholder="Provider 名称（如 volc-engine）"
        value="${esc(p.name || '')}" data-field="name" />
      <button class="btn btn-ghost btn-danger" data-action="remove-provider" data-idx="${idx}">删除</button>
    </div>
    <div class="provider-fields">
      <div class="form-row">
        <label>Base URL</label>
        <input type="text" placeholder="https://api.example.com/v1"
          value="${esc(p.baseurl || '')}" data-field="baseurl" />
      </div>
      <div class="form-row">
        <label>API Key</label>
        <input type="password" placeholder="sk-..."
          value="${esc(p.apikey || '')}" data-field="apikey" />
      </div>
      <div class="form-row">
        <label>默认模型名</label>
        <input type="text" placeholder="deepseek-v4-flash"
          value="${esc(p.model || '')}" data-field="model" />
      </div>
      <div class="form-row">
        <label>SDK 校验模型名 <small>（可选，官方 Claude 模型名）</small></label>
        <input type="text" placeholder="claude-sonnet-5"
          value="${esc(p.sdk_model || '')}" data-field="sdk_model" />
      </div>
      <div class="form-row env-section">
        <label>自定义环境变量 <small>（选填，运行时注入子进程，如 CLAUDE_CODE_MAX_CONTEXT_TOKENS=1000000）</small></label>
        <div class="env-list">
          ${renderEnvRows(p.env)}
        </div>
        <button type="button" class="btn btn-ghost btn-add-env" data-action="add-env">+ 添加参数</button>
      </div>
    </div>
  </div>`;
}

function renderAgentAssignment(at, providers, models) {
  const assigned = models[at.key] || null;
  const providerName = assigned ? assigned.provider : '';
  const modelVal = assigned ? assigned.model : '';
  const providerOptions = providers.map((p) =>
    `<option value="${esc(p.name)}" ${p.name === providerName ? 'selected' : ''}>${esc(p.name)}</option>`
  ).join('');
  return `
  <div class="agent-assign-card" data-agent="${at.key}">
    <div class="agent-label">${esc(at.label)}</div>
    <div class="agent-assign-controls">
      <label class="assign-toggle">
        <input type="checkbox" class="assign-enabled" ${assigned ? 'checked' : ''}
          data-agent="${at.key}" />
        <span>分配模型</span>
      </label>
      <div class="assign-fields ${assigned ? '' : 'disabled'}" data-agent="${at.key}">
        <select class="assign-provider" data-agent="${at.key}">
          <option value="">-- 选择 Provider --</option>
          ${providerOptions}
        </select>
        <input type="text" class="assign-model" placeholder="模型名（如 deepseek-v4-flash）"
          value="${esc(modelVal)}" data-agent="${at.key}" />
      </div>
    </div>
  </div>`;
}

// ── 配置页交互 ─────────────────────────────────────────

let configInitialized = false;

function hydrateConfigPage() {
  if (currentState.view !== 'config') return;
  if (configInitialized) return;

  // 新增 Provider
  const addBtn = el('btn-add-provider');
  if (addBtn) {
    addBtn.addEventListener('click', () => {
      const list = el('provider-list');
      if (!list) return;
      const newIdx = list.querySelectorAll('.provider-card').length;
      const div = document.createElement('div');
      div.innerHTML = renderProviderCard({ name: '', baseurl: '', apikey: '', model: '' }, newIdx);
      list.appendChild(div.firstElementChild);
      reindexProviders();
    });
  }

  // 事件委托：Provider 删除 / 自定义环境变量增删
  const main = el('main');
  main.addEventListener('click', (e) => {
    const t = e.target;
    if (t.matches('[data-action="remove-provider"]')) {
      const idx = parseInt(t.dataset.idx, 10);
      const cards = main.querySelectorAll('.provider-card');
      if (cards[idx]) cards[idx].remove();
      reindexProviders();
    } else if (t.matches('[data-action="add-env"]')) {
      const list = t.closest('.provider-card')?.querySelector('.env-list');
      if (list) {
        const div = document.createElement('div');
        div.innerHTML = renderEnvRow('', '');
        list.appendChild(div.firstElementChild);
      }
    } else if (t.matches('[data-action="remove-env"]')) {
      const row = t.closest('.env-row');
      if (row) row.remove();
    }
  });

  // 分配开关切换
  main.addEventListener('change', (e) => {
    const t = e.target;
    if (t.classList.contains('assign-enabled')) {
      const agentKey = t.dataset.agent;
      const fields = main.querySelector(`.assign-fields[data-agent="${agentKey}"]`);
      if (fields) fields.classList.toggle('disabled', !t.checked);
    }
  });

  // 保存按钮
  const saveBtn = el('btn-save-config');
  if (saveBtn) {
    saveBtn.addEventListener('click', saveConfig);
  }

  configInitialized = true;
}

function reindexProviders() {
  const cards = document.querySelectorAll('.provider-card');
  cards.forEach((card, i) => {
    card.dataset.idx = i;
    const removeBtn = card.querySelector('[data-action="remove-provider"]');
    if (removeBtn) removeBtn.dataset.idx = i;
  });
}

function collectConfigData() {
  const main = el('main');
  // Providers
  const providerCards = main.querySelectorAll('.provider-card');
  const providers = [];
  providerCards.forEach((card) => {
    const p = {};
    card.querySelectorAll('input[data-field]').forEach((inp) => {
      const field = inp.dataset.field;
      const val = inp.value.trim();
      if (val) p[field] = val;
    });
    // 自定义环境变量（仅收键值都非空的行）
    const env = {};
    card.querySelectorAll('.env-row').forEach((row) => {
      const k = row.querySelector('.env-key').value.trim();
      const v = row.querySelector('.env-value').value.trim();
      if (k && v) env[k] = v;
    });
    if (Object.keys(env).length > 0) p.env = env;
    providers.push(p);
  });

  // Agent models
  const models = {};
  KNOWN_AGENT_TYPES.forEach((at) => {
    const toggle = main.querySelector(`.assign-enabled[data-agent="${at.key}"]`);
    if (!toggle || !toggle.checked) return;
    const providerSel = main.querySelector(`.assign-provider[data-agent="${at.key}"]`);
    const modelInp = main.querySelector(`.assign-model[data-agent="${at.key}"]`);
    const provider = providerSel ? providerSel.value : '';
    const model = modelInp ? modelInp.value.trim() : '';
    if (provider && model) {
      models[at.key] = { provider, model };
    }
  });

  // Max concurrent (parallelism)
  const maxConcurrentInput = main.querySelector('#cfg-max-concurrent');
  const maxConcurrent = maxConcurrentInput ? parseInt(maxConcurrentInput.value, 10) : 2;

  // Approve mode
  const approveMode = (main.querySelector('input[name="approve_mode"]:checked') || {}).value || 'manual';

  return {
    llm: { providers },
    agents: { models, max_concurrent: maxConcurrent },
    gates: { approve_mode: approveMode },
  };
}

function saveConfig() {
  const banner = el('config-save-banner');
  const saveBtn = el('btn-save-config');
  const project = encodeURIComponent(currentState.project || '');
  const payload = collectConfigData();

  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.textContent = '保存中…';
  }
  if (banner) banner.className = 'config-banner hidden';

  fetch('/api/config?project=' + project, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
    .then((r) => {
      if (!r.ok) return r.json().then((d) => { throw new Error(d.error || 'HTTP ' + r.status); });
      return r.json();
    })
    .then(() => {
      if (banner) {
        banner.className = 'config-banner success';
        banner.textContent = '✅ 配置已保存，重启 daemon 后生效';
      }
      // 重新加载一次以确认
      load();
    })
    .catch((err) => {
      if (banner) {
        banner.className = 'config-banner error';
        banner.textContent = '❌ 保存失败：' + err.message;
      }
    })
    .finally(() => {
      if (saveBtn) {
        saveBtn.disabled = false;
        saveBtn.textContent = '💾 保存配置';
      }
    });
}

// 在每次视图渲染后尝试绑定配置页交互
const _origRenderView = renderView;
function renderViewWithHydration(state, data) {
  _origRenderView(state, data);
  if (state.view === 'config') {
    // 延迟到下一帧，确保 morphdom 已完成 DOM 更新
    requestAnimationFrame(() => {
      hydrateConfigPage();
      // 首次进入配置页，从项目列表自动选一个项目
      if (!currentState.project) {
        const sel = el('project-select');
        if (sel && sel.options.length > 0) {
          const first = sel.options[0].value;
          if (first) nav('config/' + encodeURIComponent(first));
        }
      }
    });
  }
}
// 替换 renderView 引用（renderView 已在多处被调用，这里只在调度层替换）
// 实际渲染仍走 renderView，hydrateConfigPage 在 load 回调的 hydratePending 中触发

// 在 hydratePending 中加入配置页绑定
const _origSchedulePoll = schedulePoll;

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
window.openRunModal = openRunModal;

// ── 启动 ───────────────────────────────────────────────
route();
