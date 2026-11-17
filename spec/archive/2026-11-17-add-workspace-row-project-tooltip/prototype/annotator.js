/*
 * fenix-prototype 注入式批注器（任务 2.1）
 *
 * 与组件栈无关的纯 DOM 操作：hover 高亮、点选元素、意见输入面板、意见列表、
 * POST /feedback 提交批注（锚点 + 文本 + 时间戳 + 轮次）；服务器不可达时降级
 * 为本地导出 JSON 文件（用户可把文件交给 agent）。
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
 */
(function () {
  "use strict";

  if (window.__fenixPrototypeAnnotator) return; // 防重复注入
  window.__fenixPrototypeAnnotator = true;

  var ANCHOR_ATTR = "data-proto-id";
  var FEEDBACK_URL = "/feedback";

  // ── 状态 ─────────────────────────────────────────────────────────────
  var state = {
    round: parseInt(
      new URLSearchParams(window.location.search).get("proto_round") ||
      String(window.__PROTO_FEEDBACK_ROUND__ || 1), 10) || 1,
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

  function remember(annotation, delivered) {
    annotation.delivered = delivered ? "server" : "local-only";
    state.pending.push(annotation);
    var item = el("div", "fpa-item");
    item.appendChild(el("div", "fpa-item-anchor",
      "#" + annotation.anchor + " · 轮次" + annotation.round +
      (delivered ? "" : "（未送达，已入本地导出）")));
    item.appendChild(el("div", "fpa-item-text", annotation.text));
    list.appendChild(item);
  }

  // 导出口径：仅导出 delivered !== "server" 的条目——已确认送达服务器的批注
  // 不再重复写入导出文件，避免 agent 侧回流时需自行去重
  function exportLocal() {
    var undelivered = state.pending.filter(function (a) { return a.delivered !== "server"; });
    if (!undelivered.length) { setStatus("没有未送达服务器的批注可导出。"); return; }
    var blob = new Blob([JSON.stringify({ round: state.round, feedback: undelivered },
                                        null, 2)], { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "feedback.json";
    a.click();
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
      exportLocal();
      setStatus("提交失败（" + reason + "），已导出未送达批注 feedback.json，可修正后重试。", true);
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
