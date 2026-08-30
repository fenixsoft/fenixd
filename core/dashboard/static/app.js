/* Fenix Dashboard — 原生 JS 单页应用（无 CDN）
   视图: #overview（跨项目概览） / #project/<name>（SPEC 列表） / #spec/<proj>/<spec>（详情）
   数据: 服务端 FileWatcher 监听数据源文件，经 SSE（/api/stream）推送变更，前端不轮询。
   run 对话流（LLM 事件）仅在展开/弹窗时按需拉取尾部 + SSE 增量。 */

const el = (id) => document.getElementById(id);
const $ = (sel, root) => (root || document).querySelector(sel);

// ── 工具 ────────────────────────────────────────────────
function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function api(path, options) {
  return fetch(path, options || {}).then((r) => {
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
  blocked: { cls: 'st-critical', icon: '🛑', label: '阻塞' },
  done: { cls: 'st-good', icon: '🎯', label: '完成' },
  pushed: { cls: 'st-good', icon: '🚀', label: '已推送' },
};
function statusPill(status) {
  const m = STATUS_META[status] || { cls: 'st-muted', icon: '❓', label: status || '未知' };
  return `<span class="status-pill ${m.cls}">${m.icon} ${esc(m.label)}</span>`;
}
// daemon 健康徽标：running → 「运行中」（正向色），stopped → 「未运行」（警示色）
function daemonBadge(daemon) {
  if (daemon === 'running') {
    return `<span class="status-pill daemon-pill st-good" title="fenixd daemon 运行中">运行中</span>`;
  }
  if (daemon === 'stopped') {
    return `<span class="status-pill daemon-pill st-warning" title="fenixd daemon 未运行">未运行</span>`;
  }
  return '';
}
function progressBar(done, total) {
  const p = pct(done, total);
  const cls = p === 100 ? 'good' : p >= 60 ? '' : p > 0 ? 'warn' : 'serious';
  return `<div class="progress ${cls}"><div class="fill" style="width:${p}%"></div></div>
    <div class="progress-labels"><span>${done}/${total}</span><span>${p}%</span></div>`;
}
// 非阻塞轻提示（成功/错误）：复用 .toast-error 样式（见 style.css），成功态加 .toast-ok
function toast(msg, isError) {
  const t = document.createElement('div');
  t.className = 'toast-error' + (isError ? '' : ' toast-ok');
  t.textContent = msg;
  document.body.appendChild(t);
  // 成功提示略短于错误提示，但保留足够时长以便用户感知/被断言捕获
  // （菜单关闭等交互会占用约 3s，过短会在断言前被移除，误判为未提示）。
  setTimeout(() => t.remove(), isError ? 6000 : 5000);
}

// ── 路由与状态 ──────────────────────────────────────────
let currentState = { view: 'overview' };
let seq = 0;
const specFilter = { q: '', status: '', type: '' };  // 项目视图过滤状态，跨刷新保持；type: '' 全部 / 'req' 仅需求 / 'issue' 仅问题
let activitiesTab = 'all';  // 运维记录跨项目视图的页签：'all' 或项目名（跨刷新保持）
let specSort = { key: '', dir: '' };  // 概览表格排序状态：key/dir(asc|desc|'')，跨刷新保持
let specTab = 'timeline';  // spec 详情页页签：timeline|scenarios|bugs|screenshots，跨刷新保持

function parseHash() {
  const h = decodeURIComponent(location.hash.slice(1) || 'overview');
  const parts = h.split('/');
  if (parts[0] === 'project' && parts[1]) return { view: 'project', project: parts[1] };
  if (parts[0] === 'spec' && parts[1] && parts[2]) {
    return { view: 'spec', project: parts[1], spec: parts[2] };
  }
  if (parts[0] === 'config' || h.startsWith('config=')) {
    // config/<project>、config=<project>（项目级配置，等号形式兼容直接导航）
    // 或 config（无项目则用户级）
    const proj = parts[1] || '';
    const eqMatch = h.match(/^config=(.+)$/);
    // 可选 tab 深链：#config=fenixd&tab=agent-models / #config/fenixd?tab=agent-models
    // （improve-failover-model-mapping-ui：直接进入 Agent 模型分配页，避免链编辑器
    //  被默认隐藏的 tab 挡住；验证场景与直接分享链接均受益）。
    let tab = '';
    const amp = (eqMatch ? eqMatch[1] : proj).match(/&tab=([\w-]+)/);
    if (amp) tab = amp[1];
    const q = h.match(/[?&]tab=([\w-]+)/);
    if (q) tab = q[1];
    const projClean = proj
      ? proj.replace(/[?&]tab=[\w-]+/, '')
      : (eqMatch ? eqMatch[1].replace(/&tab=[\w-]+/, '') : '');
    return { view: 'config', project: projClean, tab };
  }
  if (parts[0] === 'activities') {
    // activities/<project>（无项目 → 跨项目聚合）
    return { view: 'activities', project: parts[1] || '' };
  }
  return { view: 'overview' };
}
function nav(hash) {
  if ('#' + hash === location.hash) route();
  else location.hash = hash;
}
function route() {
  currentState = parseHash();
  updateTopbar();
  load();
  loadAlerts();
}

// ── 数据获取 ────────────────────────────────────────────
// spec 详情只含 run 元数据（状态/时长），不含事件流；事件流由弹窗按需拉取。
function fetchFor(state) {
  const p = encodeURIComponent(state.project || '');
  if (state.view === 'overview') return api('/api/overview');
  if (state.view === 'project') return api('/api/specs?project=' + p);
  if (state.view === 'config') return api('/api/config?project=' + p);
  if (state.view === 'activities') return api('/api/admin-activities?project=' + p);
  const s = encodeURIComponent(state.spec);
  return api('/api/specs/' + s + '?project=' + p);
}

function load() {
  const mySeq = ++seq;
  fetchFor(currentState)
    .then((data) => {
      if (mySeq !== seq) return;
      const scrollY = window.scrollY;
      renderView(currentState, data);
      window.scrollTo(0, scrollY);
      if (currentState.view === 'config') hydrateConfigPage();
      if (currentState.view === 'project') hydrateProjectFilter();
    })
    .catch((err) => {
      if (mySeq !== seq) return;
      showError(err);
    });
}

// ── SSE 推送订阅（服务端 FileWatcher 监听文件变更 → 推送，替代轮询） ──
let sse = null;
let sseCid = null;            // 本页 SSE 连接 id（注册 run 增量订阅用）
const pendingWatches = [];    // 尚未拿到 cid 时的待注册 run
let lastRefresh = 0;

function refreshView() {
  if (currentState.view === 'config') return;   // 配置页表单编辑中，不整页重绘
  const now = Date.now();
  if (now - lastRefresh < 500) return;   // 前缘节流：突发事件合并为一次刷新
  lastRefresh = now;
  load();
}

function handleSSEEvent(msg) {
  if (msg.type === 'state') {
    // 概览聚合所有项目，任何项目变化都整体重拉
    if (currentState.view === 'overview') { refreshView(); return; }
    if (msg.project !== currentState.project) return;
    if (currentState.view === 'project' && msg.specs) {
      renderView(currentState, { project: currentState.project, specs: msg.specs });
    } else if (currentState.view === 'spec') {
      const d = msg.details && msg.details[currentState.spec];
      if (d) renderView(currentState, d);
      else refreshView();   // 不在推送详情里 → 回退到一次 REST 拉取
    }
    return;
  }
  if (msg.type === 'detail') {
    if (currentState.view !== 'spec') return;
    if (msg.project !== currentState.project || msg.spec !== currentState.spec) return;
    renderView(currentState, msg.data);
    return;
  }
  if (msg.type === 'run_meta') {
    refreshView();
    return;
  }
  if (msg.type === 'refresh') {
    // 周期心跳：daemon 状态/新项目发现不产生文件变更，仅概览需自动重拉跟随
    if (currentState.view === 'overview') refreshView();
    return;
  }
  if (msg.type === 'run_events' && modalRunId === msg.run_id) {
    appendModalEvents(msg);
  }
  if (msg.type === 'run_events' && modalAdminSpec && modalAdminRunId === msg.run_id) {
    appendAdminEvents(msg);
  }
  if (msg.type === 'alerts') {
    // 告警标记已处理 / 新告警写入 → 刷新横幅；运维记录页同步刷新
    loadAlerts();
    if (currentState.view === 'activities') refreshView();
  }
  if (msg.type === 'admin_activities') {
    // add-admin-invoke-dialog v2：Admin 处置记录（含 pending disposition）变更 →
    // 仅当弹窗打开且 project 匹配时重拉该 SPEC 记录；fetchAdminActivities 内部负责
    // 解析 admin_run_id / 刷新顶部状态行 / 等待态切实时输出，关闭后忽略（与 run 弹窗一致）。
    if (modalAdminSpec && msg.project === modalAdminSpec.project) {
      fetchAdminActivities(modalAdminSpec.project, modalAdminSpec.spec);
    }
  }
}

function connectSSE() {
  if (sse) sse.close();
  sse = new EventSource('/api/stream');
  sse._firstOpen = true;
  sse.onopen = () => {
    // 首次连接 route() 已初始加载；重连（新 cid）则补拉当前视图 + 重订阅弹窗 run
    if (sse._firstOpen) { sse._firstOpen = false; return; }
    load();
    if (modalRunId) pendingWatches.push(modalRunId);
    // add-admin-invoke-dialog v2：SSE 断线重连后，若处置过程弹窗仍打开则补拉该 SPEC
    // 记录（run 已定位则重订阅增量；等待态则重拉解析，与首连同路径）。
    else if (modalAdminSpec) {
      if (modalAdminRunId) pendingWatches.push(modalAdminRunId);
      fetchAdminActivities(modalAdminSpec.project, modalAdminSpec.spec);
    }
  };
  sse.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch (e) { return; }
    if (msg.type === 'hello') {
      sseCid = msg.cid;
      while (pendingWatches.length) registerWatch(pendingWatches.shift());
      return;
    }
    handleSSEEvent(msg);
  };
  // onerror：EventSource 原生自动重连，无需手动处理
}

function registerWatch(runId) {
  if (!sseCid) { pendingWatches.push(runId); return; }
  fetch('/api/runs/' + encodeURIComponent(runId) + '/watch'
    + '?project=' + encodeURIComponent(currentState.project || '')
    + '&cid=' + encodeURIComponent(sseCid), { method: 'POST' }).catch(() => {});
}
function unregisterWatch(runId) {
  if (!sseCid) return;
  fetch('/api/runs/' + encodeURIComponent(runId) + '/watch'
    + '?project=' + encodeURIComponent(currentState.project || '')
    + '&cid=' + encodeURIComponent(sseCid), { method: 'DELETE' }).catch(() => {});
}

// ── 人工升级告警横幅（/api/alerts） ─────────────────────
function loadAlerts() {
  api('/api/alerts')
    .then((data) => {
      if (data && data.error) return;
      renderAlertBanner(data);
    })
    .catch(() => {});
}

function sevLabel(sev) {
  return ({ critical: '严重', major: '较高', minor: '一般' })[sev] || sev || '未知';
}
function sevRank(sev) {
  return ({ critical: 3, major: 2, minor: 1 })[sev] || 0;
}

function renderAlertBanner(data) {
  const banner = el('alert-banner');
  if (!banner) return;
  const alerts = (data && data.alerts) || [];
  const count = (data && data.total_unhandled) || alerts.length;
  if (count === 0 || alerts.length === 0) {
    banner.classList.add('hidden');
    banner.innerHTML = '';
    return;
  }
  // 重建前保留列表展开状态：标记已处理 / 新告警触发 loadAlerts 重建横幅时列表不收起。
  // 默认展开：告警项与「标记已处理」按钮须对管理员可见可处置，否则升级通道形同虚设。
  const oldList = el('alert-list');
  const expanded = !oldList || !oldList.classList.contains('hidden');
  const top = alerts.reduce((m, a) => (sevRank(a.severity) > sevRank(m.severity) ? a : m), alerts[0]);
  const latest = alerts[0];
  const listHtml = alerts.map(alertItemHtml).join('');

  banner.classList.remove('hidden');
  banner.innerHTML = `
    <div class="alert-banner-bar">
      <span class="alert-banner-title">⚠ 需人工介入</span>
      <span class="alert-banner-meta">${count} 条未处理</span>
      <span class="alert-sev-pill sev-${esc(top.severity || 'major')}">${sevLabel(top.severity)}</span>
      <span class="alert-banner-summary">${esc((latest.project ? '[' + latest.project + '] ' : '') + (latest.description || latest.action_taken || ''))}</span>
      <button id="alert-toggle" class="alert-toggle">${expanded ? '收起列表' : '展开列表'}</button>
      <button id="alert-clear-all" class="alert-clear-all">清理所有事件</button>
    </div>
    <div id="alert-list" class="alert-list${expanded ? '' : ' hidden'}">${listHtml}</div>`;
  // 注意：#alert-toggle / #alert-clear-all / .alert-handled-btn 的点击处理统一走
  // #alert-banner 上的事件委托（initAlertBanner 绑定一次），此处不再逐个重绑——
  // 防止重渲染后旧节点监听器丢失导致「展开失效」「标记已处理无反应」（见
  // fix-add-verify-report-gate Bug 3 / Bug 4 根因）。
}

function alertItemHtml(a) {
  const sev = a.severity || 'major';
  const proj = a.project ? `<span class="alert-item-proj">${esc(a.project)}</span>` : '';
  const spec = a.spec ? `<span class="alert-item-spec">${esc(a.spec)}</span>` : '';
  const time = a.created ? fmtDate(a.created) : '';
  const evidence = a.evidence ? `<div class="alert-item-evidence">证据：${esc(a.evidence)}</div>` : '';
  const action = a.action_taken ? `<div class="alert-item-action">处置：${esc(a.action_taken)}</div>` : '';
  const reco = a.recommended_action
    ? `<div class="alert-item-reco">建议：${esc(a.recommended_action)}</div>` : '';
  return `<div class="alert-item sev-${esc(sev)}">
    <div class="alert-item-head">
      <span class="alert-sev-pill sev-${esc(sev)}">${sevLabel(sev)}</span>${proj}${spec}
      <span class="alert-item-time">${esc(time)}</span>
      <button class="alert-handled-btn" data-project="${esc(a.project || '')}" data-id="${esc(a.id || '')}">标记已处理</button>
    </div>
    <div class="alert-item-desc">${esc(a.description || '')}</div>
    ${evidence}${action}${reco}
  </div>`;
}

function markAlertHandled(project, id) {
  if (!project || !id) return;
  // 乐观更新：先在前端隐藏该告警项（横幅仍显示剩余未处理计数），待 API 回写后
  // loadAlerts 重建横幅。修复 Bug 4——标记已处理依赖后端回写才能移除，而重渲染
  // 时序下列表未及时收缩，表现为「标记后告警仍在 DOM 中」。乐观移除让反馈即时。
  const banner = el('alert-banner');
  const item = banner && banner.querySelector('.alert-handled-btn[data-id="' + (window.CSS && CSS.escape ? CSS.escape(id) : id) + '"]');
  const row = item && item.closest('.alert-item');
  if (row) row.remove();
  api('/api/alerts/' + encodeURIComponent(id) + '/handled?project=' + encodeURIComponent(project),
    { method: 'POST' })
    .then(() => {
      loadAlerts();
      if (currentState.view === 'activities') load();
    })
    .catch(() => {
      // 失败：回滚乐观移除（重载横幅恢复该告警项）
      loadAlerts();
    });
}

// ── 告警横幅交互（事件委托，fix-add-verify-report-gate Bug 3/4） ──
// #alert-banner 是 index.html 中的常驻稳定节点，innerHTML 仅替换其内部子结构；
// 在此容器上做一次事件委托，避免每次 renderAlertBanner 重建后逐个重绑导致的
// 监听器丢失：
//   - #alert-toggle 点击 → toggle #alert-list 的 hidden（Bug 3 根因即旧逻辑重绑失败）
//   - #alert-clear-all 点击 → 清理所有未处理
//   - .alert-handled-btn 点击 → 标记单条已处理（Bug 4）
let _alertBannerBound = false;
function initAlertBanner() {
  if (_alertBannerBound) return;
  _alertBannerBound = true;
  const banner = el('alert-banner');
  if (!banner) return;
  banner.addEventListener('click', (e) => {
    const toggle = e.target.closest('#alert-toggle');
    if (toggle) {
      const list = el('alert-list');
      if (list) {
        list.classList.toggle('hidden');
        toggle.textContent = list.classList.contains('hidden') ? '展开列表' : '收起列表';
      }
      return;
    }
    if (e.target.closest('#alert-clear-all')) {
      if (!confirm('确认将所有未处理事件标记为已处理？')) return;
      api('/api/alerts/clear', { method: 'POST' })
        .then(() => {
          loadAlerts();
          if (currentState.view === 'activities') load();
        })
        .catch(() => {});
      return;
    }
    const handled = e.target.closest('.alert-handled-btn');
    if (handled) {
      markAlertHandled(handled.dataset.project, handled.dataset.id);
    }
  });
}

// ── 运维记录（/api/admin-activities） ──────────────────
const RESULT_META = {
  resolved: { cls: 'st-good', icon: '✅', label: '已解决' },
  'partially-resolved': { cls: 'st-warning', icon: '⚠️', label: '部分解决' },
  escalated: { cls: 'st-critical', icon: '🚨', label: '已升级' },
  failed: { cls: 'st-critical', icon: '❌', label: '失败' },
  pending: { cls: 'st-muted', icon: '⏳', label: '处置中' },
};
function resultPill(result) {
  const m = RESULT_META[result] || { cls: 'st-muted', icon: '❓', label: result || '未知' };
  return `<span class="status-pill ${m.cls}">${m.icon} ${esc(m.label)}</span>`;
}

function renderActivities(data) {
  if (data.projects) {
    // 跨项目聚合：页签栏（全部 + 各项目名），页签切换为模块级状态 activitiesTab
    const names = (data.projects || []).map((g) => g.name).sort();
    const tabs = ['all', ...names];
    // 页签选择失效（项目消失）时回退到全部
    if (activitiesTab !== 'all' && !names.includes(activitiesTab)) activitiesTab = 'all';
    const tabBar = tabs.map((t) => {
      const label = t === 'all' ? '全部' : esc(t);
      const active = t === activitiesTab ? ' active' : '';
      const count = t === 'all'
        ? (data.projects || []).reduce((n, g) => n + (g.activities || []).length, 0)
        : (data.projects.find((g) => g.name === t).activities || []).length;
      return `<button class="tab-btn${active}" onclick="setActivitiesTab('${esc(t)}')">${label}<span class="tab-count">${count}</span></button>`;
    }).join('');
    // 当前页签内容：全部 → 按项目分段聚合；某项目 → 仅该项目卡片
    const body = activitiesTab === 'all'
      ? (data.projects || []).map((g) => `
          <div class="section">
            <div class="section-title">${esc(g.name)}<span class="count">${(g.activities || []).length} 条</span></div>
            ${(g.activities || []).length ? renderActivityCards(g.activities) : '<div class="empty-state">暂无运维记录</div>'}
          </div>`).join('')
      : (() => {
          const g = data.projects.find((x) => x.name === activitiesTab);
          const acts = (g && g.activities) || [];
          return acts.length ? renderActivityCards(acts) : '<div class="empty-state">暂无运维记录</div>';
        })();
    return `
      <div class="breadcrumb"><button onclick="nav('overview')">← 概览</button></div>
      <div class="page-title">运维记录</div>
      <div class="page-sub">跨项目 Administrator 活动</div>
      <div class="tab-bar">${tabBar}</div>
      ${body}`;
  }
  const acts = data.activities || [];
  const title = data.project ? '运维记录 · ' + esc(data.project) : '运维记录';
  const sub = `${acts.length} 条 Administrator 处置记录 · 未处理升级置顶高亮`;
  return `
    <div class="breadcrumb"><button onclick="nav('overview')">← 概览</button>
      ${data.project ? `<span class="sep">/</span>${esc(data.project)}` : ''}
    </div>
    <div class="page-title">${title}</div>
    <div class="page-sub">${sub}</div>
    ${acts.length ? renderActivityCards(acts) : '<div class="empty-state">暂无运维记录</div>'}`;
}

function setActivitiesTab(name) {
  activitiesTab = name;
  // 仅重绘当前视图（保持滚动位置，不整页 load）
  if (currentState.view === 'activities' && !currentState.project) {
    const mySeq = ++seq;
    fetchFor(currentState).then((data) => {
      if (mySeq !== seq) return;
      renderActivitiesInPlace(data);
    }).catch(() => {});
  }
}

function renderActivitiesInPlace(data) {
  const main = el('main');
  // 复用 morphdom 增量更新；无 morphdom 则直接重设
  if (main._rendered && window.morphdom) {
    const html = renderActivities(data);
    window.morphdom(main, '<main id="main">' + html + '</main>', {
      onBeforeElUpdated: (fromEl, toEl) => {
        if (fromEl && fromEl.id === 'tl-root' && toEl && toEl.id === 'tl-root') return false;
      },
    });
  } else {
    main.innerHTML = renderActivities(data);
    main._rendered = true;
  }
  main._lastHtml = renderActivities(data);
}

function renderActivityCards(acts) {
  return `<div class="activity-timeline">${acts.map(activityCard).join('')}</div>`;
}

function activityCard(a) {
  const unhandled = a.handled === false;   // 关联未处理升级 → 置顶高亮
  const sev = a.severity || 'major';
  const spec = a.spec ? `<span class="activity-spec">${esc(a.spec)}</span>` : '';
  const sig = a.signal_type ? `<span class="activity-sig">${esc(a.signal_type)}</span>` : '';
  const project = a.project
    ? `<span class="alert-item-proj">${esc(a.project)}</span>` : '';
  // 旧记录无 summary → 降级显示结构化字段（不崩溃）
  const body = a.summary
    ? `<div class="activity-summary">${esc(a.summary)}</div>`
    : `<div class="activity-fallback">（无叙述总结）处置：${esc(a.actions_taken || '—')} · 结果：${esc(a.result || '—')}</div>`;
  const action = a.actions_taken
    ? `<div class="activity-action">处置：${esc(a.actions_taken)}</div>` : '';
  const reco = a.recommended_action
    ? `<div class="activity-reco">建议：${esc(a.recommended_action)}</div>` : '';
  const needHuman = unhandled
    ? `<span class="status-pill st-critical" title="需人工决策">需人工决策</span>` : '';
  const markBtn = unhandled
    ? `<button class="alert-handled-btn activity-handled-btn"
        data-project="${esc(a.project || currentState.project || '')}"
        data-id="${esc(a.escalation_id || '')}">标记已处理</button>` : '';
  return `<div class="activity-card ${unhandled ? 'unhandled' : ''} sev-${esc(sev)}">
    <div class="activity-head">
      <span class="activity-time">${esc(fmtDate(a.created))}</span>
      ${project}${spec}${sig}
      ${resultPill(a.result)}
      ${needHuman}
      ${markBtn}
    </div>
    ${body}${action}${reco}
  </div>`;
}

// ── 顶栏 ───────────────────────────────────────────────
function updateTopbar() {
  const ov = el('btn-overview');
  ov.classList.toggle('active', currentState.view === 'overview');
  const act = el('btn-activities');
  if (act) act.classList.toggle('active', currentState.view === 'activities');
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
if (el('btn-activities')) {
  el('btn-activities').addEventListener('click', () => {
    const p = currentState.project || '';
    nav('activities/' + encodeURIComponent(p));
  });
}
if (el('btn-config')) {
  el('btn-config').addEventListener('click', () => {
    const p = currentState.project || '';
    nav('config/' + encodeURIComponent(p));
  });
}
el('project-select').addEventListener('change', (e) => {
  // 切换项目时保持当前视图类型（spec 列表/配置页/运维记录均原地更换项目），
  // 仅 spec 详情无跨项目形态，降级到该项目 SPEC 列表。
  const p = e.target.value;
  const v = currentState.view;
  if (!p) {
    if (v === 'config') nav('config');                       // 用户级配置
    else if (v === 'activities') nav('activities');          // 跨项目运维聚合
    else nav('overview');                                    // project/spec/overview → 概览
    return;
  }
  if (v === 'project') nav('project/' + encodeURIComponent(p));
  else if (v === 'config') nav('config/' + encodeURIComponent(p));
  else if (v === 'activities') nav('activities/' + encodeURIComponent(p));
  else nav('project/' + encodeURIComponent(p));              // overview/spec → 项目 SPEC 列表
});
// 运维记录页「标记已处理」：事件委托（morphdom 重绘 #main 后仍生效）
el('main').addEventListener('click', (e) => {
  const t = e.target;
  if (t.matches('.activity-handled-btn')) {
    markAlertHandled(t.dataset.project, t.dataset.id);
  }
});
window.addEventListener('hashchange', route);

// ── 在线/离线指示 ──────────────────────────────────────
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
    : state.view === 'activities' ? renderActivities(data)
    : renderSpec(data);
  if (main._rendered && window.morphdom) {
    // 增量更新（VuePress 热重载同思路）：只 patch 变化部分，避免整页替换导致
    // 图片重载 / 滚动重置 / CSS 过渡重启。`#tl-root` 由 React 自行管理，跳过。
    window.morphdom(main, '<main id="main">' + html + '</main>', {
      onBeforeElUpdated: (fromEl, toEl) => {
        // 仅当新旧节点都是时间轴根 #tl-root（保持 React 托管）时才跳过；
        // 切离时间轴页签时须让 morphdom 正常移除 #tl-root，否则场景/Bug 卡片分支会被丢弃。
        if (fromEl && fromEl.id === 'tl-root' && toEl && toEl.id === 'tl-root') return false;
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
    <div class="page-sub">监控 ${projects.length} 个项目</div>
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
  const running = p.daemon === 'running';
  // 生命周期控制按钮：按 daemon 状态禁用对应项；删除需二次确认
  const controls = `
    <div class="card-actions" onclick="event.stopPropagation()">
      <button class="ctl-btn ${running ? 'disabled' : ''}" ${running ? 'disabled' : ''}
        onclick="startProject('${esc(p.name)}')">▶ 启动</button>
      <button class="ctl-btn ${running ? '' : 'disabled'}" ${running ? '' : 'disabled'}
        onclick="stopProject('${esc(p.name)}')">■ 停止</button>
      <button class="ctl-btn ctl-danger"
        onclick="deleteProject('${esc(p.name)}')">🗑 删除</button>
    </div>`;
  return `
  <div class="card" onclick="nav('project/${encodeURIComponent(p.name)}')">
    <h3>${esc(p.name)}
      ${daemonBadge(p.daemon)}
      ${p.discovered ? '<span class="status-pill st-muted">自动发现</span>' : ''}
    </h3>
    <div class="card-meta">${esc(p.path)}</div>
    <div class="kv-row"><span class="k">SPEC 数</span><span class="v">${p.spec_count}</span></div>
    <div class="kv-row"><span class="k">问题/阻塞</span><span class="v" style="color:${(p.problems || 0) ? 'var(--critical)' : ''}">${p.problems}</span></div>
    <div class="kv-row"><span class="k">活跃运行</span><span class="v" style="color:${(p.active_runs || 0) ? 'var(--warning)' : ''}">${p.active_runs}</span></div>
    ${progressBar(p.task_done, p.task_total)}
    <div style="margin-top:10px;display:flex;flex-wrap:wrap;gap:6px">${pills}</div>
    ${controls}
  </div>`;
}

// ── 项目生命周期控制（概览卡片：启动/停止/删除） ──────
function _lifecycleRequest(name, action) {
  // action: "start" | "stop" → POST /api/projects/<name>/<action>；"delete" → DELETE
  const base = '/api/projects/' + encodeURIComponent(name);
  const method = action === 'delete' ? 'DELETE' : 'POST';
  const url = action === 'delete' ? base : base + '/' + action;
  return fetch(url, { method: method }).then((r) => {
    if (!r.ok) {
      return r.json().catch(() => ({})).then((d) => {
        throw new Error(d.error || ('HTTP ' + r.status));
      });
    }
    return r.json();
  });
}

function startProject(name) {
  _lifecycleRequest(name, 'start')
    .then((d) => { load(); })
    .catch((err) => projectControlError(name, err));
}
function stopProject(name) {
  _lifecycleRequest(name, 'stop')
    .then((d) => { load(); })
    .catch((err) => projectControlError(name, err));
}
function deleteProject(name) {
  if (!confirm(
    `确认从监控移除项目「${name}」？\n\n`
    + '该项目 daemon 会被停止，但项目文件、STATE.md、openspec/、.fenix/ 等数据全部保留在磁盘。\n'
    + '此操作仅为"软删除"（停止监控）——可通过手工编辑 ~/.config/fenixd/dashboard.yaml，'
    + '从 ignored 列表中删除对应路径来恢复监控。'
  )) return;
  _lifecycleRequest(name, 'delete')
    .then((d) => { load(); })
    .catch((err) => projectControlError(name, err));
}
function projectControlError(name, err) {
  // 操作失败：仅在该卡片上显示可读错误提示，不影响其它卡片
  showProjectError(name, err.message || String(err));
}
function showProjectError(name, msg) {
  const banner = document.createElement('div');
  banner.className = 'toast-error';
  banner.textContent = `项目「${name}」操作失败：${msg}`;
  document.body.appendChild(banner);
  setTimeout(() => banner.remove(), 6000);
}

// ── SPEC 表格：排序 / 耗时列 / fix 树（前端状态驱动，design D6） ──

// 状态生命周期顺序：drafted→ready→…→pushed
const _LIFECYCLE_RANK = {
  drafted: 0, ready: 1, implementing: 2, 'bug-found': 2.5, implemented: 3,
  testing: 4, verified: 5, done: 6, pushed: 7, blocked: 8,
};

// 构建表格行：先按 fix 树分组（根为粒度整体排序，不拆散子树），再排序
function buildSpecRows(projectName, specs) {
  const byName = {};
  specs.forEach((s) => { byName[s.name] = s; });
  const isFix = (n) => n.startsWith('fix-');

  // 计算每棵 fix 树的根（递归去 fix- 后的基名，若基名本身是 fix 则继续）
  // 顶层行 = 非 fix 规格 + 根为自身的 fix（父不在 specs 中，归入「无父级」）
  const childrenMap = {};   // 根名 → [子名...]
  const roots = [];         // 顶层行规格名
  const orphanFix = [];     // 无父级 fix 规格名

  const specNames = new Set(specs.map((s) => s.name));
  specs.forEach((s) => {
    if (!isFix(s.name)) {
      roots.push(s.name);
      return;
    }
    // fix 规格：逐级向上找父
    let parent = null;
    let base = s.name;
    let guard = 0;
    while (base.startsWith('fix-')) {
      base = base.slice(4);
      guard += 1;
      if (guard > 20) break;
    }
    // 父 = 最近的、存在于 specs 中且非自身的 fix 前缀链
    // 递归：fix-fix-a 的父是 fix-a（若存在），否则 a（若存在）
    let candidate = s.name;
    while (candidate.startsWith('fix-')) {
      const up = candidate.slice(4);
      if (up === s.name) break;
      if (specNames.has(up)) { parent = up; break; }
      candidate = up;
    }
    if (parent == null) {
      orphanFix.push(s.name);
    } else {
      (childrenMap[parent] = childrenMap[parent] || []).push(s.name);
    }
  });

  // 排序键比较器（按 specSort）
  // roots / orphanFix /childrenMap 存的是 spec 名（字符串），而 sortValue 需要
  // spec 对象取 total_duration / status 等字段；此处先经 byName 把名解析为对象，
  // 避免 a.total_duration 为 undefined → 所有比较恒等、排序静默失效（表头点击不重排）。
  function cmp(a, b) {
    const sa = typeof a === 'string' ? byName[a] : a;
    const sb = typeof b === 'string' ? byName[b] : b;
    a = sa || a;
    b = sb || b;
    const key = specSort.key;
    const dir = specSort.dir === 'desc' ? -1 : 1;
    if (!key) {
      // 默认：created 倒序，缺失排末尾
      const ac = a.created || '', bc = b.created || '';
      if (!ac && !bc) return 0;
      if (!ac) return 1;
      if (!bc) return -1;
      return bc.localeCompare(ac);
    }
    const va = sortValue(a, key), vb = sortValue(b, key);
    // 缺失值恒排末尾
    const ma = va === null || va === undefined || va === '', mb = vb === null || vb === undefined || vb === '';
    if (ma && mb) return 0;
    if (ma) return 1;
    if (mb) return -1;
    if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * dir;
    return String(va).localeCompare(String(vb)) * dir;
  }
  function sortValue(s, key) {
    switch (key) {
      case 'status': return _LIFECYCLE_RANK[s.status] != null ? _LIFECYCLE_RANK[s.status] : 99;
      case 'name': return s.name;
      case 'priority': return s.priority == null ? null : Number(s.priority);
      case 'created': return s.created || null;
      case 'task': return s.task_total ? (s.task_done / s.task_total) : (s.task_total === 0 ? 0 : null);
      case 'verify': return s.verify_total ? s.verify_done : (s.verify_total === 0 ? 0 : null);
      case 'duration': return s.total_duration == null ? 0 : Number(s.total_duration);
      default: return null;
    }
  }

  // 对顶层行排序；子行在父行下按名排序，并递归向下展开各层 fix 子规格
  // （fix-fix-* 挂在 fix-* 下，后者再挂在基名规格下 → 多层树，深度逐层 +1）
  roots.sort(cmp);
  orphanFix.sort(cmp);
  const ordered = [];
  function pushTree(name, depth, orphan) {
    if (!byName[name]) return;          // 数据缺失的行不渲染
    ordered.push({ name, depth, orphan: !!orphan });
    // 父链严格递减 fix- 前缀数 → 递归必然收敛，不会成环
    (childrenMap[name] || []).sort(cmp).forEach((cn) => pushTree(cn, depth + 1, orphan));
  }
  roots.forEach((rn) => pushTree(rn, 0, false));
  // 无父级 fix 独立一组（置于末尾），其下仍可继续展开更深层的 fix 子规格
  orphanFix.forEach((fn) => pushTree(fn, 1, true));

  return ordered.map((o) => specRow(projectName, byName[o.name], o.depth, o.orphan));
}

function renderProject(data) {
  const specs = data.specs || [];
  const project = esc(data.project);

  // 前端过滤
  const q = specFilter.q.toLowerCase();
  const type = specFilter.type;
  const filtered = specs.filter((s) => {
    if (q && !s.name.toLowerCase().includes(q)) return false;
    if (specFilter.status && s.status !== specFilter.status) return false;
    if (type === 'req' && s.name.startsWith('fix-')) return false;       // 仅需求：隐藏 fix-*
    if (type === 'issue' && !s.name.startsWith('fix-')) return false;    // 仅问题：只保留 fix-*
    return true;
  });

  // 状态下拉选项：全部状态 + STATUS_META 各状态
  const statusOptions = Object.entries(STATUS_META).map(([k, m]) =>
    `<option value="${esc(k)}" ${specFilter.status === k ? 'selected' : ''}>${m.icon} ${esc(m.label)}</option>`
  ).join('');

  // 表头定义：key 用于排序轮换；显示名
  const headers = [
    { key: 'status', label: '状态' },
    { key: 'name', label: '名称' },
    { key: 'priority', label: '优先级' },
    { key: 'created', label: '创建时间' },
    { key: 'task', label: '任务进度' },
    { key: 'verify', label: '验证' },
    { key: 'duration', label: '耗时' },
  ];
  const arrows = { asc: ' ▲', desc: ' ▼' };
  const thead = headers.map((h) => {
    const active = specSort.key === h.key;
    const arrow = active ? (arrows[specSort.dir] || '') : '';
    const cls = active ? ' sort-active' : '';
    return `<th class="sortable${cls}" onclick="sortSpecs('${h.key}')">${h.label}${arrow}</th>`;
  }).join('');
  // 文档操作列（不排序，常显「背景」「设计」按钮）
  const theadAll = thead + '<th class="doc-col">文档</th>';

  const rowsHtml = filtered.length ? buildSpecRows(data.project, filtered).join('') : '';

  const emptyHtml = specs.length === 0
    ? '<div class="empty-state">该项目暂无 SPEC</div>'
    : filtered.length === 0
      ? '<div class="empty-state">无匹配的 SPEC</div>'
      : '';

  return `
    <div class="breadcrumb"><button onclick="nav('overview')">← 概览</button><span class="sep">/</span>${project}</div>
    <div class="page-title">${project}</div>
    <div class="page-sub">${specs.length} 个 SPEC</div>
    <div class="spec-filter">
      <input type="text" id="spec-filter-q" placeholder="搜索名称…" value="${esc(specFilter.q)}" />
      <select id="spec-filter-status">
        <option value="" ${specFilter.status === '' ? 'selected' : ''}>全部状态</option>
        ${statusOptions}
      </select>
      <select id="spec-filter-type">
        <option value="" ${specFilter.type === '' ? 'selected' : ''}>全部</option>
        <option value="req" ${specFilter.type === 'req' ? 'selected' : ''}>仅需求</option>
        <option value="issue" ${specFilter.type === 'issue' ? 'selected' : ''}>仅问题</option>
      </select>
    </div>
    ${rowsHtml ? `
    <div class="spec-table-wrap">
      <table class="spec-table">
        <thead><tr>${theadAll}</tr></thead>
        <tbody>${rowsHtml}</tbody>
      </table>
    </div>` : ''}
    ${emptyHtml}`;
}

function sortSpecs(key) {
  // 同列点击：asc → desc → 取消（默认 created 倒序）
  if (specSort.key !== key) {
    specSort.key = key;
    specSort.dir = 'asc';
  } else if (specSort.dir === 'asc') {
    specSort.dir = 'desc';
  } else if (specSort.dir === 'desc') {
    specSort.key = '';
    specSort.dir = '';
  } else {
    specSort.dir = 'asc';
  }
  load();
}

function specRow(project, s, depth = 0, orphan = false) {
  const pp = pct(s.task_done, s.task_total);
  const cls = pp === 100 ? 'good' : pp >= 60 ? '' : pp > 0 ? 'warn' : 'serious';
  const verify = s.verify_total > 0
    ? `<span title="验证进度">${s.verify_done}/${s.verify_total}</span>`
    : '<span class="muted">—</span>';
  const created = s.created ? fmtDate(s.created) : '<span class="muted">—</span>';
  const dur = (s.total_duration && Number(s.total_duration) > 0)
    ? fmtDuration(Number(s.total_duration))
    : '<span class="muted">—</span>';
  // fix 子规格：缩进 + 🔧 标记
  const indent = depth > 0 ? `<span class="fix-indent" style="padding-left:${depth * 18}px"></span>` : '';
  const fixMark = depth > 0 ? '🔧 ' : '';
  const orphanClass = orphan ? ' orphan-fix' : '';
  const nameCell = `${indent}${fixMark}${esc(s.name)}`;
  // 主行（不再含「错误」列），名称单元格带 data-project/data-spec 供 hover 提示定位
  const mainRow = `
  <tr class="spec-row${orphanClass}" onclick="nav('spec/${encodeURIComponent(project)}/${encodeURIComponent(s.name)}')">
    <td>${statusPill(s.status)}</td>
    <td class="spec-name-cell" data-project="${esc(project)}" data-spec="${esc(s.name)}">${nameCell}</td>
    <td>P${s.priority ?? '?'}</td>
    <td class="created-cell">${created}</td>
    <td class="progress-cell">
      <div class="progress ${cls}"><div class="fill" style="width:${pp}%"></div></div>
      <div class="progress-labels"><span>${s.task_done}/${s.task_total}</span><span>${pp}%</span></div>
    </td>
    <td>${verify}</td>
    <td>${dur}</td>
    <td class="doc-actions">
      <a class="doc-link" href="javascript:void(0)" title="查看文档（背景/设计/任务清单）"
        onclick="event.stopPropagation(); openDocModal('${encodeURIComponent(project)}', '${encodeURIComponent(s.name)}')">文档</a>
    </td>
  </tr>`;
  // 信息子行：error 非空时跨全列显示「信息」badge 与消息同行。
  // 注意 td 必须保持 table-cell（否则 colspan 失效、宽度塌缩到首列），
  // flex 布局放在内层 .info-line 上（详见 style.css）。
  // 尾部「清除」按钮在线清理 STATE.md error；空则不渲染、不占行高
  if (s.error) {
    return mainRow + `
  <tr class="spec-info-row" onclick="event.stopPropagation()">
    <td colspan="${SPEC_COL_COUNT}">
      <div class="info-line">
        <span class="info-badge">信息</span><span class="info-msg">${esc(String(s.error))}</span>
        <button class="info-clear-btn" data-project="${esc(project)}" data-spec="${esc(s.name)}"
          onclick="event.stopPropagation(); clearSpecError('${esc(project)}', '${esc(s.name)}')">清除</button>
      </div>
    </td>
  </tr>`;
  }
  return mainRow;
}

// 在线清除 SPEC 的 error 字段（POST /api/spec-error-clear）
// 成功后立即从 DOM 移除对应信息子行（不让它依赖 watcher/轮询刷新才消失——否则
// 清除后子行残留），并触发一次列表刷新以保持与 STATE.md 一致；
// 失败则按钮短暂进入禁用+错误态，STATE.md 不变。
function clearSpecError(project, spec) {
  const btn = (typeof event !== 'undefined' && event) ? event.currentTarget : null;
  fetch('/api/spec-error-clear?project=' + encodeURIComponent(project)
      + '&spec=' + encodeURIComponent(spec), { method: 'POST' })
    .then((r) => {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(() => {
      // 立即移除信息子行：从按钮向上找到所属 .spec-info-row 并删除
      const row = btn ? btn.closest('.spec-info-row') : null;
      if (row) row.remove();
      // 兜底：若 watcher 已推送最新数据，整体刷新一次确保一致（子行已无则无副作用）
      if (currentState.view === 'project') load();
    })
    .catch(() => {
      if (!btn) return;
      btn.disabled = true;
      btn.classList.add('info-clear-err');
      btn.textContent = '清除失败';
      setTimeout(() => {
        btn.disabled = false;
        btn.classList.remove('info-clear-err');
        btn.textContent = '清除';
      }, 2000);
    });
}

function hydrateProjectFilter() {
  const qInput = el('spec-filter-q');
  const sSelect = el('spec-filter-status');
  const tSelect = el('spec-filter-type');
  if (!qInput || !sSelect || !tSelect) return;

  if (qInput._bound) return;
  qInput._bound = true;
  sSelect._bound = true;
  tSelect._bound = true;

  qInput.addEventListener('input', (e) => {
    specFilter.q = e.target.value;
    load();
  });
  sSelect.addEventListener('change', (e) => {
    specFilter.status = e.target.value;
    load();
  });
  tSelect.addEventListener('change', (e) => {
    specFilter.type = e.target.value;
    load();
  });
}

function renderSpec(d) {
  // 顶部常驻：验证结论 / 验证进度 / 任务清单（不被页签收纳）
  // 下方四个长区块：运行时间轴 / 场景 / Bug 列表 / 失败截图 → 独立页签
  const tabs = [
    { key: 'timeline', label: '运行时间轴', empty: !(d.timeline && d.timeline.length) },
    { key: 'scenarios', label: '场景结果', empty: !((d.scenarios && d.scenarios.length) || (d.report && d.report.error)) },
    { key: 'bugs', label: 'Bug 列表', empty: !(d.bugs && d.bugs.length) },
    { key: 'screenshots', label: '失败截图', empty: !(d.screenshots && d.screenshots.length) },
  ];
  // 若当前 tab 已无数据，回退到默认 timeline
  if (!tabs.find((t) => t.key === specTab)) specTab = 'timeline';
  const tabBar = tabs.map((t) => {
    const active = t.key === specTab ? ' active' : '';
    const count = t.empty ? '' : '';
    return `<button class="tab-btn${active}" onclick="setSpecTab('${t.key}')">${esc(t.label)}</button>`;
  }).join('');
  // 仅渲染当前页签内容（其它页签 DOM 不展开，但占位由相同结构提供）
  let tabBody;
  if (specTab === 'timeline') tabBody = renderTimeline(d);
  else if (specTab === 'scenarios') tabBody = renderScenarios(d);
  else if (specTab === 'bugs') tabBody = renderBugs(d);
  else tabBody = renderScreenshots(d);
  // 空数据页签占位（即便该 tab 无内容也保持页签项可见可点）
  if (!tabBody) {
    // 场景结果页签的空状态需区分两种语义：report.json 损坏/不可读 vs 无场景结果，
    // 与 renderScenarios 的损坏分支保持一致，满足验证 SPEC 文案要求。
    const labels = { timeline: '暂无运行时间轴', scenarios: '暂无场景结果', bugs: '暂无 Bug', screenshots: '暂无失败截图' };
    let emptyText = labels[specTab] || '暂无数据';
    if (specTab === 'scenarios' && d.report && d.report.error) emptyText = 'report.json 损坏或不可读';
    tabBody = `<div class="section"><div class="section-title">${tabs.find((t) => t.key === specTab).label}</div><div class="empty-state">${emptyText}</div></div>`;
  }
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
    <div class="tab-bar">${tabBar}</div>
    <div class="spec-tab-body">${tabBody}</div>`;
}

function setSpecTab(key) {
  specTab = key;
  // 仅重绘当前视图（保持滚动）；切换回时间轴时需在 DOM 就位后挂载
  const mySeq = ++seq;
  fetchFor(currentState).then((data) => {
    if (mySeq !== seq) return;
    renderSpecInPlace(data);
    if (key === 'timeline') mountTimeline();
  }).catch(() => {});
}

function renderSpecInPlace(d) {
  const main = el('main');
  if (main._rendered && window.morphdom) {
    const html = renderSpec(d);
    window.morphdom(main, '<main id="main">' + html + '</main>', {
      onBeforeElUpdated: (fromEl, toEl) => {
        // 仅当新旧节点都是时间轴根 #tl-root 时跳过；切离时间轴页签须正常移除 #tl-root，
        // 否则场景/Bug 卡片分支（.scenario.fail / .bug-card）会被 morphdom 丢弃而不渲染。
        if (fromEl && fromEl.id === 'tl-root' && toEl && toEl.id === 'tl-root') return false;
      },
    });
  } else {
    main.innerHTML = renderSpec(d);
    main._rendered = true;
  }
  main._lastHtml = renderSpec(d);
}

function renderVerdict(d) {
  const v = d.verdict;
  if (!v || !v.exists) return '';
  const s = v.summary || {};
  const bugs = parseInt(s.product_bugs, 10) || 0;
  const env = parseInt(s.env_issues, 10) || 0;
  let status = v.status || '';
  let tone = 'pass', icon = '✅';
  if (bugs > 0 || /未通过|Bug Found|失败/.test(status)) { tone = 'fail'; icon = '❌'; }
  else if (env > 0 || /环境|无法验证|不可达|unreachable/i.test(status)) { tone = 'env'; icon = '⚠️'; }
  // fix-add-verify-report-gate Bug 1：结论标题状态表情符号重复渲染。parse_verdict
  // 返回的状态串（如 "❌ 未通过（Bug Found）"）已含前缀 emoji，外层又拼接了一次
  // 状态前缀 icon，导致 "❌ ❌ 未通过"。此处若状态串自身以 emoji/符号开头，则剥离
  // 该前缀，统一由计算的 icon 承载，避免重复。
  status = status.replace(/^[\s\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{2190}-\u{21FF}\u{2B00}-\u{2BFF}\u{FE0F}\u{2705}\u{274C}\u{26A0}]+/u, '').trim();
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
// 运行记录在时间轴节点上通过「查看运行记录」打开弹窗查看（openRunModal），
// 事件流按需拉取尾部 + SSE 增量，spec 视图本身不含事件流。

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

// ── SPEC 名称 hover Why 提示（add-spec-list-hover-hint） ──
// 表头列数（移除「错误」列后）：状态/名称/优先级/创建时间/任务进度/验证/耗时/文档
const SPEC_COL_COUNT = 8;
// 按 (project, spec) 内存缓存 proposal.md 的 Why 段渲染结果
// 值形态：{status:'loading', promise} | {status:'done', html} | {status:'empty', html:null}
const whyCache = new Map();

// 从 proposal.md 源文本提取 `## Why` 段（含 GFM 语义，渲染前提取）
function extractWhy(markdown) {
  if (!markdown) return null;
  const lines = String(markdown).split('\n');
  let start = -1;
  for (let i = 0; i < lines.length; i++) {
    if (/^##\s+why\s*$/i.test(lines[i])) { start = i + 1; break; }
  }
  if (start === -1) return null;
  const collected = [];
  for (let i = start; i < lines.length; i++) {
    // 遇到下一个二级标题（## ）即段尾（含 Why 内部的 ### 子标题不受影响）
    if (/^##\s/.test(lines[i])) break;
    collected.push(lines[i]);
  }
  const text = collected.join('\n').trim();
  return text || null;
}

// 按需获取并渲染 Why 段；返回 Promise<html|null>（null = 无提示）
function fetchWhy(project, spec) {
  const key = project + '│' + spec;
  const cached = whyCache.get(key);
  if (cached) {
    if (cached.status === 'done') return Promise.resolve(cached.html);
    if (cached.status === 'empty') return Promise.resolve(null);
    if (cached.status === 'loading') return cached.promise;   // 复用进行中的请求
  }
  const p = api(`/api/spec-doc?project=${encodeURIComponent(project)}`
      + `&spec=${encodeURIComponent(spec)}&doc=proposal`)
    .then((d) => {
      if (!d.found) {                       // 文档缺失 / 无 Why 段 → 负缓存，避免反复无效请求
        whyCache.set(key, { status: 'empty', html: null });
        return null;
      }
      const why = extractWhy(d.content);
      if (!why) {
        whyCache.set(key, { status: 'empty', html: null });
        return null;
      }
      const html = mdRender(why);           // Why 已是 markdown 子串，直接经既有管线渲染
      whyCache.set(key, { status: 'done', html });
      return html;
    })
    .catch((err) => {
      whyCache.delete(key);                 // 请求失败不缓存，下次 hover 自动重试
      return null;
    });
  whyCache.set(key, { status: 'loading', promise: p, html: null });
  return p;
}

function ensureHintEl() {
  let h = el('spec-name-hint');
  if (!h) {
    h = document.createElement('div');
    h.id = 'spec-name-hint';
    h.className = 'hidden';
    document.body.appendChild(h);
  }
  return h;
}

// 按视口坐标定位 hint：优先名称下方，空间不足时向上/向左翻转，避免溢出
function positionHint(h, rect) {
  const vw = window.innerWidth, vh = window.innerHeight;
  const r = h.getBoundingClientRect();
  let top = rect.bottom + 6;
  let left = rect.left;
  if (top + r.height > vh && rect.top - 6 - r.height > 0) top = rect.top - 6 - r.height;
  if (left + r.width > vw) left = Math.max(8, vw - r.width - 8);
  h.style.top = Math.max(8, top) + 'px';
  h.style.left = Math.max(8, left) + 'px';
}

function showWhyHint(cell, project, spec) {
  if (!cell.isConnected) return;            // 重渲染后旧节点已脱离 DOM，跳过
  const h = ensureHintEl();
  const rect = cell.getBoundingClientRect();
  h.classList.remove('hidden');
  h.innerHTML = '<div class="why-loading">加载中…</div>';
  positionHint(h, rect);
  fetchWhy(project, spec).then((html) => {
    if (!html) { h.classList.add('hidden'); return; }   // empty / 无 Why 段 → 不显示
    if (!cell.isConnected) { h.classList.add('hidden'); return; }
    h.innerHTML = html;
    positionHint(h, rect);
  }).catch(() => { h.classList.add('hidden'); });
}

function hideWhyHint() {
  const h = el('spec-name-hint');
  if (h) h.classList.add('hidden');
}

// 事件委托绑定 hover / 关闭路径（name cell 会被 2 秒重渲染，故委托到 document）
let _hoverTimer = null;
let _hoverCell = null;
function initWhyHint() {
  if (initWhyHint._done) return;
  initWhyHint._done = true;

  document.addEventListener('mouseover', (e) => {
    const cell = e.target.closest ? e.target.closest('.spec-name-cell') : null;
    if (!cell) return;
    if (_hoverCell === cell) return;        // 同一单元格内移动，重置计时器
    if (_hoverTimer) clearTimeout(_hoverTimer);
    _hoverCell = cell;
    const project = cell.dataset.project, spec = cell.dataset.spec;
    _hoverTimer = setTimeout(() => showWhyHint(cell, project, spec), 200);
  });

  document.addEventListener('mouseout', (e) => {
    const cell = e.target.closest ? e.target.closest('.spec-name-cell') : null;
    if (!cell) return;
    const to = e.relatedTarget;
    if (to && cell.contains(to)) return;    // 仍在单元格内，不算离开
    if (_hoverTimer) clearTimeout(_hoverTimer);
    if (_hoverCell === cell) _hoverCell = null;
    hideWhyHint();
  });

  // 点击（含行跳转）与任意滚动（表格 wrap / 窗口）均关闭
  document.addEventListener('click', () => hideWhyHint(), true);
  document.addEventListener('scroll', () => hideWhyHint(), true);
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

function renderRunModalBody(d) {
  const raw = d.events || [];
  const events = collapseThinkingTokens(raw);
  const html = events.slice(-300).map(runEventMd).join('');
  const err = d.status === 'error' && d.error ? runEventMd(d.error) : '';
  const total = d.total_events != null ? d.total_events : raw.length;
  return `<div class="runmodal-scroll">${err}${html}</div>
    <div class="kv-row"><span class="k">共 ${total} 条事件</span></div>`;
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

// ── 运行记录弹窗（80% 屏，按需拉取 + SSE 增量） ────────
let modalRunId = null;      // 当前弹窗打开的 run（null = 未打开 / 状态弹窗）
let modalProject = '';
let modalEvents = [];       // 事件缓冲：初始尾部 + 增量追加
let modalTotal = 0;

// 呼叫 Admin 处置过程弹窗的事件缓冲（与 modalEvents/modalTotal 同结构，独立管理）
let modalAdminEvents = [];  // 当前 admin run 的事件缓冲
let modalAdminTotal = 0;

function isRunLive(status) {
  return status === 'running' || status === 'empty';
}

function renderRunModalBodyLive(body, d) {
  // 粘性滚动：更新前贴近底部则更新后自动滚到最新；用户上翻阅读历史时不强制拽回
  const nearBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 80;
  body.innerHTML = renderRunModalBody(d);
  if (nearBottom) body.scrollTop = body.scrollHeight;
}

function fetchRunTail(runId, project) {
  api('/api/runs/' + encodeURIComponent(runId)
    + '?project=' + encodeURIComponent(project) + '&tail=300')
    .then((d) => {
      const box = el('runmodal');
      const body = el('runmodal-body');
      if (modalRunId !== runId || box.classList.contains('hidden')) {
        unregisterWatch(runId);
        return;
      }
      modalEvents = d.events || [];
      modalTotal = d.total_events != null ? d.total_events : modalEvents.length;
      renderRunModalBodyLive(body, {
        run_id: runId, status: d.status, error: d.error,
        events: modalEvents, total_events: modalTotal,
      });
      if (isRunLive(d.status)) registerWatch(runId);   // 运行中 → 订阅增量推送
      else unregisterWatch(runId);
    })
    .catch(() => {});
}

function appendModalEvents(msg) {
  const box = el('runmodal');
  const body = el('runmodal-body');
  if (!body || box.classList.contains('hidden') || modalRunId !== msg.run_id) return;
  if (msg.reset) {
    // 产物被轮转/截断：重新拉取完整尾部并重新订阅
    unregisterWatch(msg.run_id);
    fetchRunTail(msg.run_id, modalProject);
    return;
  }
  modalEvents = modalEvents.concat(msg.events || []);
  modalTotal = msg.total_events != null ? msg.total_events : modalEvents.length;
  renderRunModalBodyLive(body, {
    run_id: msg.run_id, status: msg.status || 'running', error: null,
    events: modalEvents, total_events: modalTotal,
  });
  if (!isRunLive(msg.status)) unregisterWatch(msg.run_id);   // 运行结束即停订阅
}

function openRunModal(payload) {
  if (modalRunId) unregisterWatch(modalRunId);
  modalRunId = null;
  const box = el('runmodal');
  const body = el('runmodal-body');
  if (payload && payload.runId) {
    const runId = payload.runId;
    const project = payload.project || currentState.project || '';
    el('runmodal-title').textContent = runId;
    body.innerHTML = '<div class="empty-state">加载中…</div>';
    box.classList.remove('hidden');
    modalRunId = runId;
    modalProject = project;
    modalEvents = [];
    modalTotal = 0;
    fetchRunTail(runId, project);
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
  if (modalRunId) unregisterWatch(modalRunId);
  modalRunId = null;
  modalEvents = [];
  modalTotal = 0;
  el('runmodal').classList.add('hidden');
  el('runmodal-body').innerHTML = '';
}
el('runmodal').addEventListener('click', (e) => { if (e.target === el('runmodal')) closeRunModal(); });
el('runmodal-close').addEventListener('click', closeRunModal);

// ── 呼叫 Admin 处置过程弹窗（add-admin-invoke-dialog v2） ────────────
// 复用 runmodal 视觉（80% 屏宽/高）。v2 改为展示 Administrator 处置过程的实时输出：
// 解析该 SPEC 的 admin_run_id 后复用 run 弹窗的 run watch + run_events SSE 时间轴
// 渲染 Agent 消息流；run 尚未启动（无 pending disposition）时显示等待态，run 启动后
// 自动切换为实时输出。设计决策：弹窗状态用模块级变量管理（与 modalRunId 同模式），
// 不依赖路由（design D5）。
let modalAdminSpec = null;  // {project, spec, inProgress: bool} | null — null = 关闭
let modalAdminRunId = null; // 当前已定位的 admin run（null = 等待态）
let modalAdminPoll = null;  // 等待态兜底轮询定时器（5s，解析成功后清除）

// 顶部状态行元数据（处置中 / 已完成 / 已中断 / 等待中）
const ADMIN_DISP_META = {
  pending: { cls: 'st-muted', icon: '⏳', label: '处置中' },
  running: { cls: 'st-warning', icon: '🔨', label: '处置中' },
  resolved: { cls: 'st-good', icon: '✅', label: '已完成' },
  'partially-resolved': { cls: 'st-warning', icon: '⚠️', label: '部分解决' },
  escalated: { cls: 'st-critical', icon: '🚨', label: '已升级' },
  failed: { cls: 'st-critical', icon: '❌', label: '失败' },
  interrupted: { cls: 'st-critical', icon: '⛔', label: '已中断' },
  waiting: { cls: 'st-muted', icon: '⏳', label: '等待 Administrator 开始处置' },
};
function adminDispPill(status) {
  const m = ADMIN_DISP_META[status] || { cls: 'st-muted', icon: '❓', label: status || '未知' };
  return `<span class="status-pill ${m.cls}">${m.icon} ${esc(m.label)}</span>`;
}

function openAdminInvokeDialog(project, spec, inProgress) {
  const box = el('adminrec');
  const body = el('adminrec-body');
  const title = el('adminrec-title');
  const note = el('adminrec-note');
  const statusPill = el('adminrec-status');
  title.textContent = (spec || '') + ' 处置过程';
  // 409 = 已在处置中（design D4）：顶部保留「已有处置进行中」提示行
  if (inProgress) {
    note.textContent = 'ℹ 已有处置进行中';
    note.classList.remove('hidden');
  } else {
    note.classList.add('hidden');
  }
  statusPill.innerHTML = adminDispPill('waiting');
  body.innerHTML = '<div class="empty-state">等待 Administrator 开始处置…</div>';
  box.classList.remove('hidden');
  modalAdminSpec = { project, spec, inProgress: !!inProgress };
  modalAdminRunId = null;
  modalAdminEvents = [];
  modalAdminTotal = 0;
  // §3.1：打开即重拉解析端点定位该 SPEC 最新 disposition 的 admin_run_id
  fetchAdminActivities(project, spec);
  // §3.2：等待态兜底轮询（5s），解析到 run 后立即停轮询
  startAdminPoll();
}

// §3.1：解析该 SPEC 最新（优先 pending、其次最终，按时间倒序）disposition 的 admin_run_id
function fetchAdminActivities(project, spec) {
  const box = el('adminrec');
  if (!box || box.classList.contains('hidden') || !modalAdminSpec) return;
  const params = '?project=' + encodeURIComponent(project)
    + '&spec=' + encodeURIComponent(spec);
  fetch('/api/admin-activities' + params)
    .then((r) => {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then((d) => {
      if (!modalAdminSpec) return;  // 关闭期间响应，丢弃
      const acts = d.activities || [];
      // 取最新一条记录（activities 已按置顶 + 时间倒序排列，首条即最新），取其
      // admin_run_id 与处置状态（design D2）：prefer pending → 其次最新 final。
      const latest = acts[0];
      const status = latest ? (latest.status || latest.result) : null;
      // 顶部状态行随广播刷新（design D5）
      el('adminrec-status').innerHTML = latest
        ? adminDispPill(status) : adminDispPill('waiting');
      if (latest && latest.admin_run_id) {
        resolveAdminRun(latest.admin_run_id, project, spec);
      }
      // 未解析到 run 且弹窗仍开 → 保持等待态（轮询/广播会再次触发本解析）
    })
    .catch(() => {
      if (!modalAdminSpec) return;
      // 解析端点失败：等待态不报错（design 风险 → 轮询兜底），仅在尚未定位 run 时提示
      if (!modalAdminRunId) {
        el('adminrec-status').innerHTML = adminDispPill('waiting');
      }
    });
}

// §3.3：解析到 admin_run_id → 复用 run 弹窗链路（拉取事件 + 注册 watch + 时间轴渲染）
function resolveAdminRun(runId, project, spec) {
  if (modalAdminRunId === runId) return;  // 已在该 run，避免重复拉取
  // 切换 run：注销旧 watch（若有）
  if (modalAdminRunId) unregisterWatch(modalAdminRunId);
  modalAdminRunId = runId;
  stopAdminPoll();  // §3.2：解析成功即停兜底轮询
  const statusPill = el('adminrec-status');
  statusPill.innerHTML = adminDispPill('running');
  fetchAdminRunTail(runId, project);
}

function fetchAdminRunTail(runId, project) {
  const box = el('adminrec');
  const body = el('adminrec-body');
  if (modalAdminSpec && modalAdminRunId !== runId) {
    unregisterWatch(runId);
    return;
  }
  api('/api/runs/' + encodeURIComponent(runId)
    + '?project=' + encodeURIComponent(project) + '&tail=300')
    .then((d) => {
      if (modalAdminSpec && modalAdminRunId !== runId) {
        unregisterWatch(runId);
        return;
      }
      if (!modalAdminSpec) return;
      modalAdminEvents = d.events || [];
      modalAdminTotal = d.total_events != null ? d.total_events : modalAdminEvents.length;
      renderAdminRunBody(runId, d.status);
      // 顶部状态行：run 进行中显示处置中，结束显示最终状态
      const live = isRunLive(d.status);
      // 若已有最终 disposition（pending 之外）则优先显示最终状态，否则跟 run 状态
      el('adminrec-status').innerHTML = adminDispPill(live ? 'running' : (d.status || 'resolved'));
      if (live) registerWatch(runId);          // 运行中 → 订阅增量推送
      else unregisterWatch(runId);             // 运行结束即停订阅
    })
    .catch((err) => {
      if (!modalAdminSpec) return;
      // §3.4：run 拉取 404（文件被清理）→ 回退等待态并重解析
      if (err && /HTTP 404/.test(err.message)) {
        modalAdminRunId = null;
        el('adminrec-status').innerHTML = adminDispPill('waiting');
        el('adminrec-body').innerHTML =
          '<div class="empty-state">等待 Administrator 开始处置…</div>';
        startAdminPoll();
        fetchAdminActivities(modalAdminSpec.project, modalAdminSpec.spec);
      }
    });
}

function renderAdminRunBody(runId, status) {
  const body = el('adminrec-body');
  if (!body) return;
  const d = {
    run_id: runId, status: status, error: null,
    events: modalAdminEvents, total_events: modalAdminTotal,
  };
  // 复用 run 弹窗的事件时间轴渲染（runEventMd / collapseThinkingTokens）
  const raw = d.events || [];
  const events = collapseThinkingTokens(raw);
  const html = events.slice(-300).map(runEventMd).join('');
  const total = d.total_events != null ? d.total_events : raw.length;
  body.innerHTML =
    `<div class="runmodal-scroll">${html}</div>`
    + `<div class="kv-row"><span class="k">共 ${total} 条事件</span></div>`;
  body.scrollTop = body.scrollHeight;
}

// §3.4：run_events SSE 增量推送在弹窗打开且 run 匹配时更新时间轴
function appendAdminEvents(msg) {
  const body = el('adminrec-body');
  const box = el('adminrec');
  if (!body || !box || box.classList.contains('hidden')
      || !modalAdminSpec || modalAdminRunId !== msg.run_id) return;
  if (msg.reset) {
    unregisterWatch(msg.run_id);
    fetchAdminRunTail(msg.run_id, modalAdminSpec.project);
    return;
  }
  modalAdminEvents = modalAdminEvents.concat(msg.events || []);
  modalAdminTotal = msg.total_events != null ? msg.total_events : modalAdminEvents.length;
  const live = isRunLive(msg.status);
  renderAdminRunBody(msg.run_id, live ? 'running' : (msg.status || 'resolved'));
  el('adminrec-status').innerHTML = adminDispPill(live ? 'running' : (msg.status || 'resolved'));
  if (!live) unregisterWatch(msg.run_id);   // 运行结束即停订阅
}

// §3.2：等待态兜底轮询（5s，仅弹窗打开且未定位 run 时进行）
function startAdminPoll() {
  stopAdminPoll();
  if (!modalAdminSpec || modalAdminRunId) return;
  modalAdminPoll = setInterval(() => {
    if (!modalAdminSpec || modalAdminRunId) { stopAdminPoll(); return; }
    fetchAdminActivities(modalAdminSpec.project, modalAdminSpec.spec);
  }, 5000);
}
function stopAdminPoll() {
  if (modalAdminPoll) { clearInterval(modalAdminPoll); modalAdminPoll = null; }
}

// §3.5：关闭弹窗 → unregisterWatch + 停轮询 + 清空状态；后台处置不受影响
function closeAdminInvokeDialog() {
  if (modalAdminRunId) unregisterWatch(modalAdminRunId);
  stopAdminPoll();
  modalAdminSpec = null;
  modalAdminRunId = null;
  modalAdminEvents = [];
  modalAdminTotal = 0;
  el('adminrec').classList.add('hidden');
  el('adminrec-body').innerHTML = '';
  el('adminrec-status').innerHTML = '';
  el('adminrec-note').classList.add('hidden');
}
el('adminrec').addEventListener('click', (e) => { if (e.target === el('adminrec')) closeAdminInvokeDialog(); });
el('adminrec-close').addEventListener('click', closeAdminInvokeDialog);

// ── SPEC 文档弹窗（proposal.md / design.md / tasks.md，三页签） ──

// 文档页签定义（顺序即页签顺序；默认激活第一个 proposal）
const DOC_TABS = [
  { doc: 'proposal', label: '需求背景', empty: '该 spec 未提供背景文档' },
  { doc: 'design', label: '详细设计', empty: '该 spec 未提供设计文档' },
  { doc: 'tasks', label: '任务清单', empty: '该 spec 未提供任务清单文档' },
];

// 当前弹窗的 (project, spec) 与已加载/在途缓存：键 = project│spec│doc
let docModalCtx = { project: '', spec: '', active: 'proposal' };
const docCache = new Map();   // (project, spec, doc) → {status:'loading'|'done'|'empty'|'error', promise?, html?}

function _docCacheKey(project, spec, doc) {
  return project + '│' + spec + '│' + doc;
}

function openDocModal(project, spec) {
  docModalCtx = { project: decodeURIComponent(project), spec: decodeURIComponent(spec), active: 'proposal' };
  const box = el('docmodal');
  const body = el('docmodal-body');
  const title = el('docmodal-title');
  title.textContent = docModalCtx.spec;
  // 页签栏激活态重置到「需求背景」
  document.querySelectorAll('#docmodal .doc-tab-btn').forEach((b) => {
    b.classList.toggle('active', b.dataset.doc === 'proposal');
  });
  body.innerHTML = '<div class="empty-state">加载中…</div>';
  box.classList.remove('hidden');
  loadDocTab('proposal');
}

// 加载某个页签内容（懒加载 + in-flight/结果缓存，复用 fetchWhy 模式）
function loadDocTab(doc) {
  docModalCtx.active = doc;
  document.querySelectorAll('#docmodal .doc-tab-btn').forEach((b) => {
    b.classList.toggle('active', b.dataset.doc === doc);
  });
  const { project, spec } = docModalCtx;
  const key = _docCacheKey(project, spec, doc);
  const cached = docCache.get(key);
  const body = el('docmodal-body');
  if (cached) {
    if (cached.status === 'done') { body.innerHTML = cached.html; return; }
    if (cached.status === 'empty') { body.innerHTML = emptyDocHtml(doc); return; }
    if (cached.status === 'error') { body.innerHTML = errorDocHtml(); return; }
    if (cached.status === 'loading') {
      // 复用进行中的请求：等待其完成（done/empty/error 任一）后由 .then 写入 DOM
      body.innerHTML = '<div class="empty-state">加载中…</div>';
      cached.promise.then(() => {
        if (docModalCtx.active === doc && docCache.get(key)) applyDocToBody(doc);
      }).catch(() => {});
      return;
    }
  }
  body.innerHTML = '<div class="empty-state">加载中…</div>';
  const p = fetch(`/api/spec-doc?project=${encodeURIComponent(project)}&spec=${encodeURIComponent(spec)}&doc=${doc}`)
    .then((resp) => {
      if (!resp.ok) throw new Error('fetch-failed:' + resp.status);
      return resp.json();
    })
    .then((d) => {
      if (!d.found) {
        docCache.set(key, { status: 'empty', html: null });
        if (docModalCtx.active === doc) body.innerHTML = emptyDocHtml(doc);
        return;
      }
      const html = mdRender(d.content);
      docCache.set(key, { status: 'done', html: html });
      if (docModalCtx.active === doc) body.innerHTML = html;
    })
    .catch(() => {
      docCache.set(key, { status: 'error', html: null });
      if (docModalCtx.active === doc) body.innerHTML = errorDocHtml();
    });
  docCache.set(key, { status: 'loading', promise: p, html: null });
}

function applyDocToBody(doc) {
  const key = _docCacheKey(docModalCtx.project, docModalCtx.spec, doc);
  const cached = docCache.get(key);
  const body = el('docmodal-body');
  if (!cached) return;
  if (cached.status === 'done') body.innerHTML = cached.html;
  else if (cached.status === 'empty') body.innerHTML = emptyDocHtml(doc);
  else if (cached.status === 'error') body.innerHTML = errorDocHtml();
}

function emptyDocHtml(doc) {
  const t = DOC_TABS.find((x) => x.doc === doc);
  return `<div class="empty-state">${esc(t ? t.empty : '文档不存在')}</div>`;
}
function errorDocHtml() {
  return `<div class="empty-state err-state">加载失败，请稍后重试</div>`;
}

function closeDocModal() {
  el('docmodal').classList.add('hidden');
  el('docmodal-body').innerHTML = '';
}

el('docmodal').addEventListener('click', (e) => { if (e.target === el('docmodal')) closeDocModal(); });
el('docmodal-close').addEventListener('click', closeDocModal);
// 文档弹窗页签切换：按需加载 + 缓存
document.querySelectorAll('#docmodal .doc-tab-btn').forEach((b) => {
  b.addEventListener('click', () => loadDocTab(b.dataset.doc));
});
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDocModal(); });

// ── 配置页 ─────────────────────────────────────────────

const KNOWN_AGENT_TYPES = [
  { key: 'implementer', label: 'Implementer（执行）' },
  { key: 'planner-plan', label: 'Planner Plan（生成场景）' },
  { key: 'planner-judge', label: 'Planner Judge（判定结果）' },
  { key: 'verifier', label: 'Verifier（旧版验证）' },
  { key: 'administrator', label: 'Administrator（运维）' },
];

// 最近一次加载的配置数据快照（含完整 agents/gates/llm），供 collectConfigData()
// 在输入框为空/非法时回退到真实已加载值，而非硬编码默认值（避免保存时覆盖其它子键）。
let lastConfigData = null;

function renderConfig(data) {
  lastConfigData = data;
  const scope = data.scope || 'project';
  const isUser = scope === 'user';
  const project = esc(data.project || '');
  const llm = data.llm || {};
  const providers = llm.providers || [];
  const agents = data.agents || {};
  const models = agents.models || {};
  const gates = data.gates || {};
  const approveMode = gates.approve_mode || 'manual';
  const error = data.error || '';
  const hasConfig = data.raw_exists;
  const sources = data.sources || {};
  const fromUser = (key) =>
    sources[key] === 'user'
      ? '<span class="config-inherit-badge">继承自用户级</span>'
      : '';

  const title = isUser ? '配置管理 · 用户级' : '配置管理' + (project ? ' · ' + project : '');
  const sub = isUser
    ? '维护跨项目通用设置，写入 <code>~/.fenix/config.yaml</code>，其他项目未覆盖的键将继承此处值。修改后需重启 daemon 生效。'
    : '修改后需重启 daemon 生效。配置文件位于 <code>.fenix/config.yaml</code>。';
  const missingNote = isUser
    ? (hasConfig ? '' : '<span class="status-pill st-warning">⚠ 用户级配置文件尚不存在，保存后创建</span>')
    : (hasConfig ? '' : '<span class="status-pill st-warning">⚠ 项目尚无配置文件</span>');

  const providerSection = `
    <div class="config-section">
      <h3>🤖 LLM Provider 列表 ${fromUser('llm')}</h3>
      <p class="section-hint">定义可用的 LLM 提供者（baseurl / apikey / 默认模型）。</p>
      <div id="provider-list" class="provider-list">
        ${providers.map((p, i) => renderProviderCard(p, i)).join('')}
      </div>
      <button class="btn btn-secondary" id="btn-add-provider">+ 新增 Provider</button>
    </div>`;

  const assignSection = `
    <div class="config-section">
      <h3>🧩 Agent 模型分配 ${fromUser('agents.models')}</h3>
      <p class="section-hint">为每种 Agent 角色分配 Provider 与模型。模型名留空时使用所选 Provider 的默认模型。</p>
      ${isUser && providers.length === 0
        ? '<p class="section-hint config-warn-hint">⚠ 当前作用域没有可用的 LLM Provider，无法为 Agent 分配模型。请先在上方「LLM Provider 列表」添加 Provider 并保存，再回来分配；或切换到项目级配置（选择项目后进入配置页）进行分配。</p>'
        : ''}
      <div class="agent-assign-grid">
        ${KNOWN_AGENT_TYPES.map((at) => renderAgentAssignment(at, providers, models)).join('')}
      </div>
    </div>`;

  const parallelSection = `
    <div class="config-section">
      <h3>⚡ 并行度设置 ${fromUser('agents.max_concurrent')}</h3>
      <p class="section-hint">
        同时运行的 Agent 进程数上限。调度采用<strong>严格优先级并行</strong>：
        高优先级任务先执行；同一优先级内可并行至该上限；
        不同优先级不并行（低优先级等高优先级全部完成后才启动）。
      </p>
      <div class="form-row">
        <label>并行度（agents.max_concurrent）</label>
        <input type="number" id="cfg-max-concurrent" min="1" step="1"
          value="${esc(agents.max_concurrent ?? 2)}" />
        <small>默认 2。保存后约 30 秒内热加载生效。</small>
      </div>
      <div class="form-row">
        <label>单次 Agent 运行轮次上限（agents.max_turns）</label>
        <input type="number" id="cfg-max-turns" min="1" step="1"
          value="${esc(agents.max_turns ?? 300)}" />
        <small>默认 300（上限而非目标值）。单个 Agent 运行轮次达到此值即被终止并触发重试。</small>
      </div>
      <div class="form-row">
        <label>单次运行时长上限（agents.run_timeout_seconds，秒）</label>
        <input type="number" id="cfg-run-timeout" min="60" step="60"
          value="${esc(agents.run_timeout_seconds ?? 3600)}" />
        <small>默认 3600（1 小时）。单个 Agent 运行超时即终止并触发重试。</small>
      </div>
      <div class="form-row">
        <label>每日 Agent 运行限额（agents.daily_run_limit，0 = 不限）</label>
        <input type="number" id="cfg-daily-run-limit" min="0" step="1"
          value="${esc(agents.daily_run_limit ?? 50)}" />
        <small>默认 50。单个 UTC 自然日内所有 Agent 类型成功运行的累计上限（实现/验证/管理共用一个池），达到后当日停止派发，UTC 次日 0 点自动归零。设为 0 表示不限制。</small>
      </div>
      <div class="form-row">
        <label>实现尝试预算（agents.impl_run_budget，1-10）</label>
        <input type="number" id="cfg-impl-run-budget" min="1" max="10" step="1"
          value="${esc(agents.impl_run_budget ?? 4)}" />
        <small>默认 4。每 SPEC 跨修复周期的实现 run 启动次数上限（含首次实现与每轮修复重派）。达到上限即冻结该 SPEC 并交人工裁决，需人工调大预算或推进状态。合法范围 1-10。</small>
      </div>
    </div>`;

  const approveSection = `
    <div class="config-section">
      <h3>🚪 审批模式 ${fromUser('gates.approve_mode')}</h3>
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
    </div>`;

  // 界面风格（主题）页签：偏好存于浏览器 localStorage，不进入保存路径
  const currentTheme = getStoredTheme();
  const themeSection = `
    <div class="config-section">
      <h3>🎨 界面风格</h3>
      <p class="section-hint">
        选择 Dashboard 的配色风格，选择后<strong>立即全站生效</strong>，并保存在本浏览器中，
        刷新或重开页面后保持。此偏好<strong>不写入</strong> config.yaml，不随配置作用域变化。
      </p>
      <div class="approve-mode-row" data-testid="theme-options" role="radiogroup" aria-label="界面风格">
        <label class="radio-item" data-testid="theme-dark">
          <input type="radio" name="ui_theme" value="" data-value="dark"
            ${currentTheme === 'dark' ? 'checked' : ''} />
          <span><strong>黑色风格</strong>（默认）</span>
          <small>深色背景，适合弱光环境。</small>
        </label>
        <label class="radio-item" data-testid="theme-light">
          <input type="radio" name="ui_theme" value="" data-value="light"
            ${currentTheme === 'light' ? 'checked' : ''} />
          <span><strong>白色风格</strong></span>
          <small>浅色背景，适合明亮环境。</small>
        </label>
      </div>
    </div>`;

  return `
  <div class="config-page">
    <div class="page-title">${title}</div>
    <div class="page-sub">
      ${sub}
      ${missingNote}
    </div>
    ${error ? `<div class="config-error">⚠ ${esc(error)}</div>` : ''}

    <div id="config-save-banner" class="config-banner hidden"></div>

    <div class="config-tabs" data-testid="config-tabs">
      <div class="tab-bar" role="tablist">
        <button class="tab-btn active" data-testid="tab-llm-provider" data-tab="llm-provider" role="tab">🤖 LLM Provider</button>
        <button class="tab-btn" data-testid="tab-agent-models" data-tab="agent-models" role="tab">🧩 Agent 模型分配</button>
        <button class="tab-btn" data-testid="tab-parallel" data-tab="parallel" role="tab">⚡ 并行度设置</button>
        <button class="tab-btn" data-testid="tab-approve" data-tab="approve" role="tab">🚪 审批模式</button>
        <button class="tab-btn" data-testid="tab-theme" data-tab="theme" role="tab">🎨 界面风格</button>
      </div>

      <div class="tab-pane active" data-testid="pane-llm-provider" data-pane="llm-provider">${providerSection}</div>
      <div class="tab-pane" data-testid="pane-agent-models" data-pane="agent-models" hidden>${assignSection}</div>
      <div class="tab-pane" data-testid="pane-parallel" data-pane="parallel" hidden>${parallelSection}</div>
      <div class="tab-pane" data-testid="pane-approve" data-pane="approve" hidden>${approveSection}</div>
      <div class="tab-pane" data-testid="pane-theme" data-pane="theme" hidden>${themeSection}</div>
    </div>

    <div class="config-actions">
      <button class="btn btn-primary" id="btn-save-config" data-testid="btn-save-config">💾 保存配置</button>
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
  // improve-failover-model-mapping-ui（D4）：可排序多 provider 链编辑器。
  // models[at.key] 为规范化视图：{model: 角色级缺省, provider: [{provider, model}, ...]}。
  // 无该角色定义时退化为 {model: null, provider: []}。
  const assigned = models[at.key] || null;
  const roleModel = (assigned && assigned.model) || '';
  // fix-fix-fix-improve-failover-model-mapping-ui：provider 形态归一化。
  // 配置文件/API 允许 provider 为 str（"a"）、list[str]（["a","b"]）、
  // list[{provider, model?}]（[{a,m1},...]）及混合形态（{provider, model?} 与 str 混排），
  // 此处统一转换为编辑器行形态 {provider, model}，避免字符串形态加载后整行不渲染、
  // 名字不为数组元素的 provider 列回显为空（验证报告 BUG-01 根因），并防止后续
  // collectConfigData 因无行渲染而将该角色从保存数据中静默剔除。
  const raw = (assigned && assigned.provider) || [];
  const rows = (Array.isArray(raw) ? raw : [raw])
    .map((r) =>
      typeof r === 'string'
        ? { provider: r, model: '' }
        : { provider: (r && r.provider) || '', model: (r && r.model) || '' }
    )
    .filter((r) => r.provider !== '');
  const enabled = rows.length > 0;
  // 回显保真：若绑定 provider 名不在当前 providers 列表中（如载入的配置引用了
  // 列表未列出的 provider，或 providers 列表为空），仍把该值作为「选中」选项注入，
  // 避免 <select> 回退到空占位导致 Provider 列回显为空（验证报告 Bug 2 根因）。
  const providerOptions = (p) => {
    const opts = providers.map((pp) =>
      `<option value="${esc(pp.name)}" ${pp.name === p ? 'selected' : ''}>${esc(pp.name)}</option>`
    );
    if (p && !providers.some((pp) => pp.name === p)) {
      opts.unshift(`<option value="${esc(p)}" selected>${esc(p)}</option>`);
    }
    return opts.join('');
  };

  const rowHtml = rows.map((r, i) => {
    const pname = r.provider || '';
    const mval = (r.model != null && r.model !== '') ? r.model : '';
    const canUp = i > 0;
    const canDown = i < rows.length - 1;
    return `
    <div class="chain-row" data-agent="${at.key}" data-idx="${i}">
      <div class="chain-row-controls">
        <button type="button" class="btn btn-ghost btn-move" data-action="chain-up"
          data-agent="${at.key}" data-idx="${i}" title="上移" ${canUp ? '' : 'disabled="true"'}>↑</button>
        <button type="button" class="btn btn-ghost btn-move" data-action="chain-down"
          data-agent="${at.key}" data-idx="${i}" title="下移" ${canDown ? '' : 'disabled="true"'}>↓</button>
      </div>
      <select class="assign-provider" data-agent="${at.key}" data-idx="${i}">
        <option value="">-- 选择 Provider --</option>
        ${providerOptions(pname)}
      </select>
      <input type="text" class="assign-model" placeholder="${roleModel ? esc('留空用角色级缺省 ' + roleModel) : '模型名（留空用角色级缺省）'}"
        value="${esc(mval)}" data-agent="${at.key}" data-idx="${i}" />
      <button type="button" class="btn btn-ghost btn-danger" data-action="chain-remove"
        data-agent="${at.key}" data-idx="${i}" title="删除此行">✕</button>
    </div>`;
  }).join('');

  // improve-failover-model-mapping-ui（D4）：链行容器只放 .chain-row，使每个角色下
  // 「第 N 行」可用 .chain-row:nth-child(N) 稳定寻址（避免 role-model-row 抢占 nth-child）。
  // .btn-add-chain 置于 .assign-fields 之外，确保空状态（.assign-fields.disabled 带
  // pointer-events:none 时）添加按钮仍可点击、不被遮挡。
  return `
  <div class="agent-assign-card" data-agent="${at.key}">
    <div class="agent-label">${esc(at.label)}</div>
    <div class="role-model-row">
      <label>角色级默认模型（留空表示无全链缺省，逐元素必须自带 model）</label>
      <input type="text" class="assign-role-model" data-agent="${at.key}"
        placeholder="模型名（如 deepseek-v4-flash），可选"
        value="${esc(roleModel)}" />
    </div>
    <div class="assign-fields ${enabled ? '' : 'disabled'}" data-agent="${at.key}">
      ${enabled ? rowHtml : ''}
    </div>
    <button type="button" class="btn btn-secondary btn-add-chain" data-agent="${at.key}">+ 添加 Provider 行</button>
  </div>`;
}

// ── 配置页交互 ─────────────────────────────────────────

// #main 元素全程常驻（morphdom 只 patch 其内部，不替换根），委托事件绑定一次
// 即可作用于所有重绘后的配置页 DOM；而按钮节点会被替换/复用，防重标记必须
// 挂在 JS 属性上（data-* 属性会在 morphdom patch 时被抹掉，造成 listener 累积）。
let configDelegated = false;

function hydrateConfigPage() {
  if (currentState.view !== 'config') return;
  const main = el('main');
  if (!main) return;

  // 主题选项从 localStorage 恢复（不读取传入配置快照）
  initTheme();

  // improve-failover-model-mapping-ui：URL 深链带 tab 参数时直接进入对应配置页签，
  // 避免 Agent 模型分配等被默认隐藏的 tab 挡住（验证场景与直接分享链接受益）。
  const tab = currentState.tab;
  if (tab) {
    const btn = main.querySelector(`.config-tabs .tab-btn[data-tab="${tab}"]`);
    if (btn) {
      main.querySelectorAll('.config-tabs .tab-btn').forEach((b) =>
        b.classList.toggle('active', b === btn));
      main.querySelectorAll('.config-tabs .tab-pane').forEach((pane) => {
        const active = pane.dataset.pane === tab;
        pane.classList.toggle('active', active);
        if (active) pane.removeAttribute('hidden');
        else pane.setAttribute('hidden', '');
      });
    }
  }

  // 新增 Provider（按钮节点随渲染重建/复用）
  const addBtn = el('btn-add-provider');
  if (addBtn && !addBtn._bound) {
    addBtn._bound = true;
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

  // 保存按钮（节点随渲染重建/复用）
  const saveBtn = el('btn-save-config');
  if (saveBtn && !saveBtn._bound) {
    saveBtn._bound = true;
    saveBtn.addEventListener('click', saveConfig);
  }

  if (configDelegated) return;
  configDelegated = true;

  // 事件委托（#main 常驻，一次绑定全视图有效）：
  // Provider 删除 / 自定义环境变量增删 / 页签切换
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
    } else if (t.matches('[data-action="chain-add"]') || t.classList.contains('btn-add-chain')) {
      // 新增一行 provider 链行（improve-failover-model-mapping-ui D4）
      const agentKey = (t.dataset.agent) || t.getAttribute('data-agent');
      const card = main.querySelector(`.agent-assign-card[data-agent="${agentKey}"]`);
      if (!card) return;
      const fields = card.querySelector('.assign-fields');
      if (fields) fields.classList.remove('disabled');
      // 读取角色级缺省模型，用于新行 model 输入框占位（与初始行一致）
      const roleModelInp = card.querySelector(`.assign-role-model[data-agent="${agentKey}"]`);
      const roleDefault = roleModelInp ? roleModelInp.value.trim() : '';
      const div = document.createElement('div');
      div.innerHTML = renderChainRow(agentKey, '', '', readProviderCards(), roleDefault);
      const rowEl = div.firstElementChild;
      if (fields) fields.appendChild(rowEl);
      reindexChainRows(main, agentKey);
    } else if (t.matches('[data-action="chain-remove"]')) {
      // 删除该行
      const agentKey = t.dataset.agent;
      const rowEl = t.closest('.chain-row');
      if (rowEl) rowEl.remove();
      const fields = main.querySelector(`.agent-assign-card[data-agent="${agentKey}"] .assign-fields`);
      if (fields && fields.querySelectorAll('.chain-row').length === 0) fields.classList.add('disabled');
      reindexChainRows(main, agentKey);
    } else if (t.matches('[data-action="chain-up"]') || t.matches('[data-action="chain-down"]')) {
      // 上移 / 下移：与相邻行交换 DOM 位置（链序即 DOM 顺序）
      const agentKey = t.dataset.agent;
      const idx = parseInt(t.dataset.idx, 10);
      const rowEl = t.closest('.chain-row');
      const fields = main.querySelector(`.agent-assign-card[data-agent="${agentKey}"] .assign-fields`);
      if (!rowEl || !fields) return;
      if (t.dataset.action === 'chain-up' && idx > 0) {
        const prev = rowEl.previousElementSibling;
        if (prev && prev.classList.contains('chain-row')) fields.insertBefore(rowEl, prev);
      } else if (t.dataset.action === 'chain-down') {
        const next = rowEl.nextElementSibling;
        if (next && next !== fields.querySelector('.btn-add-chain')) fields.insertBefore(next, rowEl);
      }
      reindexChainRows(main, agentKey);
    } else {
      const btn = t.closest ? t.closest('.config-tabs .tab-btn') : null;
      if (!btn) return;
      // 仅显隐 pane，不重渲染、不丢表单输入
      const tab = btn.dataset.tab;
      main.querySelectorAll('.config-tabs .tab-btn').forEach((b) =>
        b.classList.toggle('active', b === btn)
      );
      main.querySelectorAll('.config-tabs .tab-pane').forEach((pane) => {
        const active = pane.dataset.pane === tab;
        pane.classList.toggle('active', active);
        if (active) pane.removeAttribute('hidden');
        else pane.setAttribute('hidden', '');
      });
    }
  });

  // 界面风格（主题）切换
  main.addEventListener('change', (e) => {
    const t = e.target;
    if (t.matches('input[name="ui_theme"]')) {
      setTheme(t);
      e.stopPropagation();
      return;
    }
  });
}

function reindexProviders() {
  const cards = document.querySelectorAll('.provider-card');
  cards.forEach((card, i) => {
    card.dataset.idx = i;
    const removeBtn = card.querySelector('[data-action="remove-provider"]');
    if (removeBtn) removeBtn.dataset.idx = i;
  });
}

/* improve-failover-model-mapping-ui：链行编辑器辅助函数（D4） */
// roleModel：角色级缺省模型，用于新行 model 输入框占位提示（与初始行一致）。
function renderChainRow(agentKey, provider, model, providers, roleModel) {
  const providerOpts = providers.map((p) =>
    `<option value="${esc(p.name)}" ${p.name === provider ? 'selected' : ''}>${esc(p.name)}</option>`
  ).join('');
  const placeholder = roleModel
    ? esc('留空用角色级缺省 ' + roleModel)
    : '模型名（留空用角色级缺省）';
  return `
  <div class="chain-row" data-agent="${agentKey}" data-idx="0">
    <div class="chain-row-controls">
      <button type="button" class="btn btn-ghost btn-move" data-action="chain-up"
        data-agent="${agentKey}" data-idx="0" title="上移" disabled="true">↑</button>
      <button type="button" class="btn btn-ghost btn-move" data-action="chain-down"
        data-agent="${agentKey}" data-idx="0" title="下移" disabled="true">↓</button>
    </div>
    <select class="assign-provider" data-agent="${agentKey}" data-idx="0">
      <option value="">-- 选择 Provider --</option>
      ${providerOpts}
    </select>
    <input type="text" class="assign-model" placeholder="${placeholder}"
      value="${esc(model)}" data-agent="${agentKey}" data-idx="0" />
    <button type="button" class="btn btn-ghost btn-danger" data-action="chain-remove"
      data-agent="${agentKey}" data-idx="0" title="删除此行">✕</button>
  </div>`;
}

// 上移/下移按钮的 disabled 状态：断言（attribute_match）期望 disabled 属性值为
// "true"，而 HTML 布尔属性 disabled 序列化为 disabled=""（get_attribute 返回 ""），
// 导致验证场景判定失败（报告 Bug 3/4 根因）。故显式以 setAttribute('disabled','true')
// 承载状态，启用时 removeAttribute 彻底移除，避免残留 disabled="" 误判按钮禁用。
function setMoveDisabled(btn, disabled) {
  if (!btn) return;
  btn.disabled = disabled;
  if (disabled) btn.setAttribute('disabled', 'true');
  else btn.removeAttribute('disabled');
}

function reindexChainRows(main, agentKey) {
  const rows = main.querySelectorAll(`.chain-row[data-agent="${agentKey}"]`);
  rows.forEach((row, i) => {
    row.dataset.idx = i;
    // data-action 按钮：chain-up / chain-down / chain-remove
    row.querySelectorAll('[data-action^="chain-"]').forEach((btn) => { btn.dataset.idx = i; });
    // assign-provider / assign-model 的 data-idx
    row.querySelectorAll('.assign-provider, .assign-model').forEach((inp) => { inp.dataset.idx = i; });
    // 上移/下移 disabled 状态
    const upBtn = row.querySelector('[data-action="chain-up"]');
    const downBtn = row.querySelector('[data-action="chain-down"]');
    if (upBtn) setMoveDisabled(upBtn, i === 0);
    if (downBtn) setMoveDisabled(downBtn, i === rows.length - 1);
  });
}

function readProviderCards() {
  const main = el('main');
  const providers = [];
  main.querySelectorAll('.provider-card').forEach((card) => {
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
  return providers;
}

function collectConfigData() {
  const main = el('main');
  // Providers
  const providers = readProviderCards();

  // Agent models — improve-failover-model-mapping-ui（D4）：可排序多 provider 链编辑器。
  // 每个角色输出规范化编辑器状态：{model: 角色级缺省, provider: [{provider, model}, ...]}。
  const models = {};
  KNOWN_AGENT_TYPES.forEach((at) => {
    // 角色级缺省模型（独立输入框，与逐行 model 区分）
    const roleModelInp = main.querySelector(`.assign-role-model[data-agent="${at.key}"]`);
    const roleModel = roleModelInp ? roleModelInp.value.trim() : '';
    // 收集该角色所有链行（按 DOM 顺序即链序）
    const rows = [];
    main.querySelectorAll(`.chain-row[data-agent="${at.key}"]`).forEach((row) => {
      const providerSel = row.querySelector('.assign-provider');
      const modelInp = row.querySelector('.assign-model');
      const provider = providerSel ? providerSel.value.trim() : '';
      const model = modelInp ? modelInp.value.trim() : '';
      // 仅收集已选 provider 的行（空行视为未配置，丢弃）
      if (provider) {
        rows.push({ provider, model });
      }
    });
    if (rows.length > 0 || roleModel) {
      const entry = { provider: rows };
      if (roleModel) entry.model = roleModel;
      models[at.key] = entry;
    }
  });

  // 已加载配置快照（供输入框为空/非法时回退真实值，避免用硬编码默认值覆盖）
  const loadedAgents = (lastConfigData && lastConfigData.agents) || {};

  // 解析数字输入：空串 / 非数字（NaN）→ 回退到已加载真实值；回退值仍非数字（首次无配置）
  // 才用领域默认值。这样保存「仅编辑 max_turns」时不会把 max_concurrent 重置为硬编码 2。
  const numOr = (input, fallback, domainDefault) => {
    if (!input) return (fallback != null ? fallback : domainDefault);
    const raw = input.value.trim();
    if (raw === '') return (fallback != null ? fallback : domainDefault);
    const n = parseInt(raw, 10);
    if (Number.isNaN(n)) return (fallback != null ? fallback : domainDefault);
    return n;
  };

  // Max concurrent (parallelism)
  const maxConcurrentInput = main.querySelector('#cfg-max-concurrent');
  const maxConcurrent = numOr(maxConcurrentInput, loadedAgents.max_concurrent, 2);

  // Max turns per agent run (single agent run turn limit)
  const maxTurnsInput = main.querySelector('#cfg-max-turns');
  const maxTurns = numOr(maxTurnsInput, loadedAgents.max_turns, 300);

  // Run timeout (single agent run limit, seconds)
  const runTimeoutInput = main.querySelector('#cfg-run-timeout');
  const runTimeout = numOr(runTimeoutInput, loadedAgents.run_timeout_seconds, 3600);

  // Daily run limit (0 = unlimited)
  const dailyRunLimitInput = main.querySelector('#cfg-daily-run-limit');
  const dailyRunLimit = numOr(dailyRunLimitInput, loadedAgents.daily_run_limit, 50);

  // 实现尝试预算（1-10，超出范围回退真实值，避免脏值落盘）
  const implRunBudgetInput = main.querySelector('#cfg-impl-run-budget');
  const implRunBudget = numOr(implRunBudgetInput, loadedAgents.impl_run_budget, 4);

  // Approve mode
  const approveMode = (main.querySelector('input[name="approve_mode"]:checked') || {}).value || 'manual';

  return {
    llm: { providers },
    agents: { models, max_concurrent: maxConcurrent, max_turns: maxTurns, run_timeout_seconds: runTimeout, daily_run_limit: dailyRunLimit, impl_run_budget: implRunBudget },
    gates: { approve_mode: approveMode },
  };
}

function saveConfig() {
  const banner = el('config-save-banner');
  const saveBtn = el('btn-save-config');
  const main = el('main');
  const payload = collectConfigData();

  // 校验：每行已选 Provider 的链不能静默丢弃。模型名留空时依赖角色级缺省或 Provider 默认模型；
  // 仅当无任何模型可用时阻止保存（improve-failover-model-mapping-ui D4）。
  const providerDefaults = {};
  readProviderCards().forEach((p) => { if (p.name) providerDefaults[p.name] = p.model || ''; });
  const missingModel = [];
  KNOWN_AGENT_TYPES.forEach((at) => {
    const card = main.querySelector(`.agent-assign-card[data-agent="${at.key}"]`);
    if (!card) return;
    const roleModelInp = card.querySelector(`.assign-role-model[data-agent="${at.key}"]`);
    const roleDefault = roleModelInp ? roleModelInp.value.trim() : '';
    const rows = card.querySelectorAll('.chain-row');
    if (rows.length === 0) return; // 无链行 → 跳过校验（未分配）
    const hasAnyModel = roleDefault !== '';
    let allRowsHaveModel = true;
    rows.forEach((row) => {
      const provSel = row.querySelector('.assign-provider');
      const modelInp = row.querySelector('.assign-model');
      const provider = provSel ? provSel.value.trim() : '';
      const model = modelInp ? modelInp.value.trim() : '';
      if (!provider) return; // 空 provider 行已由 collectConfigData 丢弃
      const hasModel = !!(model || roleDefault || providerDefaults[provider]);
      if (!hasModel) allRowsHaveModel = false;
    });
    if (!hasAnyModel && !allRowsHaveModel) {
      missingModel.push(at.label);
    }
  });

  if (missingModel.length > 0) {
    const parts = [];
    parts.push(missingModel.join('、') + ' 无可用模型（角色级缺省与逐行模型均为空，且 Provider 也无默认模型）');
    if (banner) {
      banner.className = 'config-banner error';
      banner.textContent = '❌ 保存失败：' + parts.join('；') + '。';
    }
    return;
  }

  // 实现尝试预算范围校验（1-10）：越界阻止保存，避免脏值落盘
  const implBudget = payload.agents && payload.agents.impl_run_budget;
  if (!Number.isInteger(implBudget) || implBudget < 1 || implBudget > 10) {
    if (banner) {
      banner.className = 'config-banner error';
      banner.textContent = '❌ 保存失败：实现尝试预算（agents.impl_run_budget）必须为 1-10 的整数。';
    }
    if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = '💾 保存配置'; }
    return;
  }

  // 用户模式（无项目）→ POST /api/config；项目模式 → POST /api/config?project=<name>
  const url = currentState.project
    ? '/api/config?project=' + encodeURIComponent(currentState.project)
    : '/api/config';

  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.textContent = '保存中…';
  }
  if (banner) banner.className = 'config-banner hidden';

  fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
    .then((r) => {
      if (!r.ok) return r.json().then((d) => { throw new Error(d.error || 'HTTP ' + r.status); });
      return r.json();
    })
    .then((data) => {
      if (banner) {
        banner.className = 'config-banner success';
        banner.textContent = data.path
          ? `✅ 配置已保存并写入 ${data.path}，重启 daemon 后生效`
          : '✅ 配置已保存，重启 daemon 后生效';
      }
      // 重新拉取最新配置以刷新表单/快照（避免下次保存用旧数据覆盖），
      // 但不得重绘 #config-save-banner —— morphdom 重渲染会把成功横幅重置为
      // hidden、在断言/用户看到之前吞掉保存反馈（验证场景 6 例失败的根因）。
      // 改为静默刷新数据，横幅由自身 setTimeout 保留足够时长后自动隐藏。
      refreshConfigDataSilently();
      setTimeout(hideConfigBanner, 4000);
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

// 保存成功后静默刷新配置数据（更新 lastConfigData 快照，供下次保存回退真实值），
// 但不重绘 #config-save-banner / 表单 DOM —— 避免 morphdom 重渲染吞掉保存反馈横幅。
function refreshConfigDataSilently() {
  if (currentState.view !== 'config') return;
  fetchFor(currentState)
    .then((data) => { if (data) lastConfigData = data; })
    .catch(() => {});
}

// 延时隐藏保存反馈横幅（保留足够时长供断言捕获与用户确认，避免立即消失误判未提示）。
function hideConfigBanner() {
  const banner = el('config-save-banner');
  if (banner && (banner.className.indexOf('success') !== -1 ||
                 banner.className.indexOf('error') !== -1)) {
    banner.className = 'config-banner hidden';
  }
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

// ── 界面风格（主题）切换 ─────────────────────────────────
// 主题偏好存于浏览器 localStorage（键 fenix.theme，取值仅 dark/light），
// 不写入 config.yaml、不触发任何 API 请求；切换即时全站生效（改 <html> 根
// data-theme 属性，由 CSS 变量驱动）。首帧防闪烁由 index.html <head> 内联
// 脚本负责；此处提供应用函数与配置页选项初始化。

const THEME_KEY = 'fenix.theme';

// 读取偏好：非法/缺失回退 dark（与内联脚本保持一致）
function getStoredTheme() {
  try {
    const t = localStorage.getItem(THEME_KEY);
    if (t === 'light' || t === 'dark') return t;
  } catch (e) { /* localStorage 不可用：回退 dark */ }
  return 'dark';
}

// 同步两个主题单选的 checked「属性」（而非仅 property），使
// getAttribute('checked') 稳定返回 "true"/"false"，供自动化断言读取。
function syncThemeCheckedAttrs() {
  const group = document.querySelector('[data-testid="theme-options"]');
  if (!group) return;
  const active = getStoredTheme();
  group.querySelectorAll('input[name="ui_theme"]').forEach((inp) => {
    const on = (inp.dataset.value || '') === active;
    inp.setAttribute('checked', on ? 'true' : 'false');
    inp.checked = on;
  });
}

// 应用主题：写根属性 + 持久化 + 同步属性。不进入保存路径、不触发请求。
// 主题名取自单选的 data-value（value 留空以兼容 `input_value` 断言读取）。
function setTheme(theme) {
  theme = (theme && theme.dataset && theme.dataset.value) || theme;
  if (theme !== 'light' && theme !== 'dark') theme = 'dark';
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem(THEME_KEY, theme); } catch (e) { /* 忽略持久化失败 */ }
  syncThemeCheckedAttrs();
}

// 启动与配置页（重）渲染后调用：确保根属性与持久化一致（name 冲突时以存储为准）。
// 因 morphdom 增量更新会在同步代码之后再 patch 一次 DOM，导致 radio 的 checked
// property 被重置，故同步后再用 requestAnimationFrame 兜底重同步一次属性/属性值。
function initTheme() {
  const t = getStoredTheme();
  document.documentElement.dataset.theme = t;
  syncThemeCheckedAttrs();
  requestAnimationFrame(syncThemeCheckedAttrs);
}

// 导出到全局供内联 onclick 使用
window.nav = nav;
window.openLightbox = openLightbox;
window.openRunModal = openRunModal;

// ── SPEC 行右键上下文菜单（add-spec-context-menu） ────────────────

// 菜单单例：全局复用，避免每次右键重建 DOM
let _specCtxMenuEl = null;
let _specCtxMenuSpec = null;  // 当前菜单关联的 {project, spec, priority, status}
let _specCtxMenuCloseHandler = null;

function _ensureSpecContextMenu() {
  if (_specCtxMenuEl) return _specCtxMenuEl;
  const menu = document.createElement('div');
  menu.id = 'spec-ctx-menu';
  menu.className = 'spec-ctx-menu';
  menu.innerHTML =
    '<div class="ctx-item" data-action="admin-invoke">呼叫 Admin 介入</div>' +
    '<div class="ctx-item" data-action="priority">调整优先级</div>' +
    '<div class="ctx-item ctx-danger" data-action="delete">删除 Spec</div>';
  document.body.appendChild(menu);
  _specCtxMenuEl = menu;

  menu.addEventListener('click', (e) => {
    const item = e.target.closest('.ctx-item');
    if (!item || !_specCtxMenuSpec) return;
    const action = item.dataset.action;
    const { project, spec } = _specCtxMenuSpec;
    _hideSpecContextMenu();
    if (action === 'admin-invoke') _ctxAdminInvoke(project, spec);
    else if (action === 'priority') _ctxSetPriority(project, spec);
    else if (action === 'delete') _ctxDeleteSpec(project, spec);
  });

  return menu;
}

function _showSpecContextMenu(x, y, meta) {
  const menu = _ensureSpecContextMenu();
  _specCtxMenuSpec = meta;
  menu.style.display = 'block';

  // 视口翻转定位：防止超出窗口边缘
  const mw = menu.offsetWidth, mh = menu.offsetHeight;
  const vw = window.innerWidth, vh = window.innerHeight;
  if (x + mw > vw) x = Math.max(0, vw - mw - 4);
  if (y + mh > vh) y = Math.max(0, vh - mh - 4);
  menu.style.left = x + 'px';
  menu.style.top = y + 'px';

  // 关闭：Esc / 点击外部 / 滚动
  _specCtxMenuCloseHandler = (e) => {
    if (e.type === 'keydown' && e.key === 'Escape') { _hideSpecContextMenu(); return; }
    if (e.type === 'click' && !menu.contains(e.target)) { _hideSpecContextMenu(); return; }
    if (e.type === 'scroll') { _hideSpecContextMenu(); return; }
  };
  // 使用 capture 阶段确保在其它 click handler 之前拦截
  document.addEventListener('click', _specCtxMenuCloseHandler, { capture: true });
  document.addEventListener('keydown', _specCtxMenuCloseHandler, { capture: true });
  document.addEventListener('scroll', _specCtxMenuCloseHandler, { capture: true });
}

function _hideSpecContextMenu() {
  if (_specCtxMenuEl) _specCtxMenuEl.style.display = 'none';
  _specCtxMenuSpec = null;
  if (_specCtxMenuCloseHandler) {
    document.removeEventListener('click', _specCtxMenuCloseHandler, { capture: true });
    document.removeEventListener('keydown', _specCtxMenuCloseHandler, { capture: true });
    document.removeEventListener('scroll', _specCtxMenuCloseHandler, { capture: true });
    _specCtxMenuCloseHandler = null;
  }
}

// ── 菜单项动作 ──────────────────────────────────────

function _ctxAdminInvoke(project, spec) {
  // add-admin-invoke-dialog：2xx 与 409 均打开处置记录弹窗（409 = 已在处置中），
  // 其他错误仅 toast。409 时弹窗顶部显示「已有处置进行中」提示。
  fetch('/api/spec-admin-invoke?project=' + encodeURIComponent(project)
      + '&spec=' + encodeURIComponent(spec), { method: 'POST' })
    .then((r) => {
      if (r.ok) return { data: {}, inProgress: false };
      return r.json().then((d) => {
        if (r.status === 409) return { data: d, inProgress: true };
        throw new Error(d.error || 'HTTP ' + r.status);
      });
    })
    .then((result) => {
      openAdminInvokeDialog(project, spec, result.inProgress);
      // 刷新运维活动区（若在运维记录视图）
      if (currentState.view === 'activities') load();
    })
    .catch((err) => toast(err.message || '呼叫失败', true));
}

function _ctxSetPriority(project, spec) {
  // 预填当前值：从 spec 行的 DOM 中读取 P 值
  let currentP = 5;
  try {
    const nameCells = document.querySelectorAll(`.spec-row .spec-name-cell[data-spec="${CSS.escape(spec)}"]`);
    if (nameCells.length) {
      const row = nameCells[0].closest('tr');
      if (row) {
        const tds = row.querySelectorAll('td');
        // 优先级在第 3 列（index 2）
        if (tds[2]) {
          const m = tds[2].textContent.match(/(\d)/);
          if (m) currentP = parseInt(m[1], 10);
        }
      }
    }
  } catch (_) { /* ignore read failure */ }

  const input = prompt('请输入优先级（P1 最高，P9 最低）：', currentP);
  if (input === null) return; // 取消
  const priority = parseInt(input, 10);
  if (isNaN(priority) || priority < 1 || priority > 9) {
    toast('请输入 1-9 的整数', true);
    return;
  }
  fetch('/api/spec-priority?project=' + encodeURIComponent(project)
      + '&spec=' + encodeURIComponent(spec), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ priority }),
  })
    .then((r) => { if (!r.ok) return r.json().then(d => { throw new Error(d.error || 'HTTP ' + r.status); }); return r.json(); })
    .then(() => { toast('优先级已更新'); })
    .catch((err) => toast(err.message || '更新失败', true));
}

function _ctxDeleteSpec(project, spec) {
  if (!confirm('确认删除 Spec「' + spec + '」？\n\n软删除：STATE.md 移除该条目，\nopenspec/changes/' + spec + '/ 目录移入 archive 归档。\n归档路径：openspec/changes/archive/' + spec + '-<时间戳>/')) return;
  fetch('/api/spec-delete?project=' + encodeURIComponent(project)
      + '&spec=' + encodeURIComponent(spec), { method: 'POST' })
    .then((r) => { if (!r.ok) return r.json().then(d => { throw new Error(d.error || 'HTTP ' + r.status); }); return r.json(); })
    .then((d) => {
      toast('Spec「' + spec + '」已删除');
      // 乐观移除：立即从 DOM 删除该行及其信息子行，不等轮询/重拉，
      // 避免删除后行仍短暂残留（重拉前视口里仍可见旧行）。STATE.md 变更会经
      // SSE 推送触发整页刷新做最终一致性，无需在此显式 load()（否则静态 mock
      // 重拉会把已删行重新加回，造成「删除后行仍在」的误判）。
      document.querySelectorAll('.spec-name-cell[data-spec="' + CSS.escape(spec) + '"]')
        .forEach((cell) => {
          const row = cell.closest('tr');
          if (!row) return;
          // 先获取信息子行引用，再移除主行（remove 后 nextElementSibling 为 null）
          const next = row.nextElementSibling;
          const isInfoRow = next && next.classList.contains('spec-info-row');
          row.remove();
          if (isInfoRow) next.remove();
        });
    })
    .catch((err) => toast(err.message || '删除失败', true));
}

function initSpecContextMenu() {
  document.addEventListener('contextmenu', (e) => {
    // 只在 spec 行内拦截（.spec-name-cell 含 data-spec）
    const nameCell = e.target.closest('.spec-name-cell[data-spec]');
    if (!nameCell) return;
    e.preventDefault();
    const spec = nameCell.dataset.spec;
    const project = nameCell.dataset.project;
    // 从该行获取优先级（供 prompt 预填）
    let priority = 5;
    const row = nameCell.closest('tr');
    if (row) {
      const tds = row.querySelectorAll('td');
      if (tds[2]) {
        const m = tds[2].textContent.match(/(\d)/);
        if (m) priority = parseInt(m[1], 10);
      }
    }
    _showSpecContextMenu(e.clientX, e.clientY, { project, spec, priority });
  });
}

// ── 启动 ───────────────────────────────────────────────
route();
connectSSE();
initWhyHint();
initSpecContextMenu();
initAlertBanner();
