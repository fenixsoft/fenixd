/*
 * fenix-prototype 注入式批注器（任务 2.1）
 *
 * 与组件栈无关的纯 DOM 操作：hover 高亮、点选元素、意见输入面板、意见列表、
 * POST 批注（锚点 + 文本 + 时间戳 + 轮次）到按页面路径自适应推导的批注端点
 * （dashboard 承载伺服时为 /api/proto/<project>/<spec>/feedback，根路径伺服
 * 形态兜底 /feedback）；服务器不可达时降级为本地导出 JSON 文件（用户可把
 * 文件交给 agent）。
 *
 * 注入方式（原型 HTML 内）：
 *   <script src="annotator.js" defer></script>
 *
 * 轮次（round）来源优先级：URL 查询参数 ?proto_round=N > 全局
 * window.__PROTO_FEEDBACK_ROUND__ > 默认 1。agent 迭代原型后引导用户带
 * 新轮次参数刷新，批注即自带轮次号。
 *
 * 批注 JSON schema（单条）：
 *   { "anchor": "<data-proto-id>", "text": "<意见>",
 *     "timestamp": "<ISO8601>", "round": <int>,
 *     "element": { "tag": "<tag>", "text": "<元素文本快照>" } }
 *
 * 运行时在单条批注上附加两个内部字段（POST 请求体不带）：
 *   delivered —— 服务器送达状态："server"=已确认送达批注端点；
 *     "local-only"=未送达服务器（本地导出文件中的条目恒为此值，表示该
 *     批注只能经导出文件回流）。
 *   exportedAt —— 已写入过本地导出文件的标记（ISO8601 时刻，仅内存
 *     状态，不序列化进导出文件），用于避免同一批注被重复导出。
 */
