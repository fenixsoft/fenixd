(function () {
  // SSE 桥:App 壳级 custom 组件(不随路由销毁,设计 §3)
  // 行为规格 §0:state 帧触发 overview 重拉 + 500ms 前缘节流;config 视图编辑豁免由 config 页自身处理
  window.BridgeTest = { lastEvent: null };

  const THROTTLE_MS = 500;
  const lastFired = {}; // eventName -> ts,前缘节流

  function shouldFire(name) {
    const now = Date.now();
    if (lastFired[name] && now - lastFired[name] < THROTTLE_MS) return false;
    lastFired[name] = now;
    return true;
  }

  // 桥组件挂在 app.json header(壳级),由 app.js 注册的 sse-bridge 渲染器在
  // componentDidMount 里调用 attach(renderer, scoped)。scoped 来自 embed 实例,广播走
  // 官方 BroadcastAction 同款机制:amisCore.dispatchGlobalEventForRenderer(eventName,
  // renderer, scoped, data, action),它沿整棵渲染树触发所有匹配 onEvent 配置的组件
  // (renderer-event.ts 的 getMatchedEventTargets,不校验 scoped,跨组件可达)。
  window.Bridge = {
    attach(renderer, scoped) {
      const amisCore = (typeof amisRequire === 'function') ? amisRequire('amis') : null;
      const dispatchGlobal = amisCore && amisCore.dispatchGlobalEventForRenderer
        ? amisCore.dispatchGlobalEventForRenderer : null;
      const dispatch = (name, evt) => {
        if (dispatchGlobal && scoped) {
          dispatchGlobal(name, renderer, scoped, evt, null);
          return true;
        }
        // 退路:渲染器自带 dispatchEvent(可能仅冒泡到祖先,不跨兄弟组件)
        if (renderer && typeof renderer.dispatchEvent === 'function') {
          renderer.dispatchEvent(name, evt);
          return true;
        }
        return false;
      };
      const es = new EventSource('/api/stream');
      // ── V1 同款无感数据流:帧数据经组件 setData 原地灌入,不走 amis reload(免 spinner/闪烁) ──
      // rows 为各项目行(形状同 /api/projects),seed 后由 state/refresh 帧增量维护。
      window.Bridge._rows = null;
      window.Bridge._push = function () {
        const sc = window.amisScoped;
        if (!sc || !window.Bridge._rows) return;
        const rows = Object.values(window.Bridge._rows);
        try {
          const stats = sc.getComponentById && sc.getComponentById('ov-stats');
          if (stats && typeof stats.setData === 'function') {
            const zero = {spec_count: 0, task_done: 0, task_total: 0, problems: 0, active_runs: 0};
            const totals = rows.reduce((a, r) => ({
              spec_count: a.spec_count + (r.spec_count || 0),
              task_done: a.task_done + (r.task_done || 0),
              task_total: a.task_total + (r.task_total || 0),
              problems: a.problems + (r.problems || 0),
              active_runs: a.active_runs + (r.active_runs || 0),
            }), zero);
            if (window.Adapters && window.Adapters.adaptOverview) {
              stats.setData(window.Adapters.adaptOverview({totals: totals}));
            }
          }
          const cards = sc.getComponentById && sc.getComponentById('ov-projects');
          if (cards && typeof cards.setData === 'function' && window.Adapters && window.Adapters.adaptProjects) {
            cards.setData({items: window.Adapters.adaptProjects(rows)});
          }
        } catch (e) { /* 组件未挂载(路由切换间隙)→ 下一帧重试 */ }
      };
      window.Bridge._seed = function () {
        fetch('/api/projects').then((r) => r.json()).then((d) => {
          const map = {};
          (d.projects || []).forEach((row) => { map[row.name] = row; });
          window.Bridge._rows = map;
          window.Bridge._push();
        }).catch(() => {});
      };
      window.Bridge._seed();
      es.onmessage = (e) => {
        if (!e.data) return; // 25s 心跳是注释帧,不进 onmessage;保险跳过空帧
        let evt;
        try { evt = JSON.parse(e.data); } catch { return; }
        window.BridgeTest.lastEvent = evt;
        if (evt.type === 'hello') window.Bridge.cid = evt.cid;  // Task 8 watch 订阅依赖
        // 纯测试辅助:state/refresh 广播次数反映节流后数量(Task 5 SSE 联动断言用)
        if (evt.type === 'state' || evt.type === 'refresh') {
          window.BridgeTest.reloadCount = (window.BridgeTest.reloadCount || 0) + 1;
        }
        const name = 'sse:' + evt.type;
        // state 帧:用帧内单项目数据增量维护 rows 后原地推送(V1 renderView 同型)
        if (evt.type === 'state' && evt.project && window.Bridge._rows) {
          const prev = window.Bridge._rows[evt.project] || {};
          const ov = evt.overview && (evt.overview.totals || evt.overview) || {};
          const patch = {name: evt.project};
          ['spec_count', 'task_done', 'task_total', 'problems', 'active_runs', 'status_counts', 'scenario_count', 'updated'].forEach((k) => {
            if (ov[k] !== undefined) patch[k] = ov[k];
          });
          window.Bridge._rows[evt.project] = Object.assign({}, prev, patch);
          window.Bridge._push();
          // spec-detail 页:帧内含当前查看 spec 的详情 → 原地灌入(V1 renderView 同型)
          try {
            const scNow = window.amisScoped;
            const route = (window.V2 && window.V2.route && window.V2.route()) || {};
            if (scNow && route.page === 'spec' && route.params && route.params[0] === evt.project && evt.details && evt.details[route.params[1]]) {
              const det = scNow.getComponentById && scNow.getComponentById('spec-detail');
              if (det && typeof det.setData === 'function' && window.Adapters && window.Adapters.adaptSpecDetail) {
                det.setData(window.Adapters.adaptSpecDetail(evt.details[route.params[1]]));
              }
            }
          } catch (e2) { /* 路由信息缺失时跳过,下一帧重试 */ }
        }
        // detail 帧:单 spec 详情推送 → 同上原地灌入
        if (evt.type === 'detail' && evt.project && evt.spec && evt.data) {
          try {
            const scNow = window.amisScoped;
            const route = (window.V2 && window.V2.route && window.V2.route()) || {};
            if (scNow && route.page === 'spec' && route.params && route.params[0] === evt.project && route.params[1] === evt.spec) {
              const det = scNow.getComponentById && scNow.getComponentById('spec-detail');
              if (det && typeof det.setData === 'function' && window.Adapters && window.Adapters.adaptSpecDetail) {
                det.setData(window.Adapters.adaptSpecDetail(evt.data));
              }
            }
          } catch (e3) { /* 忽略 */ }
        }
        // hello 只广播一次;refresh/state 走 500ms 前缘节流(behavior.md §0)
        if ((evt.type === 'refresh' || evt.type === 'state') && !shouldFire(name)) return;
        // refresh 心跳:静默重种子(框架外 fetch,零 spinner)后原地推送,替代 v1 的整体重拉
        if (evt.type === 'refresh') {
          window.Bridge._seed();
        }
        // 广播派发到渲染树内所有 onEvent 消费者
        if (dispatch(name, evt)) {
          window.BridgeTest.broadcastCount = (window.BridgeTest.broadcastCount || 0) + 1;
        }
      };
      es.onerror = () => console.error('[v2-bridge] SSE 连接异常,实时刷新已中断', new Date().toISOString());
      window.Bridge._es = es;
      return es;
    },
  };
})();
