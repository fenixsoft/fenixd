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
        // hello 只广播一次;refresh/state 走 500ms 前缘节流(behavior.md §0)
        if ((evt.type === 'refresh' || evt.type === 'state') && !shouldFire(name)) return;
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
