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

  fetch('/v2/pages/app.json?t=' + Date.now()).then(r => r.json()).then(appSchema => {
    // amis 6.13 的 app 组件要求页面用 children 分组才能渲染侧边栏(平铺 pages 不会
    // 生成导航);embed 默认按 location.hash 解析路由。导航 <a> 的 href 由 amis 生成为
    // 路径形式(/overview),这里在渲染后改写为 #/overview 风格,既与既有 #/xxx 链接
    // 一致,也契合 hash 路由(点击仍走 amis 内部导航,hashchange 监听同步 embed)。
    const amisScoped = amisLib.embed('#root', appSchema, {}, {
      theme: 'dark',
      location: parseHash(),
      jumpTo: (to) => { location.hash = to.startsWith('#') ? to : '#' + to; },
    });
    window.amisScoped = amisScoped;

    const fixNavHrefs = () => {
      const nav = document.querySelector('.dark-AsideNav');
      if (!nav) return;
      nav.querySelectorAll('a[href^="/"]').forEach((a) => {
        const h = a.getAttribute('href');
        if (h && h[0] === '/' && !h.startsWith('//')) a.setAttribute('href', '#' + h);
      });
    };
    const mo = new MutationObserver(fixNavHrefs);
    mo.observe(document.getElementById('root'), { childList: true, subtree: true });
    fixNavHrefs();

    window.addEventListener('hashchange', () => {
      amisScoped.updateProps({ location: parseHash() });
    });
  });
})();