(function () {
  "use strict";

  if (window.__fenixPrototypeAnnotator) return; // 防重复注入
  window.__fenixPrototypeAnnotator = true;

  var ANCHOR_ATTR = "data-proto-id";
  // 批注提交端点随伺服形态自适应（dashboard 承载后同一页面 URL 可能是
  // /proto/<project>/<spec>/index.html 或 /proto/<project>/<spec>/）：
  // 命中 dashboard 原型通道时按页面 pathname 推导
  // /api/proto/<project>/<spec>/feedback（捕获段原样传递，不做二次编码——
  // pathname 里的 percent-encoding 保持原样即可与服务端 unquote 对上）；
  // 其余形态（独立 serve_prototype.py 的根路径伺服）兜底 "/feedback"。
  // file:// 打开时 fetch 不可用，走本地导出降级，本值不参与。
  var FEEDBACK_URL = (function () {
    var m = window.location.pathname.match(/^\/proto\/([^/]+)\/([^/]+)(?:\/|$)/);
    return m ? "/api/proto/" + m[1] + "/" + m[2] + "/feedback" : "/feedback";
  })();

  // ── 状态 ─────────────────────────────────────────────────────────────
  // 轮次解析按「存在性」判定：URL 参数与全局量显式传入的 0（契约外但为
  // 合法整数）按原值保留，不被静默改写成默认轮次；仅对缺失（null/
  // undefined）与解析失败（NaN）兜底默认 1，优先级链保持不变
  function resolveRound() {
    var urlRound = new URLSearchParams(window.location.search).get("proto_round");
    if (urlRound !== null) {
      var n = parseInt(urlRound, 10);
      return isNaN(n) ? 1 : n;
    }
    var globalRound = window.__PROTO_FEEDBACK_ROUND__;
    if (globalRound !== undefined && globalRound !== null) {
      var g = parseInt(String(globalRound), 10);
      return isNaN(g) ? 1 : g;
    }
    return 1;
  }

  var state = {
    round: resolveRound(),
    selected: null,          // 当前点选的带锚元素
    pending: [],             // 本会话已提交/待导出的批注
    annotateMode: true,      // true=点选批注（拦截点击）；false=浏览（放行点击）
  };

  // ── 工具 ─────────────────────────────────────────────────────────────
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function resolveAnchor(node) {
    while (node && node !== document.body) {
      if (node.getAttribute && node.getAttribute(ANCHOR_ATTR)) return node;
      node = node.parentNode;
    }
    return null;
  }

  function elementSnapshot(node) {
    return { tag: (node.tagName || "").toLowerCase(),
             text: (node.textContent || "").replace(/\s+/g, " ").trim().slice(0, 80) };
  }

  // ── hover 高亮 ───────────────────────────────────────────────────────
  var highlight = el("div", "fpa-highlight");
  var highlightLabel = el("div", "fpa-highlight-label", "");
  highlight.appendChild(highlightLabel);
  // 初始隐藏：position:fixed 未设 top/left 时元素停留在 body 末尾静态位置，
  // label 自带橙色背景即使为空也渲染色块——挂载后到首次 mousemove 前（触屏
  // 或无鼠标设备上可长期存在）页面底部会残留橙色残影；首次命中锚点时由
  // mousemove 处置为 block 正常显示
  highlight.style.display = "none";
  var hoveredNode = null; // 最近悬停的带锚元素，scroll/resize 后重算高亮位置用

  function moveHighlight(node) {
    var rect = node.getBoundingClientRect();
    highlight.style.top = rect.top + "px";
    highlight.style.left = rect.left + "px";
    highlight.style.width = rect.width + "px";
    highlight.style.height = rect.height + "px";
    highlightLabel.textContent = node.getAttribute(ANCHOR_ATTR) || "(无锚)";
  }

  // 高亮框按 getBoundingClientRect 的视口坐标定位 position:fixed，
  // 页面滚动（滚轮不触发 mousemove）或窗口缩放后须按最近悬停元素重算，
  // 否则高亮框停留在旧视口位置与实际元素错位
  function refreshHighlight() {
    if (!state.annotateMode || !hoveredNode) return;
    moveHighlight(hoveredNode);
  }

  // ── 面板（意见输入 + 意见列表）──────────────────────────────────────
  var panel = el("div", "fpa-panel");
  var head = el("div", "fpa-head");
  var title = el("strong", null, "原型批注");
  var modeBtn = el("button", "fpa-btn fpa-mode", "浏览模式");
  var collapseBtn = el("button", "fpa-btn", "—");
  head.appendChild(title);
  var spacer = el("span", "fpa-spacer");
  head.appendChild(spacer);
  head.appendChild(modeBtn);
  head.appendChild(collapseBtn);

  var targetLine = el("div", "fpa-target", "点选页面中的区块开始批注（当前：未选择）");
  var textarea = el("textarea", "fpa-input");
  textarea.placeholder = "输入意见，如：表格这里要加筛选";
  var submitBtn = el("button", "fpa-btn fpa-submit", "提交批注");
  var exportBtn = el("button", "fpa-btn fpa-export", "导出 JSON（服务器不可达时）");
  var statusLine = el("div", "fpa-status", "");
  var listTitle = el("div", "fpa-list-title", "已提交意见");
  var list = el("div", "fpa-list");

  var body = el("div", "fpa-body");
  body.appendChild(targetLine);
  body.appendChild(textarea);
  var row = el("div", "fpa-row");
  row.appendChild(submitBtn);
  row.appendChild(exportBtn);
  body.appendChild(row);
  body.appendChild(statusLine);
  body.appendChild(listTitle);
  body.appendChild(list);
  panel.appendChild(head);
  panel.appendChild(body);

  function setStatus(text, isError) {
    statusLine.textContent = text;
    statusLine.className = "fpa-status" + (isError ? " fpa-status-error" : "");
  }

  function addTarget(node) {
    state.selected = node;
    var anchor = node.getAttribute(ANCHOR_ATTR);
    targetLine.textContent = "当前选择锚：" + anchor + "　" +
      elementSnapshot(node).text.slice(0, 24);
  }

  // ── 提交（POST /feedback，失败降级本地导出）────────────────────────
  function buildAnnotation(text) {
    return {
      anchor: state.selected.getAttribute(ANCHOR_ATTR),
      text: text,
      timestamp: new Date().toISOString(),
      round: state.round,
      element: elementSnapshot(state.selected),
    };
  }

  // annotation 对象 → 意见列表节点的映射：提交成功做数据层去重时按它
  // 同步移除该批注此前提交失败残留的意见列表节点。节点引用不能作为可
  // 枚举属性挂在 annotation 上——导出与 POST 都会序列化批注对象，DOM
  // 节点会污染序列化结果
  var itemEls = new Map();

  function remember(annotation, delivered) {
    annotation.delivered = delivered ? "server" : "local-only";
    state.pending.push(annotation);
    var item = el("div", "fpa-item");
    item.appendChild(el("div", "fpa-item-anchor",
      "#" + annotation.anchor + " · 轮次" + annotation.round +
      (delivered ? "" : "（未送达，已入本地导出）")));
    item.appendChild(el("div", "fpa-item-text", annotation.text));
    list.appendChild(item);
    itemEls.set(annotation, item);
  }

  // 移除批注对应的意见列表节点（数据层去重时同步回收 DOM，防止列表
  // 继续显示「未送达，已入本地导出」的误导性旧条目）
  function discardItemEl(annotation) {
    var node = itemEls.get(annotation);
    if (node && node.parentNode) node.parentNode.removeChild(node);
    itemEls.delete(annotation);
  }

  // 导出口径：仅导出尚未交付的条目——delivered 非 "server"（未确认送达
  // 服务器）且无 exportedAt 标记（未写入过导出文件）。已确认送达服务器
  // 的批注与已写入过导出文件的批注都不再重复写入导出文件，避免 agent 侧
  // 回流时需自行去重
  function exportLocal() {
    var undelivered = state.pending.filter(function (a) {
      return a.delivered !== "server" && !a.exportedAt;
    });
    if (!undelivered.length) { setStatus("没有未送达服务器的批注可导出。"); return; }
    var blob = new Blob([JSON.stringify({ round: state.round, feedback: undelivered },
                                        null, 2)], { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "feedback.json";
    a.click();
    // 已写入本次导出文件的条目打上 exportedAt 标记（仅内存状态，导出文件
    // 不含此字段；delivered 保持 "local-only" 如实反映未送达服务器）：
    // 再次点击导出或再次提交失败触发自动导出时不再重复携带旧批注，防止
    // 多份导出文件间出现重复副本
    var exportedAt = new Date().toISOString();
    undelivered.forEach(function (item) { item.exportedAt = exportedAt; });
    // 延迟回收 object URL：同步 revoke 可能中止尚未启动的下载
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
    setStatus("已导出 feedback.json——把它交给 agent 即可回流批注。");
  }

  function submit() {
    var text = textarea.value.trim();
    if (!state.selected) { setStatus("请先点选页面中的区块", true); return; }
    if (!text) { setStatus("意见不能为空", true); return; }
    var annotation = buildAnnotation(text);
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, 8000);
    submitBtn.disabled = true; // 在飞防重：8 秒超时窗口内重复点击不再重复 POST
    setStatus("提交中…");
    fetch(FEEDBACK_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(annotation),
      signal: controller.signal,
    }).then(function (resp) {
      clearTimeout(timer);
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      // 同一意见此前提交失败残留的未送达条目在此移除（按 anchor + text +
      // round 同键匹配，delivered !== "server" 覆盖未送达的全部形态——
      // 含已写入过导出文件的）：服务器已收到本条（成功回调），未被导出过
      // 的残留旧条目会被后续导出重复携带；数据层移除的同时回收意见列表
      // 中的旧节点，避免列表同时显示旧「未送达」与新的已送达条目误导用户
      // 与 agent 回流判断
      state.pending = state.pending.filter(function (a) {
        var stale = a.delivered !== "server" &&
                    a.anchor === annotation.anchor &&
                    a.text === annotation.text &&
                    a.round === annotation.round;
        if (stale) discardItemEl(a);
        return !stale;
      });
      remember(annotation, true);
      textarea.value = ""; // 仅在确认送达后清空；失败时保留原文便于用户修正重试
      setStatus("已提交到服务器。");
      submitBtn.disabled = false;
    }).catch(function (err) {
      clearTimeout(timer);
      // 失败归因：区分超时中止 / HTTP 非 2xx / 网络不可达，便于用户对症重试
      var reason;
      if (err && err.name === "AbortError") reason = "提交超时（8 秒无响应）";
      else if (err && err.message && err.message.indexOf("HTTP ") === 0) reason = err.message;
      else reason = "网络不可达";
      remember(annotation, false);
      // 服务器明确拒绝（HTTP 4xx，如参数校验失败/端点不存在）：原样重试同
      // 样必败，自动导出文件对回流无帮助且多次失败会连续触发多次下载——
      // 只提示修正后重试；超时/网络不可达/服务器故障才降级为自动导出
      if (reason.indexOf("HTTP 4") === 0) {
        setStatus("提交失败（" + reason + "），服务器拒绝了该批注，请修正后再提交。", true);
      } else {
        exportLocal();
        setStatus("提交失败（" + reason + "），已导出未送达批注 feedback.json，可修正后重试。", true);
      }
      submitBtn.disabled = false;
    });
  }

  submitBtn.addEventListener("click", submit);
  exportBtn.addEventListener("click", exportLocal);

  // ── 全局交互（批注模式拦截点击，浏览模式放行）──────────────────────
  document.addEventListener("mousemove", function (ev) {
    if (!state.annotateMode) return;
    hoveredNode = resolveAnchor(ev.target);
    if (hoveredNode) { moveHighlight(hoveredNode); highlight.style.display = "block"; }
    else { highlight.style.display = "none"; }
  }, true);

  // scroll 用捕获监听：内部滚动容器的 scroll 事件不冒泡，捕获阶段可统一接住
  window.addEventListener("scroll", refreshHighlight, true);
  window.addEventListener("resize", refreshHighlight);

  document.addEventListener("click", function (ev) {
    if (!state.annotateMode) return; // 浏览模式放行原型自身交互
    var node = resolveAnchor(ev.target);
    if (panel.contains(ev.target)) return;
    ev.preventDefault();
    ev.stopPropagation();
    if (!node) { setStatus("该区域没有 " + ANCHOR_ATTR + " 锚，请点选带锚的关键区块", true); return; }
    addTarget(node);
    setStatus("已选区块，输入意见后提交。");
  }, true);

  modeBtn.addEventListener("click", function () {
    state.annotateMode = !state.annotateMode;
    modeBtn.textContent = state.annotateMode ? "浏览模式" : "批注模式";
    hoveredNode = null;
    highlight.style.display = "none";
    setStatus(state.annotateMode ? "批注模式：点选区块即选中。" : "浏览模式：原型可正常点击。");
  });

  collapseBtn.addEventListener("click", function () {
    var hidden = body.style.display === "none";
    body.style.display = hidden ? "" : "none";
    collapseBtn.textContent = hidden ? "—" : "+";
  });

  // ── 注入样式与挂载 ──────────────────────────────────────────────────
  var style = document.createElement("style");
  style.textContent = [
    ".fpa-highlight{position:fixed;z-index:2147483646;pointer-events:none;",
    "outline:2px solid #fa8c16;background:rgba(250,140,22,.08);}",
    ".fpa-highlight-label{position:absolute;top:-20px;left:0;font:12px/20px monospace;",
    "background:#fa8c16;color:#fff;padding:0 6px;border-radius:2px;white-space:nowrap;}",
    ".fpa-panel{position:fixed;right:12px;bottom:12px;width:300px;z-index:2147483647;",
    "background:#fff;border:1px solid #d9d9d9;border-radius:8px;",
    "box-shadow:0 4px 16px rgba(0,0,0,.18);font:13px/1.5 -apple-system,sans-serif;color:#333;}",
    ".fpa-head{display:flex;align-items:center;gap:6px;padding:8px 10px;",
    "border-bottom:1px solid #f0f0f0;}",
    ".fpa-spacer{flex:1;}",
    ".fpa-body{padding:10px;display:flex;flex-direction:column;gap:8px;}",
    ".fpa-target{color:#666;font-size:12px;}",
    ".fpa-input{width:100%;box-sizing:border-box;height:56px;resize:vertical;",
    "border:1px solid #d9d9d9;border-radius:4px;padding:6px;}",
    ".fpa-row{display:flex;gap:8px;}",
    ".fpa-btn{border:1px solid #d9d9d9;background:#fff;border-radius:4px;",
    "padding:2px 10px;cursor:pointer;font-size:12px;}",
    ".fpa-submit{background:#1677ff;color:#fff;border-color:#1677ff;}",
    ".fpa-status{color:#888;font-size:12px;min-height:1em;}",
    ".fpa-status-error{color:#cf1322;}",
    ".fpa-list-title{font-weight:600;border-top:1px solid #f0f0f0;padding-top:6px;}",
    ".fpa-list{max-height:140px;overflow:auto;display:flex;flex-direction:column;gap:6px;}",
    ".fpa-item-anchor{font:11px monospace;color:#1677ff;}",
    ".fpa-item-text{color:#555;}",
  ].join("");
  document.head.appendChild(style);

  // 注入约定是 <script defer>（保证 body 已解析）；若被放进 <head> 且漏写
  // defer，此处 document.body 尚为 null——降级为 DOMContentLoaded 后挂载，
  // 并在控制台提示注入偏差，避免整个批注器静默失效
  function mount() {
    document.body.appendChild(highlight);
    document.body.appendChild(panel);
    setStatus("批注模式：点选区块 → 输入意见 → 提交（轮次 " + state.round + "）。");
  }
  if (document.body) {
    mount();
  } else {
    console.warn("[fenix-prototype] annotator.js 应以 <script defer> 注入（当前 body 未解析），已延迟至 DOMContentLoaded 挂载。");
    document.addEventListener("DOMContentLoaded", mount);
  }
})();
