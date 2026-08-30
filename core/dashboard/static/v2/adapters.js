/**
 * adapters.js — API 响应到 AMIS 数据结构的适配纯函数集
 *
 * UMD: 浏览器端挂 window.Adapters; node 测试通过 require 导入。
 * 行为唯一权威: docs/superpowers/specs/2026-08-29-amis-dashboard-v2-behavior.md
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = { Adapters: factory() };
  else root.Adapters = factory();
})(typeof self !== 'undefined' ? self : this, function () {

  // ── §2 状态生命周期顺序 ──────────────────────────────────
  const SPEC_LIFECYCLE = [
    'drafted', 'ready', 'implementing', 'bug-found', 'implemented',
    'testing', 'verified', 'done', 'pushed', 'blocked',
  ];

  const _LIFECYCLE_RANK = {};
  SPEC_LIFECYCLE.forEach((s, i) => { _LIFECYCLE_RANK[s] = i; });

  // ── 工具函数 ──────────────────────────────────────────────
  function num(v, fallback) {
    const n = Number(v);
    return Number.isNaN(n) ? (fallback != null ? fallback : 0) : n;
  }

  // ── adaptSpecs ────────────────────────────────────────────
  // 字段映射 + fix 树构建 + 生命周期排序
  // behavior.md §2: fix-<父名> 归入父名行 children; 父行聚合子任务进度
  function adaptSpecs(rawList) {
    if (!Array.isArray(rawList) || rawList.length === 0) return [];

    const byName = {};
    rawList.forEach(s => { byName[s.name] = s; });
    const specNames = new Set(rawList.map(s => s.name));
    const isFix = n => n.startsWith('fix-');

    // ── 构建 childrenMap ──
    const childrenMap = {}; // parentName → [childName, ...]
    const roots = [];
    const orphanFix = [];

    rawList.forEach(s => {
      if (!isFix(s.name)) {
        roots.push(s.name);
        return;
      }
      // 逐级向上找父
      let parent = null;
      let candidate = s.name;
      let guard = 0;
      while (candidate.startsWith('fix-')) {
        const up = candidate.slice(4);
        if (up === s.name) break;
        if (specNames.has(up)) { parent = up; break; }
        candidate = up;
        guard += 1;
        if (guard > 20) break;
      }
      if (parent == null) {
        orphanFix.push(s.name);
      } else {
        (childrenMap[parent] = childrenMap[parent] || []).push(s.name);
      }
    });

    // ── 将 raw spec 转为输出行对象(字段数字化) ──
    function toRow(raw) {
      return {
        name: raw.name,
        status: raw.status,
        priority: raw.priority != null ? Number(raw.priority) : null,
        created: raw.created || null,
        updated: raw.updated || null,
        error: raw.error || null,
        task_done: num(raw.task_done),
        task_total: num(raw.task_total),
        verify_done: num(raw.verify_done),
        verify_total: num(raw.verify_total),
        verify_error: raw.verify_error || null,
        scenario_count: num(raw.scenario_count),
        total_duration: num(raw.total_duration),
        latest_run: raw.latest_run || null,
        latest_run_status: raw.latest_run_status || null,
        // fix 树字段(默认)
        depth: 0,
        isFixChild: false,
        orphan: false,
        children: null,
      };
    }

    // ── 生命周期排序比较器(§2 顺序) ──
    function cmp(aName, bName) {
      const a = byName[aName], b = byName[bName];
      const ra = _LIFECYCLE_RANK[a.status] != null ? _LIFECYCLE_RANK[a.status] : 99;
      const rb = _LIFECYCLE_RANK[b.status] != null ? _LIFECYCLE_RANK[b.status] : 99;
      if (ra !== rb) return ra - rb;
      // 同生命周期序内: created 倒序(与服务端一致)
      const ac = a.created || '', bc = b.created || '';
      if (!ac && !bc) return 0;
      if (!ac) return 1;
      if (!bc) return -1;
      return bc.localeCompare(ac);
    }

    // ── 递归展开树 ──
    const output = [];

    function pushTree(name, depth, orphan) {
      if (!byName[name]) return;
      const raw = byName[name];
      const row = toRow(raw);
      row.depth = depth;
      row.orphan = !!orphan;
      row.isFixChild = depth > 0;

      // 聚合子任务进度:父行 task_done/task_total = 所有子孙之和
      const childNames = (childrenMap[name] || []).sort(cmp);
      if (childNames.length > 0) {
        let aggDone = 0, aggTotal = 0;
        const childRows = [];
        childNames.forEach(cn => {
          pushTree(cn, depth + 1, orphan);
          // pushTree 已将子行 push 到 output; 从 output 尾部取回做聚合
          // (子行按顺序追加,此时 output 尾部即刚推入的)
        });
        // 收集该 name 的直接子行(从 output 中找 depth=depth+1 且 parent=name 的)
        // 更简单:用 toRow 直接聚合原始 raw 数据
        childNames.forEach(cn => {
          const cRaw = byName[cn];
          aggDone += num(cRaw.task_done);
          aggTotal += num(cRaw.task_total);
        });
        row.task_done = aggDone;
        row.task_total = aggTotal;
        row.children = childNames.map(cn => {
          // 从 output 中找到刚 push 的子行
          for (let i = output.length - 1; i >= 0; i--) {
            if (output[i].name === cn && output[i].depth === depth + 1) {
              return output[i];
            }
          }
          return null;
        }).filter(Boolean);
      }

      output.push(row);
    }

    roots.sort(cmp).forEach(rn => pushTree(rn, 0, false));
    orphanFix.sort(cmp).forEach(fn => pushTree(fn, 1, true));

    return output;
  }

  // ── adaptOverview ─────────────────────────────────────────
  // behavior.md §1: GET /api/overview → {projects, totals}
  // 输入为 totals 对象,输出所有字段数字化
  function adaptOverview(raw) {
    if (!raw || typeof raw !== 'object') {
      return { spec_count: 0, task_done: 0, task_total: 0, problems: 0, active_runs: 0 };
    }
    const t = raw.totals || raw; // 支持传整个 overview 或仅 totals
    return {
      spec_count: num(t.spec_count),
      task_done: num(t.task_done),
      task_total: num(t.task_total),
      problems: num(t.problems),
      active_runs: num(t.active_runs),
    };
  }

  // ── adaptProjects ─────────────────────────────────────────
  // behavior.md §1: GET /api/projects → {projects: [...]}
  // 输入为 projects 数组,输出每行字段数字化
  function adaptProjects(rawList) {
    if (!Array.isArray(rawList)) return [];
    return rawList.map(p => ({
      name: p.name,
      path: p.path,
      daemon: p.daemon || 'unknown',
      spec_count: num(p.spec_count),
      status_counts: p.status_counts || {},
      task_done: num(p.task_done),
      task_total: num(p.task_total),
      problems: num(p.problems),
      active_runs: num(p.active_runs),
      scenario_count: num(p.scenario_count),
      updated: p.updated || 0,
      discovered: !!p.discovered,
      exists: p.exists !== false,
      error: p.error || null,
    }));
  }

  // ── adaptSpecDetail ───────────────────────────────────────
  // behavior.md §1: GET /api/specs/<spec> → specDetail
  // verdict.summary 计数可能为字符串 "0",必须数字化
  function adaptSpecDetail(raw) {
    if (!raw || typeof raw !== 'object') return {};
    const d = Object.assign({}, raw);

    // verdict 计数数字化
    if (d.verdict && d.verdict.summary) {
      const s = Object.assign({}, d.verdict.summary);
      for (const k of Object.keys(s)) {
        if (s[k] !== null && s[k] !== undefined) s[k] = num(s[k], 0);
      }
      d.verdict = Object.assign({}, d.verdict, { summary: s });
    }

    // verify_progress 数字化
    if (d.verify_progress) {
      d.verify_progress = Object.assign({}, d.verify_progress, {
        total: num(d.verify_progress.total),
        done: num(d.verify_progress.done),
      });
    }

    // token_usage 数字化（add-cost-observability 2.1）
    if (d.token_usage && typeof d.token_usage === 'object') {
      d.token_usage = Object.assign({}, d.token_usage, {
        tokens_in: num(d.token_usage.tokens_in, 0),
        tokens_out: num(d.token_usage.tokens_out, 0),
        cost_usd: d.token_usage.cost_usd == null ? null : num(d.token_usage.cost_usd, 0),
        cost_available: !!d.token_usage.cost_available,
      });
    }

    // tasks 数字化
    if (Array.isArray(d.tasks)) {
      d.tasks = d.tasks.map(t => ({
        title: t.title,
        done: num(t.done),
        total: num(t.total),
        tasks: Array.isArray(t.tasks) ? t.tasks.map(st => ({
          id: st.id,
          desc: st.desc,
          done: !!st.done,
        })) : [],
      }));
    }

    return d;
  }

  // ── adaptAlerts ───────────────────────────────────────────
  // behavior.md §7: GET /api/alerts → {total_unhandled, projects, alerts}
  // 输入为 alerts 数组,输出保留核心字段
  function adaptAlerts(rawList) {
    if (!Array.isArray(rawList)) return [];
    return rawList.map(a => ({
      id: a.id,
      project: a.project || null,
      spec: a.spec || null,
      severity: a.severity || 'minor',
      created: a.created || null,
      description: a.description || '',
      evidence: a.evidence || '',
      action_taken: a.action_taken || null,
      recommended_action: a.recommended_action || '',
      handled: !!a.handled,
      // add-alert-auto-resolve D5：已解决区展示字段（自动解决/人工处理徽标、
      // 解决依据、解除时刻）；未处理项为 null
      handled_by: a.handled_by || null,
      resolve_note: a.resolve_note || null,
      handled_at: a.handled_at || null,
    }));
  }

  // ── adaptActivities ───────────────────────────────────────
  // behavior.md §7: GET /api/admin-activities
  // 输入为 activities 数组,输出保留核心字段
  function adaptActivities(rawList) {
    if (!Array.isArray(rawList)) return [];
    return rawList.map(a => ({
      id: a.id,
      kind: a.kind || null,
      admin_run_id: a.admin_run_id || null,
      spec: a.spec || null,
      signal_type: a.signal_type || null,
      summary: a.summary || null,
      actions_taken: a.actions_taken || a.action_taken || null,
      result: a.result || null,
      status: a.status || null,
      created: a.created || null,
      handled: !!a.handled,
      escalation_id: a.escalation_id || null,
      project: a.project || null,
    }));
  }

  // ── adaptConfig ───────────────────────────────────────────
  // behavior.md §6: GET /api/config
  // llm 无键时为 {}(不保证有 providers 数组——responseAdaptor 必须兜底)
  function adaptConfig(raw) {
    if (!raw || typeof raw !== 'object') raw = {};
    // llm 兜底
    const llm = raw.llm && typeof raw.llm === 'object' ? raw.llm : {};
    const providers = Array.isArray(llm.providers) ? llm.providers : [];
    // agents 兜底
    const agents = raw.agents && typeof raw.agents === 'object' ? raw.agents : {};
    const gates = raw.gates && typeof raw.gates === 'object' ? raw.gates : {};
    return {
      llm: { providers },
      agents: {
        models: agents.models || {},
        max_concurrent: num(agents.max_concurrent, 2),
        max_turns: num(agents.max_turns, 300),
        run_timeout_seconds: num(agents.run_timeout_seconds, 3600),
        daily_run_limit: num(agents.daily_run_limit, 50),
        token_budget_millions: num(agents.token_budget_millions, 50),
        impl_run_budget: num(agents.impl_run_budget, 4),
      },
      gates: {
        approve_mode: gates.approve_mode || 'manual',
      },
      scope: raw.scope || 'user',
      raw_exists: !!raw.raw_exists,
      sources: raw.sources || {},
      error: raw.error || null,
      project: raw.project || null,
    };
  }

  // ── buildConfigPayload ────────────────────────────────────
  // behavior.md §6: 三级回退 数字回退(numOr): 输入空/NaN → 回退快照 → 领域默认
  // 表单值 → 快照 → 默认
  function numOr(input, fallback, domainDefault) {
    if (input === null || input === undefined || input === '') {
      return (fallback != null ? fallback : domainDefault);
    }
    const raw = typeof input === 'string' ? input.trim() : input;
    if (raw === '') return (fallback != null ? fallback : domainDefault);
    const n = Number(raw);
    if (Number.isNaN(n)) return (fallback != null ? fallback : domainDefault);
    return n;
  }

  function buildConfigPayload(form, snapshot, defaults) {
    if (!form || typeof form !== 'object') form = {};
    if (!snapshot || typeof snapshot !== 'object') snapshot = {};
    if (!defaults || typeof defaults !== 'object') defaults = {};

    const loadedAgents = snapshot.agents || {};
    // form.agents 为表单中的数字字段(可能含 max_concurrent 等)
    const formAgents = form.agents && typeof form.agents === 'object' ? form.agents : {};

    // ── LLM providers ──
    // form.providers 为数组(form 顶层),或 form.llm.providers
    // 仅收完整行:后端校验要求 name/baseurl/apikey 均非空字符串(core/config.py
    // _validate_llm),不完整行入库必 400 且阻塞整份配置保存——对齐 v1
    // collectConfigData「仅收键值都非空的行」先例,未填完的行留在表单不落盘
    const isFilled = v => typeof v === 'string' && v.trim() !== '';
    const rawProviders = form.providers || (form.llm && form.llm.providers);
    const llmProviders = Array.isArray(rawProviders)
      ? rawProviders.filter(p => p && isFilled(p.name) && isFilled(p.baseurl) && isFilled(p.apikey))
      : [];

    // ── approve_mode ──
    let approveMode = 'manual';
    if (form.approve_mode) approveMode = form.approve_mode;
    else if (form.gates && form.gates.approve_mode) approveMode = form.gates.approve_mode;
    else if (snapshot.gates && snapshot.gates.approve_mode) approveMode = snapshot.gates.approve_mode;

    const payload = {
      llm: { providers: llmProviders },
      agents: {
        models: form.models || (form.agents && form.agents.models) || {},
        max_concurrent: numOr(formAgents.max_concurrent || form.max_concurrent, loadedAgents.max_concurrent, defaults.max_concurrent || 2),
        max_turns: numOr(formAgents.max_turns || form.max_turns, loadedAgents.max_turns, defaults.max_turns || 300),
        run_timeout_seconds: numOr(formAgents.run_timeout_seconds || form.run_timeout_seconds, loadedAgents.run_timeout_seconds, defaults.run_timeout_seconds || 3600),
        daily_run_limit: numOr(formAgents.daily_run_limit || form.daily_run_limit, loadedAgents.daily_run_limit, defaults.daily_run_limit || 50),
        token_budget_millions: numOr(formAgents.token_budget_millions || form.token_budget_millions, loadedAgents.token_budget_millions, defaults.token_budget_millions || 50),
        impl_run_budget: numOr(formAgents.impl_run_budget || form.impl_run_budget, loadedAgents.impl_run_budget, defaults.impl_run_budget || 4),
      },
      gates: {
        approve_mode: approveMode,
      },
    };

    return payload;
  }

  // ── validateChain ─────────────────────────────────────────
  // behavior.md §6: 链完整性校验(必填角色齐全、模型名存在)
  // chainValue: [{provider, model}, ...]  provider 信息列表
  // providers: [{name, model}, ...] LLM providers 列表
  // 返回 true 或错误文案
  function validateChain(chainValue, providers) {
    if (!Array.isArray(chainValue) || chainValue.length === 0) {
      return 'Agent 链为空，至少需要一行';
    }
    if (!Array.isArray(providers)) providers = [];
    const providerMap = {};
    providers.forEach(p => { providerMap[p.name] = p; });

    const missing = [];
    chainValue.forEach((row, i) => {
      if (!row.provider) {
        missing.push(`第 ${i + 1} 行未选择 Provider`);
        return;
      }
      // model 为空时检查 provider 默认模型
      const pDefault = providerMap[row.provider];
      if (!row.model && !(pDefault && pDefault.model)) {
        missing.push(`第 ${i + 1} 行（${row.provider}）无可用模型`);
      }
    });
    if (missing.length > 0) {
      return `模型缺失: ${missing.join('；')}`;
    }
    return true;
  }

  return {
    SPEC_LIFECYCLE,
    adaptSpecs,
    adaptOverview,
    adaptProjects,
    adaptSpecDetail,
    adaptAlerts,
    adaptActivities,
    adaptConfig,
    buildConfigPayload,
    validateChain,
  };
});
