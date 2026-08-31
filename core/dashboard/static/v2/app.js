(function () {
  const amisLib = amisRequire('amis/embed');
  const amisCore = amisRequire('amis');
  const React = amisRequire('react');

  // ── SSE 桥壳级组件注册(设计 §3 退路方案)──────────────
  // app.json 中 header 用字符串 onMount 在 SDK 模式下不执行(实测),改由这里全局注册
  // 一个 custom 渲染器 `sse-bridge`;其 props.onAction 即 AMIS broadcast 派发入口,桥组件
  // 用它在渲染树内广播 sse:* 事件供各页面 onEvent 消费。注册一次即可。
  if (amisCore && React && React.Component && amisCore.registerRenderer &&
      !amisCore.resolveRenderer('sse-bridge')) {
    class SSEBridge extends React.Component {
      componentDidMount() {
        // 组件持有自己 attach 返回的 EventSource;unmount 时精确关闭。
        // 不可用全局 window.Bridge._es:快速切页时多个 bridge 实例并存,全局引用
        // 会被覆盖,旧连接泄漏占满浏览器 6 连接池 → 后续请求全部 pending(2026-08-31 事故)
        if (window.Bridge && typeof window.Bridge.attach === 'function') {
          this._es = window.Bridge.attach(this, window.amisScoped);
        }
      }
      componentWillUnmount() {
        if (this._es && typeof this._es.close === 'function') this._es.close();
      }
      render() { return null; }
    }
    amisCore.registerRenderer({ type: 'sse-bridge', component: SSEBridge, autoVar: true });
  }

  // ── run-stream 渲染器(替代 type:custom + 字符串 onMount)──────────────
  // SDK embed 模式下,type:"custom" 的字符串 onMount 不执行(实测与 sse-bridge 同源限制),
  // 故注册一个 React 渲染器 `run-stream`,由 componentDidMount 调 window.RunStream.mount(dom, props)。
  // props 即 AMIS 数据域透传(含 crud 行级 project/specName),关闭时由 onEvent.close 的
  // custom script 调 window.RunStream.active.dispose() 清理。注册一次即可。
  // 注意:不可用 !resolveRenderer('run-stream') 作守卫:该函数对未知类型返回占位而非 falsy,会误跳过注册。
  if (amisCore && React && React.Component && amisCore.registerRenderer) {
    class RunStream extends React.Component {
      componentDidMount() {
        this._inst = null;
        if (window.RunStream && typeof window.RunStream.mount === 'function' && this._dom) {
          const data = this.props.data || {};
          const base = Object.assign({}, data, this.props);
          // spec-detail 时间轴点击设置 window.__rsRunId,作为 run 模式 runId 兜底源
          // AMIS 数据域字段名是 run_id(下划线),mount 期望 runId(驼峰)
          if (base.mode === 'run' && !base.runId) {
            base.runId = window.__rsRunId || data.run_id || data.runId;
          }
          this._inst = window.RunStream.mount(this._dom, base);
          window.RunStream.active = this._inst || window.RunStream.active;
        }
      }
      componentWillUnmount() {
        if (this._inst && typeof this._inst.dispose === 'function') this._inst.dispose();
      }
      render() {
        const self = this;
        return React.createElement('div', {
          ref: function (n) { self._dom = n; },
          className: 'run-stream-mount',
        });
      }
    }
    amisCore.registerRenderer({ type: 'run-stream', component: RunStream, autoVar: true });
  }

  // ── hash 路由解析 ─────────────────────────────
  // 路由表(behavior.md §8):
  //   #/overview
  //   #/project/:name
  //   #/spec/:project/:name
  //   #/config/:project?tab=   (project 可省:#/config)
  //   #/activities/:project    (可省:#/activities)
  const ROUTES = [
    { page: 'overview',    re: /^\/overview$/ },
    { page: 'project',     re: /^\/project\/([^/?]+)/ },
    { page: 'spec-detail', re: /^\/spec\/([^/?]+)\/([^/?]+)/ },
    { page: 'config',      re: /^\/config(?:\/([^/?]+))?/ },
    { page: 'activities',  re: /^\/activities(?:\/([^/?]+))?/ },
  ];

  function parseHash() {
    const raw = decodeURIComponent(location.hash.replace(/^#/, '')) || '/overview';
    const [path, qs] = raw.split('?');
    const query = Object.fromEntries(new URLSearchParams(qs || ''));
    let page = 'overview';
    let params = [];
    for (const r of ROUTES) {
      const m = path.match(r.re);
      if (m) { page = r.page; params = m.slice(1); break; }
    }
    const search = qs ? '?' + qs : '';
    const hash = location.hash || '#/overview';
    const locationObj = { pathname: path, search, hash, query, state: {}, path };
    locationObj.key = hash;
    return Object.assign(locationObj, { page, params, query, path });
  }
  window.V2 = {
    route: parseHash,
    theme() { return localStorage.getItem('fenix.theme') || 'light'; },
  };

  // 页面 JSON 合并加载:app.json 仅保留壳(导航/路由占位,body 为空 page),各页面内容
  // 下沉到 pages/<name>.json;SDK 无 $ref 也无服务端渲染,故在加载期把各 pages/*.json
  // 按 url 前缀匹配深合并进 app.json 对应页后再 embed(计划 Task 5 Step 1 定案)。
  //
  // 注意:AMIS 的 `app` 组件在 embed 模式下无法按 hash 路由渲染页面内容(其页面匹配依赖
  // window.location.pathname,与 hash 路由不兼容,实测始终 404)。因此这里改为自建壳 + hash
  // 路由:用 app.json 的导航结构渲染侧边栏,正文区由本脚本按当前路由 embed 对应的
  // pages/<name>.json 到 #v2-content(AMIS 单页 embed,hash 路由完全可控)。
  const PAGE_NAMES = ['overview', 'project', 'spec-detail', 'config', 'activities'];
  const urlMap = {
    overview: '/overview', project: '/project/', 'spec-detail': '/spec/',
    config: '/config', activities: '/activities',
  };

    let initScopeSelect = null;
  function buildShell(appSchema) {
    // 全局项目作用域:顶栏选择器统一管理(localStorage 持久化,全页面生效)
    window.V2.scope = {
      project() { return localStorage.getItem('fenix.v2.scopeProject') || ''; },
      set(name) { localStorage.setItem('fenix.v2.scopeProject', name || ''); }
    };
    // 从 app.json 收集导航项(顶层 redirect + children 分组)
    const nav = [];
    for (const p of appSchema.pages) {
      if (p.redirect) continue; // redirect-only 页面不渲染为导航项(避免重复链接)
      if (p.children) {
        for (const c of p.children) {
          if (c.url) nav.push({ label: c.label, url: c.url, icon: c.icon });
        }
      } else if (p.url) {
        nav.push({ label: p.label, url: p.url, icon: p.icon });
      }
    }
    window.__navPages = nav;
    const savedW = parseInt(localStorage.getItem('fenix.v2.asideWidth') || '200', 10);
    const asideW = (savedW >= 140 && savedW <= 400) ? savedW : 200;
    return `
      <div class="v2-shell">
        <aside class="v2-aside" style="width:${asideW}px">
          <div class="v2-brand">Fenix<span class="v2-brand-sub">Dashboard</span></div>
          <nav class="v2-nav" id="v2-nav-mount"></nav>
          <div class="v2-resizer" title="拖拽调整侧栏宽度"></div>
        </aside>
        <main class="v2-main">
          <div class="v2-topbar">
            <div id="v2-breadcrumb" class="v2-breadcrumb"></div>
            <div class="v2-topbar-right">
              <span class="v2-scope-label">项目作用域</span>
              <select id="v2-scope-select" title="切换后概览/配置等页面按所选项目取数"></select>
            </div>
          </div>
          <div id="v2-content"></div>
        </main>
      </div>`;
  }

  // ── 侧栏 amis Nav 导航(自带二级菜单伸缩) ──
  // 「项目」的 children 为动态项目列表(fetch /api/projects);activeOn 随路由
  // 经 updateProps 原地刷新,整树不重建。
  let sideNavScoped = null;
  function navLinks(hash) {
    const pages = window.__navPages || [];
    const projects = window.__navProjects || [];
    const encode = (s) => '#/project/' + encodeURIComponent(s);
    return pages.map((n) => {
      if (n.label === '项目') {
        return {
          label: n.label,
          children: projects.map((p) => ({
            label: p.name,
            to: encode(p.name),
            activeOn: hash === encode(p.name) ? 'true' : 'false',
          })),
        };
      }
      return {
        label: n.label,
        to: '#' + n.url,
        activeOn: hash === '#' + n.url ? 'true' : 'false',
      };
    });
  }
  function renderSideNav() {
    const mount = document.getElementById('v2-nav-mount');
    if (!mount) return;
    if (sideNavScoped && typeof sideNavScoped.unmount === 'function') {
      try { sideNavScoped.unmount(); } catch (e) { /* 实例已失效时忽略 */ }
    }
    sideNavScoped = null;
    mount.innerHTML = '';
    const theme = window.V2.theme() === 'light' ? 'cxd' : 'dark';
    sideNavScoped = amisLib.embed(mount, { type: 'nav', stacked: true, links: navLinks(location.hash) }, { theme: theme }, {});
  }
  function updateSideNav() {
    if (sideNavScoped && typeof sideNavScoped.updateProps === 'function') {
      sideNavScoped.updateProps({ links: navLinks(location.hash) });
      return;
    }
    renderSideNav();
  }
  function refreshNavProjects() {
    fetch('/api/projects').then((r) => r.json()).then((d) => {
      window.__navProjects = d.projects || [];
      renderSideNav();
    }).catch(() => {});
  }

  let contentScoped = null;

  // ── 面包屑(壳级,随路由更新) ──
  // 概览为根;项目/SPEC 详情逐级下钻,层级可点击回跳。
  function crumbEsc(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }
  function updateBreadcrumb(route) {
    const el = document.getElementById('v2-breadcrumb');
    if (!el) return;
    const page = route.page;
    const p = route.params || [];
    const parts = [];
    if (page === 'overview') {
      parts.push('<span class="v2-crumb-cur">概览</span>');
    } else {
      parts.push('<a href="#/overview">概览</a>');
      if (page === 'project') {
        parts.push('<span class="v2-crumb-cur">项目:' + crumbEsc(decodeURIComponent(p[0] || '')) + '</span>');
      } else if (page === 'spec-detail') {
        parts.push('<a href="#/project/' + crumbEnc(p[0]) + '">项目:' + crumbEsc(decodeURIComponent(p[0] || '')) + '</a>');
        parts.push('<span class="v2-crumb-cur">SPEC:' + crumbEsc(decodeURIComponent(p[1] || '')) + '</span>');
      } else if (page === 'config') {
        parts.push('<span class="v2-crumb-cur">配置</span>');
      } else if (page === 'activities') {
        parts.push('<span class="v2-crumb-cur">运维记录</span>');
      }
    }
    el.innerHTML = parts.join('<span class="v2-crumb-sep">/</span>');
  }
  function crumbEnc(s) { return encodeURIComponent(decodeURIComponent(s || '')); }

  // ── 壳级告警横幅 service(跨所有路由可见) ──
  // design §决策:横幅整块可点开 Dialog 列表,空告警时横幅不可见
  // behavior.md §7:每条「标记已处理」POST /api/alerts/<id>/handled;全部清空 POST /api/alerts/clear
  // SSE alerts 事件 → reload 横幅
  function alertBannerSchema() {
    return {
      type: 'service',
      id: 'alert-banner',
      name: 'alert-banner',
      api: {
        url: '/api/alerts',
        adaptor: "return { status: 0, data: { rows: window.Adapters.adaptAlerts(payload.alerts || []), resolvedRows: window.Adapters.adaptAlerts((payload && payload.resolved) || []), total_unhandled: (payload && payload.total_unhandled) || 0 } }"
      },
      onEvent: {
        "sse:alerts": {
          actions: [{ actionType: 'reload', componentId: 'alert-banner' }]
        }
      },
      body: {
        type: 'tpl',
        visibleOn: '${rows.length > 0}',
        tpl: "<span id='alert-banner-strip' style='cursor:pointer;display:inline-block;padding:4px 12px;background:var(--danger);color:#fff;border-radius:4px;font-size:0.85rem'>⚠ ${rows.length} 条未处理告警</span>",
        onEvent: {
          click: {
            actions: [{
              actionType: 'dialog',
              args: {
                dialog: {
                  title: '未处理告警 · ${rows.length} 条',
                  size: 'lg',
                  body: [
                    {
                      type: 'table',
                      source: '${rows}',
                      columns: [
                        {
                          name: 'severity', label: '严重度', width: 70, type: 'tpl',
                          tpl: "<% if (data.severity === 'critical') { %><span class='label label-danger'>严重</span><% } else if (data.severity === 'major') { %><span class='label label-warning'>重要</span><% } else { %><span class='label label-default'>轻微</span><% } %>"
                        },
                        { name: 'project', label: '项目', width: 110, type: 'tpl', tpl: "${project || '—'}" },
                        { name: 'spec', label: 'SPEC', width: 130, type: 'tpl', tpl: "${spec || '—'}" },
                        {
                          name: 'description', label: '描述', type: 'tpl',
                          tpl: "<% if (data.handled) { %><s class='text-muted'><%= data.description %></s><% } else { %><%= data.description %><% } %>"
                        },
                        {
                          name: 'op', label: '操作', width: 110, type: 'button', level: 'link',
                          label: '标记已处理', disabledOn: '${handled}',
                          onEvent: {
                            click: {
                              actions: [
                                { actionType: 'ajax', args: { api: { method: 'post', url: "/api/alerts/${id}/handled?project=${project}" } } },
                                { actionType: 'reload', componentId: 'alert-banner' }
                              ]
                            }
                          }
                        }
                      ]
                    },
                    {
                      type: 'button', label: '全部清空', level: 'danger', className: 'm-t-sm',
                      confirmText: '确认清理所有告警事件?',
                      onEvent: {
                        click: {
                          actions: [
                            { actionType: 'ajax', args: { api: { method: 'post', url: '/api/alerts/clear' } } },
                            { actionType: 'reload', componentId: 'alert-banner' }
                          ]
                        }
                      }
                    },
                    // add-alert-auto-resolve D5：已解决告警折叠为「已解决 (N)」可
                    // 展开区（默认收起，不与待处理混排），展开项按 handled_by 区分
                    // 「自动解决/人工处理」徽标，显示 resolve_note 与 handled_at
                    {
                      type: 'container',
                      visibleOn: '${resolvedRows.length > 0}',
                      body: [
                        { type: 'divider' },
                        {
                          type: 'collapse-group',
                          defaultActiveKey: [],
                          body: [
                            {
                              type: 'collapse',
                              key: 'resolved',
                              title: '已解决 (${resolvedRows.length})',
                              body: {
                                type: 'table',
                                source: '${resolvedRows}',
                                columns: [
                                  {
                                    name: 'severity', label: '严重度', width: 70, type: 'tpl',
                                    tpl: "<% if (data.severity === 'critical') { %><span class='label label-danger'>严重</span><% } else if (data.severity === 'major') { %><span class='label label-warning'>重要</span><% } else { %><span class='label label-default'>轻微</span><% } %>"
                                  },
                                  { name: 'project', label: '项目', width: 110, type: 'tpl', tpl: "${project || '—'}" },
                                  { name: 'spec', label: 'SPEC', width: 130, type: 'tpl', tpl: "${spec || '—'}" },
                                  { name: 'description', label: '描述', type: 'tpl', tpl: "<%= data.description %>" },
                                  {
                                    name: 'resolve_note', label: '解决依据', type: 'tpl',
                                    tpl: "<% if (data.handled_by === 'auto-resolve') { %><span class='label label-success'>自动解决</span><% } else { %><span class='label label-info'>人工处理</span><% } %> <%= (data.resolve_note || '') %>"
                                  },
                                  { name: 'handled_at', label: '解除时刻', width: 160, type: 'tpl', tpl: "${handled_at || '—'}" }
                                ]
                              }
                            }
                          ]
                        }
                      ]
                    }
                  ]
                }
              }
            }]
          }
        }
      }
    };
  }

  function renderContent(pageName, pageSchema) {
    const el = document.getElementById('v2-content');
    if (!el) return;
    // embed 前必须显式卸载上一棵 React 树:innerHTML='' 绕过 React 生命周期,
    // 旧 sse-bridge 的 componentWillUnmount 不触发 → EventSource 泄漏 →
    // 占满浏览器 6 连接池,后续页面请求全部 pending(2026-08-31 卡死事故)
    if (contentScoped && typeof contentScoped.unmount === 'function') {
      try { contentScoped.unmount(); } catch (e) { /* 实例已失效时忽略 */ }
    }
    contentScoped = null;
    el.innerHTML = '';
    if (!pageSchema) {
      el.innerHTML = '<div class="v2-empty">页面不存在</div>';
      return;
    }
    // 注入路由参数到 AMIS 数据域,供页面 JSON 的 ${params[0]}/${params[1]} 使用
    const route = window.V2.route();
    updateBreadcrumb(route);
    const data = { params: route.params, query: route.query, theme: window.V2.theme() };
    // 主题:dark → dark.css + dark 主题;light → 禁用 dark.css + cxd 浅色主题
    const theme = window.V2.theme();
    const darkLink = document.querySelector('link[href$="dark.css"]');
    if (darkLink) darkLink.disabled = theme !== 'dark';
    document.documentElement.dataset.theme = theme;
    const shellEl = document.querySelector('.v2-shell');
    if (shellEl) shellEl.classList.toggle('v2-light', theme !== 'dark');
    // 壳级 SSE 桥:必须与页面组件处于同一棵 embed 树,广播才能沿渲染树触达各页 onEvent
    // 消费者(amisCore.dispatchGlobalEventForRenderer 依赖同一 scoped 实例)。sse-bridge 渲染
    // 器 render 为 null,仅承担 attach;这里把它前置注入页面 body,避免单独 embed 导致跨树不可达。
    const wrapped = Object.assign({}, pageSchema);
    wrapped.body = [{ type: 'sse-bridge' }, alertBannerSchema()].concat(Array.isArray(pageSchema.body) ? pageSchema.body : []);
    contentScoped = amisLib.embed(el, wrapped, { data, theme: theme === 'light' ? 'cxd' : 'dark' }, {});
    window.amisScoped = contentScoped;
    initScopeSelect();
    // 桥端无感推送依赖新页面的组件树挂载完成,挂载后推一次当前基线
    if (window.Bridge && typeof window.Bridge._push === 'function') {
      setTimeout(() => window.Bridge._push(), 50);
    }
    updateSideNav();
  }

  function loadAndRender() {
    const route = window.V2.route();
    const name = route.page;
    const url = '/v2/pages/' + name + '.json?t=' + Date.now();
    fetch(url).then((r) => { if (!r.ok) throw new Error('404'); return r.json(); })
      .then((schema) => renderContent(name, schema))
      .catch(() => renderContent(name, null));
  }

  Promise.all([
    fetch('/v2/pages/app.json?t=' + Date.now()).then((r) => r.json()),
  ]).then(([appSchema]) => {
    const root = document.getElementById('root');
    root.innerHTML = buildShell(appSchema);
    // 注入壳样式(避免依赖额外 css 文件;深色主题适配)
    if (!document.getElementById('v2-shell-style')) {
      const st = document.createElement('style');
      st.id = 'v2-shell-style';
      st.textContent = `
        body{margin:0}
        /* height 固定为视口:若用 min-height,长内容会把 shell 连同整页撑出滚动,
           content 的 flex 收缩随之失效(2026-08-31 双滚动条事故) */
        .v2-shell{display:flex;height:100vh;background:var(--body-bg,#1a1a1a);color:var(--text-color,#e8e8e8);font-family:system-ui,-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
        .v2-aside{position:relative;min-width:140px;max-width:400px;background:#232324;border-right:1px solid #383838;padding:12px 0;overflow-y:auto;flex-shrink:0}
        .v2-resizer{position:absolute;top:0;right:0;width:7px;height:100%;cursor:col-resize;z-index:20}
        .v2-resizer:hover,.v2-resizer.v2-resizing{background:rgba(59,130,246,.35)}
        .v2-brand{font-size:16px;font-weight:700;letter-spacing:.3px;padding:8px 16px 16px}
        .v2-brand-sub{color:var(--text-muted,#999);font-weight:400;margin-left:6px}
        /* 侧栏为 amis Nav 控件(stacked + 二级伸缩);挂载容器撑满侧栏 */
        #v2-nav-mount{padding:4px 0}
        #v2-nav-mount .amis-scope{height:100%}
        .v2-topbar{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:8px 20px;border-bottom:1px solid rgba(255,255,255,.08);flex-shrink:0}
        .v2-topbar-right{display:flex;align-items:center;gap:8px}
        .v2-breadcrumb{font-size:.9rem;display:flex;align-items:center;gap:6px;min-width:0;overflow:hidden;white-space:nowrap}
        .v2-breadcrumb a{color:var(--link-color,#7ab8ff);text-decoration:none}
        .v2-breadcrumb a:hover{text-decoration:underline}
        .v2-crumb-sep{color:var(--text-muted,#999);margin:0 2px}
        .v2-crumb-cur{font-weight:600}
        .v2-scope-label{font-size:.85rem;color:var(--text-muted,#999)}
        /* 项目面板网格:恢复原 cards 三列布局,面板不再占满整行 */
        .v2-proj-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:12px;align-items:stretch}
        /* 面板等高:缺失信息的项目与其余面板齐平;标题 14px 粗体,徽标内联在标题行 */
        .v2-proj-grid > [class*="-Panel"]{height:100%;display:flex;flex-direction:column}
        .v2-proj-grid > [class*="-Panel"] > [class*="-Panel-body"]{flex:1 1 auto}
        .v2-proj-grid [class*="-Panel-title"]{font-size:14px;font-weight:700;display:flex;align-items:center;gap:8px;flex-wrap:nowrap;white-space:nowrap}
        .v2-proj-grid [class*="-Panel-title"] .v2-status-pill{font-size:12px;font-weight:400}
        #v2-scope-select{background:#222;color:#e8e8e8;border:1px solid #444;border-radius:4px;padding:4px 8px}
        /* 列向 flex:#v2-content 弹性填满剩余高度。amis embed 会给挂载点加 .amis-scope 类,
           命中 sdk.css 的 height:100%,若 content 高度不定会把 main 撑出内滚(2026-08-31 双滚动条事故);
           长页面滚动收敛到 content 内部,topbar 固定。 */
        .v2-main{flex:1;display:flex;flex-direction:column;padding:0 20px 20px;overflow:hidden}
        #v2-content{flex:1 1 auto;min-height:0;overflow:auto}
        .v2-empty{color:#888;padding:40px;text-align:center}
        /* ── 概览 v1 对齐样式(值取自 v1 style.css,浅/深主题共用) ── */
        .v2-totals-wrap .v2-totals{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:12px}
        .v2-stat-tile{background:var(--background);border:1px solid var(--border-color,rgba(128,128,128,.25));border-radius:10px;padding:14px 16px;text-align:center}
        .v2-stat-tile .num{font-size:26px;font-weight:700;line-height:1.1;font-variant-numeric:tabular-nums;color:var(--text-color)}
        .v2-stat-tile .label{color:var(--text-muted,#898781);font-size:12px;margin-top:2px}
        .v2-critical{color:var(--danger,#d03b3b)!important}
        .v2-warning{color:var(--warning,#fab219)!important}
        .v2-status-pill{display:inline-flex;align-items:center;gap:5px;padding:2px 8px;border-radius:999px;font-size:12px;border:1px solid rgba(128,128,128,.3);color:var(--text-color,#e8e8e8);white-space:nowrap;line-height:1.5}
        .v2-st-good{color:#0ca30c;border-color:rgba(12,163,12,.45)}
        .v2-st-warning{color:#fab219;border-color:rgba(250,178,25,.45)}
        .v2-st-serious{color:#ec835a;border-color:rgba(236,131,90,.45)}
        .v2-st-critical{color:#d03b3b;border-color:rgba(208,59,59,.45)}
        .v2-st-info{color:#3987e5;border-color:rgba(57,135,229,.45)}
        .v2-st-muted{color:#898781}
        .v2-st-aqua{color:#199e70;border-color:rgba(25,158,112,.45)}
        .v2-daemon-pill::before{content:'';width:6px;height:6px;border-radius:50%;background:currentColor}
        .v2-card-meta{font-size:13px;color:var(--text-muted,#898781);display:flex;flex-direction:column;align-items:flex-start;gap:2px}
        .v2-daemon-row{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
        .v2-kv-row{display:flex;justify-content:space-between;font-size:13px;margin:5px 0;color:var(--text-color,#e8e8e8)}
        .v2-kv-row .v2-k{color:var(--text-muted,#898781)}
        .v2-kv-row .v2-v{font-variant-numeric:tabular-nums}
        .v2-progress{height:8px;background:rgba(128,128,128,.18);border-radius:999px;overflow:hidden;margin:8px 0 4px}
        .v2-progress .v2-fill{height:100%;border-radius:999px;background:#3987e5;transition:width .4s ease}
        .v2-progress .v2-fill.v2-bar-good{background:#0ca30c}
        .v2-progress .v2-fill.v2-bar-warn{background:#fab219}
        .v2-progress .v2-fill.v2-bar-serious{background:#ec835a}
        .v2-progress-labels{display:flex;justify-content:space-between;font-size:12px;color:var(--text-muted,#898781)}
        .v2-pills{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
      `;
      document.head.appendChild(st);
    }
    // amis 弹层(Select 下拉等)以内联 absolute 坐标按 .amis-scope 为参照系定位,
    // 但 SDK 未给 scope 根设 relative → 弹层落到 body 坐标系,横向偏移一个侧栏宽度。
    const scopeStyle = document.createElement('style');
    scopeStyle.textContent = '.v2-main .amis-scope{position:relative}' +
      '.v2-shell.v2-light{background:#f2f2f2;color:#333}' +
      '.v2-shell.v2-light .v2-aside{background:#fff;border-right:1px solid #e0e0e0}' +
      '.v2-shell.v2-light .v2-brand{color:#111}' +
      '.v2-shell.v2-light .v2-nav-item a{color:#555}' +
      '.v2-shell.v2-light .v2-nav-active a,.v2-shell.v2-light .v2-nav-item a:hover{color:#111;background:#e5e7eb}' +
      '.v2-shell.v2-light .v2-nav-parent-label,.v2-shell.v2-light .v2-subnav-empty{color:#7a7871}' +
      '.v2-shell.v2-light .v2-subnav-item a{color:#4a4944}' +
      '.v2-shell.v2-light .v2-subnav-item a:hover{background:#e5e7eb;color:#111}' +
      '.v2-shell.v2-light .v2-subnav-item.v2-subnav-active a{background:#e5e7eb;color:#111}' +
      '.v2-shell.v2-light #v2-scope-select{background:#fff;color:#333;border-color:#ccc}';
    document.head.appendChild(scopeStyle);
    loadAndRender();
    refreshNavProjects();
    window.addEventListener('hashchange', loadAndRender);
    // 顶栏作用域选择器:用户级(空) + 项目列表;切换后按路由类型联动
    initScopeSelect = function () {
      const sel = document.getElementById('v2-scope-select');
      if (!sel) return;
      if (sel.dataset.bound) { sel.value = window.V2.scope.project(); return; }
      sel.dataset.bound = '1';
      sel.innerHTML = '<option value="">用户级（跨项目默认）</option>';
      fetch('/api/projects').then((r) => r.json()).then((d) => {
        (d.projects || []).forEach((p) => {
          const o = document.createElement('option');
          o.value = p.name; o.textContent = p.name;
          sel.appendChild(o);
        });
        sel.value = window.V2.scope.project();
      }).catch(() => {});
      sel.addEventListener('change', () => {
        window.V2.scope.set(sel.value);
        const route = window.V2.route();
        if (route.page === 'project' && sel.value) location.hash = '#/project/' + encodeURIComponent(sel.value);
        else if (route.page === 'spec-detail' && sel.value && route.params[1]) location.hash = '#/spec/' + encodeURIComponent(sel.value) + '/' + route.params[1];
        else if ((route.page === 'project' || route.page === 'spec-detail') && !sel.value) location.hash = '#/overview';
        else loadAndRender();
      });
    };
    // 侧栏拖拽调宽:.v2-resizer 按住拖动,宽度 140-400px,持久化 localStorage
    (function bindResizer() {
      const aside = document.querySelector('.v2-aside');
      const rz = document.querySelector('.v2-resizer');
      if (!aside || !rz) return;
      rz.addEventListener('mousedown', (e) => {
        e.preventDefault();
        const startX = e.clientX;
        const startW = aside.getBoundingClientRect().width;
        rz.classList.add('v2-resizing');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
        const onMove = (ev) => {
          const w = Math.min(400, Math.max(140, Math.round(startW + ev.clientX - startX)));
          aside.style.width = w + 'px';
        };
        const onUp = () => {
          document.removeEventListener('mousemove', onMove);
          document.removeEventListener('mouseup', onUp);
          rz.classList.remove('v2-resizing');
          document.body.style.cursor = '';
          document.body.style.userSelect = '';
          localStorage.setItem('fenix.v2.asideWidth', String(Math.round(aside.getBoundingClientRect().width)));
        };
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
      });
    })();
    initScopeSelect();
    // 「进入」按钮 → 项目页。面板不整块点击(面板正文要可选中/复制),进入由按钮承担。
    // 类前缀随主题变化(dark-*/cxd-*),必须主题无关匹配。面板根 class 形如
    // "cxd-Panel cxd-Panel--default",不能简单排除 "-Panel-"(会连根排除),
    // 需逐个排除区域子类(body/heading/footer/btnToolbar/title/actions)。
    const PANEL_ROOT_SEL = '[class*="-Panel"]:not([class*="-Panel-body"]):not([class*="-Panel-heading"]):not([class*="-Panel-footer"]):not([class*="-Panel-btnToolbar"]):not([class*="-Panel-title"]):not([class*="-Panel-actions"])';
    document.getElementById('v2-content').addEventListener('click', (e) => {
      const btn = e.target.closest('button, [class*="-Button"]');
      if (!btn || !btn.textContent.trim().endsWith('进入')) return;
      const panel = btn.closest(PANEL_ROOT_SEL);
      if (!panel) return;
      const titleEl = panel.querySelector('[class*="-Panel-title"]');
      const name = titleEl && titleEl.textContent.trim();
      if (name) location.hash = '#/project/' + encodeURIComponent(name);
    });
  });
})();
