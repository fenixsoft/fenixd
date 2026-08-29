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
        if (window.Bridge && typeof window.Bridge.attach === 'function') {
          window.Bridge.attach(this, window.amisScoped);
        }
      }
      componentWillUnmount() {
        if (window.Bridge && window.Bridge._es) window.Bridge._es.close();
      }
      render() { return null; }
    }
    amisCore.registerRenderer({ type: 'sse-bridge', component: SSEBridge, autoVar: true });
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
  window.V2 = { route: parseHash };

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

  function buildShell(appSchema) {
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
    const items = nav.map((n, i) =>
      `<li class="v2-nav-item" data-url="${n.url}"><a href="#${n.url}">${n.icon ? `<i class="${n.icon}"></i> ` : ''}${n.label}</a></li>`
    ).join('');
    return `
      <div class="v2-shell">
        <aside class="v2-aside">
          <div class="v2-brand">Fenix</div>
          <nav class="v2-nav"><ul>${items}</ul></nav>
        </aside>
        <main class="v2-main">
          <div id="v2-content"></div>
        </main>
      </div>`;
  }

  function highlightNav() {
    const route = window.V2.route();
    document.querySelectorAll('.v2-nav-item').forEach((li) => {
      const u = li.getAttribute('data-url');
      const active = route.path === u || (u !== '/overview' && route.path.startsWith(u));
      li.classList.toggle('v2-nav-active', active);
    });
  }

  let contentScoped = null;

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
        adaptor: "return { status: 0, data: { rows: window.Adapters.adaptAlerts(payload.alerts || []), total_unhandled: (payload && payload.total_unhandled) || 0 } }"
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
    el.innerHTML = '';
    if (!pageSchema) {
      el.innerHTML = '<div class="v2-empty">页面不存在</div>';
      return;
    }
    // 注入路由参数到 AMIS 数据域,供页面 JSON 的 ${params[0]}/${params[1]} 使用
    const route = window.V2.route();
    const data = { params: route.params, query: route.query };
    // 壳级 SSE 桥:必须与页面组件处于同一棵 embed 树,广播才能沿渲染树触达各页 onEvent
    // 消费者(amisCore.dispatchGlobalEventForRenderer 依赖同一 scoped 实例)。sse-bridge 渲染
    // 器 render 为 null,仅承担 attach;这里把它前置注入页面 body,避免单独 embed 导致跨树不可达。
    const wrapped = Object.assign({}, pageSchema);
    wrapped.body = [{ type: 'sse-bridge' }, alertBannerSchema()].concat(Array.isArray(pageSchema.body) ? pageSchema.body : []);
    contentScoped = amisLib.embed(el, wrapped, { data, theme: 'dark' }, {});
    window.amisScoped = contentScoped;
    highlightNav();
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
        .v2-shell{display:flex;min-height:100vh;background:var(--body-bg,#1a1a1a);color:var(--text-color,#e8e8e8)}
        .v2-aside{width:200px;background:#232324;border-right:1px solid #383838;padding:12px 0}
        .v2-brand{font-size:1.2rem;font-weight:700;padding:8px 16px 16px}
        .v2-nav ul{list-style:none;margin:0;padding:0}
        .v2-nav-item a{display:block;padding:8px 16px;color:#b8b8b8;text-decoration:none}
        .v2-nav-item a:hover{background:#2e2e2f;color:#fff}
        .v2-nav-active>a{background:#313131;color:#fff;font-weight:600}
        .v2-main{flex:1;padding:20px;overflow:auto}
        .v2-empty{color:#888;padding:40px;text-align:center}
      `;
      document.head.appendChild(st);
    }
    loadAndRender();
    window.addEventListener('hashchange', loadAndRender);
  });
})();
