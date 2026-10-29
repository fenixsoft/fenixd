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
    online: true,            // /feedback 可达性（失败即降级本地导出）
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

  function moveHighlight(node) {
    var rect = node.getBoundingClientRect();
    highlight.style.top = rect.top + "px";
    highlight.style.left = rect.left + "px";
    highlight.style.width = rect.width + "px";
    highlight.style.height = rect.height + "px";
    highlightLabel.textContent = node.getAttribute(ANCHOR_ATTR) || "(无锚)";
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

  function exportLocal() {
    var blob = new Blob([JSON.stringify({ round: state.round, feedback: state.pending },
                                        null, 2)], { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "feedback.json";
    a.click();
    URL.revokeObjectURL(a.href);
    setStatus("已导出 feedback.json——把它交给 agent 即可回流批注。");
  }

  function submit() {
    var text = textarea.value.trim();
    if (!state.selected) { setStatus("请先点选页面中的区块", true); return; }
    if (!text) { setStatus("意见不能为空", true); return; }
    var annotation = buildAnnotation(text);
    fetch(FEEDBACK_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(annotation),
    }).then(function (resp) {
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      state.online = true;
      remember(annotation, true);
      setStatus("已提交到服务器。");
    }).catch(function () {
      state.online = false;
      remember(annotation, false);
      exportLocal();
    });
    textarea.value = "";
  }

  submitBtn.addEventListener("click", submit);
  exportBtn.addEventListener("click", exportLocal);

  // ── 全局交互（批注模式拦截点击，浏览模式放行）──────────────────────
  document.addEventListener("mousemove", function (ev) {
    if (!state.annotateMode) return;
    var node = resolveAnchor(ev.target);
    if (node) { moveHighlight(node); highlight.style.display = "block"; }
    else { highlight.style.display = "none"; }
  }, true);

  document.addEventListener("click", function (ev) {
    if (!state.annotateMode) return; // 浏览模式放行原型自身交互
    var node = resolveAnchor(ev.target);
    if (panel.contains(ev.target) || ev.target === highlight) return;
    ev.preventDefault();
    ev.stopPropagation();
    if (!node) { setStatus("该区域没有 " + ANCHOR_ATTR + " 锚，请点选带锚的关键区块", true); return; }
    addTarget(node);
    setStatus("已选区块，输入意见后提交。");
  }, true);

  modeBtn.addEventListener("click", function () {
    state.annotateMode = !state.annotateMode;
    modeBtn.textContent = state.annotateMode ? "浏览模式" : "批注模式";
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
  document.body.appendChild(highlight);
  document.body.appendChild(panel);
  setStatus("批注模式：点选区块 → 输入意见 → 提交（轮次 " + state.round + "）。");
})();
