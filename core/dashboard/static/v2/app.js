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
        // 将渲染器实例 + 当前 scoped 一并交给桥。scoped 来自 embed 实例(window.amisScoped),
        // 广播走 amisCore.dispatchGlobalEventForRenderer(eventName, renderer, scoped, data, action),
        // 该机制沿整棵渲染树触发所有匹配 onEvent 的组件(跨组件可达)。
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
