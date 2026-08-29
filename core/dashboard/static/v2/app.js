(function () {
  const amisLib = amisRequire('amis/embed');

  // ── hash 路由解析 ─────────────────────────────
  // 路由表(behavior.md §8):
  //   #/overview
  //   #/project/:name
  //   #/spec/:project/:name
  //   #/config/:project?tab=   (project 可省:#/config)
  //   #/activities/:project    (可省:#/activities)
  const ROUTES = [
    { page: 'overview',   re: /^\/overview$/ },
    { page: 'project',    re: /^\/project\/([^/?]+)/ },
    { page: 'spec-detail', re: /^\/spec\/([^/?]+)\/([^/?]+)/ },
    { page: 'config',     re: /^\/config(?:\/([^/?]+))?/ },
    { page: 'activities', re: /^\/activities(?:\/([^/?]+))?/ },
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
    // AMIS embed 的 location 是 history 形态:app 渲染器按 location.pathname 匹配 pages[].url
    const locationObj = { pathname: path, search, hash, query, state: {}, path };
    locationObj.key = hash;
    return Object.assign(locationObj, { page, params, query, path });
  }
  window.V2 = { route: parseHash };

  fetch('/v2/pages/app.json?t=' + Date.now()).then(r => r.json()).then(appSchema => {
    const amisScoped = amisLib.embed('#root', appSchema, {
      // 数据域默认值:各页面 schema 里可用 ${params[0]} 等
    }, {
      theme: 'dark',
      location: parseHash(),
      jumpTo: (to, action) => { location.hash = to.startsWith('#') ? to : '#' + to; },
      updateLocation: (location, action) => {
        if (action?.actionType === 'url') { location.href = location; return; }
        const target = typeof location === 'string'
          ? location
          : (location.pathname || '') + (location.search || '');
        location.hash = target.startsWith('#') ? target : '#' + target;
      },
      isCurrentUrl: (to, location) => {
        if (!to) return false;
        const cur = parseHash();
        let i = 0;
        const pagePath = to.replace(/:[^/]+/g, () => cur.params[i++] || '');
        return pagePath === cur.path ? { params: cur.params } : false;
      },
      // 响应适配全局兜底:非 {status:0} 结构的 /api 响应原样透传,
      // 页面级适配用 adapters.js 处理(见各页面任务的 api.adaptor)
      responseAdaptor: (api, payload) => payload,
    });
    window.amisScoped = amisScoped;
  });

  window.addEventListener('hashchange', () => {
    window.amisScoped && window.amisScoped.updateProps({ location: parseHash() });
  });
})();
