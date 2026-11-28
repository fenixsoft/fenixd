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
 * uidebug 模式（add-fenix-ui-debug，代理页注入时先行设定
 * window.__FENIX_ANNOTATOR_MODE__="uidebug"）：端点推导改走
 * /uidebug/<project>/<session>/ 代理通道；锚不再限定 data-proto-id，
 * 任意元素可点选，锚值为即时生成的 CSS selector（唯一 id 祖先截断的
 * nth-of-type 链）；批注附 page 字段（代理内 pathname+search）；请求用
 * 代理运行时补丁备份的原生 fetch（window.__fenixUidDebugNative.fetch），
 * 不经代理改写。原型模式（默认）行为与历史完全一致。
 *
 * 批注管理（2026-11-28 批注功能自身优化，仅 uidebug 模式）：批注端点支持
 * GET 列表 / POST 带 id 重编辑 / DELETE ?id= 删单条；面板「已提交意见」
 * 改为服务器列表真相源（含删除/编辑按钮），提交成功后整表刷新。
 *
 * 样式隔离（2026-11-28 批注功能自身优化 2）：面板与高亮框全部挂进 Shadow
 * DOM——宿主页的全局样式表（如 dashboard 深色主题的 body/button 配色）
 * 不再命中批注器 UI；可继承属性（color/font）仍会经宿主元素渗入，在
 * host 元素上显式重置基调兜住。事件从 shadow 冒出到 document 时 target
 * 被重定向为 host 元素，点选拦截按 ev.target === host 排除。
 *
 * 轮次（round）来源优先级：URL 查询参数 ?proto_round=N > 全局
 * window.__PROTO_FEEDBACK_ROUND__ > 默认 1。agent 迭代原型后引导用户带
 * 新轮次参数刷新，批注即自带轮次号。
 *
 * 批注 JSON schema（单条）：
 *   { "anchor": "<data-proto-id>", "text": "<意见>",
 *     "timestamp": "<ISO8601>", "round": <int>,
 *     "element": { "tag": "<tag>", "text": "<元素文本快照>" } }
 *   uidebug 模式 anchor 为 CSS selector，并附加 "page": "<代理内路径>"；
 *   id 由服务端补发（追加响应回带），删除/重编辑按它寻址
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
  // uidebug 模式开关：代理注入的行内脚本先于本文件执行，全局量此处读取
  // 即为注入意图；普通原型页无该量，走原型分支
  var UIDEBUG = window.__FENIX_ANNOTATOR_MODE__ === "uidebug";
  // 批注提交端点随伺服形态自适应（dashboard 承载后同一页面 URL 可能是
  // /proto/<project>/<spec>/index.html 或 /proto/<project>/<spec>/）：
  // 命中 dashboard 原型通道时按页面 pathname 推导
  // /api/proto/<project>/<spec>/feedback（捕获段原样传递，不做二次编码——
  // pathname 里的 percent-encoding 保持原样即可与服务端 unquote 对上）；
  // uidebug 模式按代理页 pathname 推导 /api/uidebug/<project>/<session>/
  // feedback；其余形态（独立 serve_prototype.py 的根路径伺服）兜底 "/feedback"。
  // file:// 打开时 fetch 不可用，走本地导出降级，本值不参与。
  var FEEDBACK_URL = (function () {
    if (UIDEBUG) {
      var um = window.location.pathname.match(/^\/uidebug\/([^/]+)\/([^/]+)(?:\/|$)/);
      return um ? "/api/uidebug/" + um[1] + "/" + um[2] + "/feedback" : "/feedback";
    }
    var m = window.location.pathname.match(/^\/proto\/([^/]+)\/([^/]+)(?:\/|$)/);
    return m ? "/api/proto/" + m[1] + "/" + m[2] + "/feedback" : "/feedback";
  })();

  // ── 状态 ─────────────────────────────────────────────────────────────
  // 轮次解析按「存在性」判定：URL 参数与全局量显式传入的 0（契约外但为
  // 合法整数）按原值保留，不被静默改写成默认轮次；仅对缺失（null/
  // undefined）与解析失败兜底默认 1，优先级链保持不变。URL 参数走严格
  // 整串校验（/^\d+$/）：'3abc'、' 3' 这类部分可解析的杂质输入不按前缀
  // 数字静默接受，一律兜底默认 1；全局量维持 parseInt+NaN 兜底（数字
  // 字面量直设，无杂质输入面）
  function resolveRound() {
    var urlRound = new URLSearchParams(window.location.search).get("proto_round");
    if (urlRound !== null) {
      if (!/^\d+$/.test(urlRound)) return 1;
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
  var editingId = null;     // uidebug 重编辑态：正在改写的批注 id（原型模式恒 null）

  // ── 工具 ─────────────────────────────────────────────────────────────
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // Shadow DOM 隔离（详见文件头注释）：面板/高亮全部挂进 shadow root。
  // attachShadow 不可用（过于陈旧的浏览器）时降级为历史光 DOM 挂载形态
  // （style 进 head、UI 进 body）——功能不缺失，仅失去样式隔离。
  var shadowHost = document.createElement("div");
  shadowHost.id = "fpa-root";
  // 可继承属性兜底：宿主页的 body/button 配色（如深色主题 color:#fff）
  // 会穿过 shadow 边界继承进来，host 元素上显式重置基调
  shadowHost.style.cssText =
    "color:#333;font:13px/1.5 -apple-system,'PingFang SC','Microsoft YaHei',sans-serif;";
  var mountRoot = null;
  try {
    mountRoot = shadowHost.attachShadow({ mode: "open" });
  } catch (e) { mountRoot = null; }
  var styleParent = mountRoot || document.head;
  var uiParent = mountRoot || document.body;

  // uidebug：请求统一走代理补丁备份的原生 fetch——目标应用可能再包装
  // fetch，原生通道保证批注端点不被代理改写（FEEDBACK_URL 本身在豁免
  // 前缀内，此为纵深防线）；原型模式该全局量不存在，回退当前 fetch
  function nativeFetch(url, opts) {
    var doFetch = (window.__fenixUidDebugNative &&
                   window.__fenixUidDebugNative.fetch) || fetch.bind(window);
    return doFetch(url, opts);
  }

  function resolveAnchor(node) {
    if (UIDEBUG) {
      // uidebug：任意元素皆可为锚（批注器自身 UI 与 shadow host 除外）
      if (!node || node.nodeType !== 1) return null;
      if (node === highlight || node === shadowHost) return null;
      if (panel && (panel.contains(node) || node === panel)) return null;
      return node;
    }
    while (node && node !== document.body) {
      if (node.getAttribute && node.getAttribute(ANCHOR_ATTR)) return node;
      node = node.parentNode;
    }
    return null;
  }

  // uidebug 锚选择器：唯一 id 祖先截断的 nth-of-type 链（body→element），
  // 生成后 querySelector 验证唯一命中；不唯一/异常时仍返回链串（agent 可
  // 结合 element 文本快照定位，selector 是最佳线索而非硬契约）
  function selectorSegment(node) {
    var seg = (node.tagName || "").toLowerCase();
    var parent = node.parentNode;
    if (parent && parent.children) {
      var typed = 0;
      for (var j = 0; j < parent.children.length; j++) {
        if (parent.children[j].tagName === node.tagName) {
          typed++;
          if (parent.children[j] === node) break;
        }
      }
      if (typed > 1) seg += ":nth-of-type(" + typed + ")";
    }
    return seg;
  }

  function cssSelectorFor(node) {
    var esc = (window.CSS && CSS.escape)
      ? function (s) { return CSS.escape(s); }
      : function (s) { return String(s).replace(/([^\w-])/g, "\\$1"); };
    var chain = [];
    var cur = node;
    while (cur && cur.nodeType === 1) {
      if (cur.id) {
        var byId = "#" + esc(cur.id);
        try {
          if (document.querySelectorAll(byId).length === 1) {
            chain.unshift(byId);
            break;
          }
        } catch (e) {}
      }
      chain.unshift(selectorSegment(cur));
      if (cur === document.body || cur === document.documentElement) break;
      cur = cur.parentNode;
    }
    if (!chain.length) chain.push("body");
    return chain.join(" > ");
  }

  function elementSnapshot(node) {
    return { tag: (node.tagName || "").toLowerCase(),
             text: (node.textContent || "").replace(/\s+/g, " ").trim().slice(0, 80) };
  }

  // ── hover 高亮 ───────────────────────────────────────────────────────
  var highlight = el("div", "fpa-highlight");
  var highlightLabel = el("div", "fpa-highlight-label", "");
  highlight.appendChild(highlightLabel);
  // 初始隐藏：position:fixed 未设 top/left 时元素停留在挂载点末尾静态位置，
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
    highlightLabel.textContent = UIDEBUG
      ? (node.tagName || "").toLowerCase() + (node.id ? "#" + node.id : "")
      : (node.getAttribute(ANCHOR_ATTR) || "(无锚)");
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
  var title = el("strong", null, UIDEBUG ? "界面调试批注" : "原型批注");
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
  var cancelEditBtn = el("button", "fpa-btn", "取消编辑");
  cancelEditBtn.style.display = "none"; // 仅 uidebug 重编辑态可见
  var exportBtn = el("button", "fpa-btn fpa-export", "导出 JSON（服务器不可达时）");
  var statusLine = el("div", "fpa-status", "");
  var listTitle = el("div", "fpa-list-title",
    UIDEBUG ? "已提交意见（可编辑/删除）" : "已提交意见");
  var list = el("div", "fpa-list");

  var body = el("div", "fpa-body");
  body.appendChild(targetLine);
  body.appendChild(textarea);
  var row = el("div", "fpa-row");
  row.appendChild(submitBtn);
  row.appendChild(cancelEditBtn);
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
    if (UIDEBUG) {
      state.selectedSelector = cssSelectorFor(node);
      targetLine.textContent = "当前选择：" + state.selectedSelector + "　" +
        elementSnapshot(node).text.slice(0, 24);
      return;
    }
    var anchor = node.getAttribute(ANCHOR_ATTR);
    targetLine.textContent = "当前选择锚：" + anchor + "　" +
      elementSnapshot(node).text.slice(0, 24);
  }

  // ── uidebug 批注管理（列表 / 删除 / 重编辑）─────────────────────────
  // 服务器列表为真相源：面板「已提交意见」整表来自 GET 端点（含历史轮次
  // 与其他页面条目），提交/删除/更新成功后整表刷新。原型模式不走此路径
  // （列表仍为本会话内存态，行为与历史一致）。
  function renderServerList(entries, errorMsg) {
    list.textContent = "";
    if (errorMsg) {
      list.appendChild(el("div", "fpa-empty", errorMsg));
      return;
    }
    if (!entries.length) {
      list.appendChild(el("div", "fpa-empty", "暂无批注。点选区块 → 输入意见 → 提交。"));
      return;
    }
    entries.forEach(function (entry) {
      var item = el("div", "fpa-item");
      var label = (entry.anchor || "(无锚)") + " · 轮次" + entry.round +
        (entry.edited ? " · 已编辑" : "");
      var anchorLine = el("div", "fpa-item-anchor", label);
      // 完整 selector 与来源页放进 title（可见行保持单行省略）
      anchorLine.title = (entry.anchor || "") +
        (entry.page ? "\n" + entry.page : "");
      item.appendChild(anchorLine);
      item.appendChild(el("div", "fpa-item-text", entry.text || ""));
      var actions = el("div", "fpa-item-actions");
      var editBtn = el("button", "fpa-btn fpa-item-btn", "编辑");
      editBtn.addEventListener("click", function () { setEditing(entry); });
      var delBtn = el("button", "fpa-btn fpa-item-btn", "删除");
      delBtn.addEventListener("click", function () { deleteEntry(entry.id); });
      actions.appendChild(editBtn);
      actions.appendChild(delBtn);
      item.appendChild(actions);
      list.appendChild(item);
    });
  }

  function refreshServerList() {
    if (!UIDEBUG) return;
    nativeFetch(FEEDBACK_URL, { method: "GET" }).then(function (resp) {
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      return resp.json();
    }).then(function (data) {
      renderServerList((data && data.feedback) || []);
    }).catch(function () {
      renderServerList([], "无法加载已提交批注（服务器不可达）。");
    });
  }

  function setEditing(entry) {
    editingId = entry ? entry.id : null;
    if (entry) {
      textarea.value = entry.text || "";
      submitBtn.textContent = "更新批注";
      cancelEditBtn.style.display = "";
      setStatus("编辑批注：改完点「更新批注」。");
    } else {
      textarea.value = "";
      submitBtn.textContent = "提交批注";
      cancelEditBtn.style.display = "none";
    }
  }

  function deleteEntry(id) {
    if (!window.confirm("删除这条批注？删除后不可恢复。")) return;
    nativeFetch(FEEDBACK_URL + "?id=" + encodeURIComponent(id),
                { method: "DELETE" }).then(function (resp) {
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      if (editingId === id) setEditing(null); // 删的正是编辑中条目 → 退出编辑态
      refreshServerList();
      setStatus("已删除批注。");
    }).catch(function (err) {
      var notFound = err && err.message === "HTTP 404";
      setStatus(notFound ? "该批注已不存在（可能已被删除），列表已刷新。"
                         : "删除失败，请重试。", !notFound);
      refreshServerList();
    });
  }

  // ── 提交（POST /feedback，失败降级本地导出）────────────────────────
  function buildAnnotation(text) {
    var annotation = {
      // uidebug：anchor=点选时生成的 CSS selector（state.selectedSelector）
      anchor: UIDEBUG
        ? (state.selectedSelector || "")
        : state.selected.getAttribute(ANCHOR_ATTR),
      text: text,
      timestamp: new Date().toISOString(),
      round: state.round,
      element: elementSnapshot(state.selected),
    };
    if (UIDEBUG) {
      // 代理内路径（/uidebug/<p>/<s>/~/<sub>）：多页调试时定位批注所在页面
      annotation.page = window.location.pathname + window.location.search;
    }
    return annotation;
  }

  // annotation 对象 → 意见列表节点的映射：提交成功做数据层去重时按它
  // 同步移除该批注此前提交失败残留的意见列表节点。节点引用不能作为可
  // 枚举属性挂在 annotation 上——导出与 POST 都会序列化批注对象，DOM
  // 节点会污染序列化结果
  var itemEls = new Map();

  // failureNote：失败条目的未送达注记文案，由调用方按真实降级路径传入
  // （已触发本地导出用「已入本地导出」；服务器 4xx 拒绝、未生成导出文件
  // 用「未导出」），remember 不代填默认值，避免未导出路径误标已导出
  function remember(annotation, delivered, failureNote) {
    annotation.delivered = delivered ? "server" : "local-only";
    state.pending.push(annotation);
    var item = el("div", "fpa-item");
    item.appendChild(el("div", "fpa-item-anchor",
      (UIDEBUG ? annotation.anchor : "#" + annotation.anchor) +
      " · 轮次" + annotation.round +
      (delivered ? "" : failureNote)));
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
    if (!text) { setStatus("意见不能为空", true); return; }
    if (editingId) {
      // uidebug 重编辑：按 id 只更新 text（无需重新点选区块——锚点不动）
      submitBtn.disabled = true;
      setStatus("更新中…");
      nativeFetch(FEEDBACK_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: editingId, text: text }),
      }).then(function (resp) {
        submitBtn.disabled = false;
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        setEditing(null);
        refreshServerList();
        setStatus("已更新批注。");
      }).catch(function (err) {
        submitBtn.disabled = false;
        var reason = (err && err.message) || "网络不可达";
        setStatus(reason === "HTTP 404"
          ? "更新失败：该批注已不存在，已退出编辑态。"
          : "更新失败（" + reason + "），请重试。", true);
        if (reason === "HTTP 404") setEditing(null);
      });
      return;
    }
    if (!state.selected) { setStatus("请先点选页面中的区块", true); return; }
    var annotation = buildAnnotation(text);
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, 8000);
    submitBtn.disabled = true; // 在飞防重：8 秒超时窗口内重复点击不再重复 POST
    setStatus("提交中…");
    nativeFetch(FEEDBACK_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(annotation),
      signal: controller.signal,
    }).then(function (resp) {
      clearTimeout(timer);
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      if (UIDEBUG) {
        // 服务器列表即真相源：成功后整表刷新（含其他轮次/页面条目），
        // 不再走本地 remember 渲染
        refreshServerList();
      } else {
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
      }
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
      var refused = reason.indexOf("HTTP 4") === 0;
      // 意见列表注记按真实降级路径区分：4xx 拒绝不触发本地导出（见下），
      // 条目不得声称「已入本地导出」误导用户/agent 去找不存在的导出文件
      remember(annotation, false,
        refused ? "（未送达：服务器拒绝，未导出）" : "（未送达，已入本地导出）");
      // 服务器明确拒绝（HTTP 4xx，如参数校验失败/端点不存在）：原样重试同
      // 样必败，自动导出文件对回流无帮助且多次失败会连续触发多次下载——
      // 只提示修正后重试；超时/网络不可达/服务器故障才降级为自动导出
      if (refused) {
        setStatus("提交失败（" + reason + "），服务器拒绝了该批注，请修正后再提交。", true);
      } else {
        exportLocal();
        setStatus("提交失败（" + reason + "），已导出未送达批注 feedback.json，可修正后重试。", true);
      }
      submitBtn.disabled = false;
    });
  }

  submitBtn.addEventListener("click", submit);
  cancelEditBtn.addEventListener("click", function () {
    setEditing(null);
    setStatus("已取消编辑。");
  });
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
    if (!state.annotateMode) return; // 浏览模式放行页面自身交互
    // shadow 隔离下面板内点击的 ev.target 被重定向为 host 元素（光 DOM
    // 降级形态仍走 panel.contains）；两者都在 preventDefault 之前排除
    if (ev.target === shadowHost || panel.contains(ev.target)) return;
    var node = resolveAnchor(ev.target);
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
    setStatus(state.annotateMode ? "批注模式：点选区块即选中。" : "浏览模式：页面可正常点击。");
  });

  collapseBtn.addEventListener("click", function () {
    var hidden = body.style.display === "none";
    body.style.display = hidden ? "" : "none";
    collapseBtn.textContent = hidden ? "—" : "+";
  });

  // ── 注入样式与挂载 ──────────────────────────────────────────────────
  // 样式进 shadow root（降级形态进 head）：宿主页样式表不再命中批注器。
  // 按钮/输入框补 font:inherit 与显式 color——表单元素不继承字体，且颜色
  // 不能依赖宿主页（深色主题下宿主 color:#fff 会让默认色按钮文字不可读）
  var style = document.createElement("style");
  style.textContent = [
    ":host{all:initial;}",
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
    "border:1px solid #d9d9d9;border-radius:4px;padding:6px;font:inherit;color:#333;}",
    ".fpa-row{display:flex;gap:8px;}",
    ".fpa-btn{font:inherit;font-size:12px;border:1px solid #d9d9d9;background:#fff;",
    "color:#333;border-radius:4px;padding:2px 10px;cursor:pointer;}",
    ".fpa-item-btn{padding:0 8px;font-size:11px;}",
    ".fpa-submit{background:#1677ff;color:#fff;border-color:#1677ff;}",
    ".fpa-status{color:#888;font-size:12px;min-height:1em;}",
    ".fpa-status-error{color:#cf1322;}",
    ".fpa-list-title{font-weight:600;border-top:1px solid #f0f0f0;padding-top:6px;}",
    ".fpa-list{max-height:140px;overflow:auto;display:flex;flex-direction:column;gap:6px;}",
    ".fpa-item-anchor{font:11px monospace;color:#1677ff;overflow:hidden;",
    "text-overflow:ellipsis;white-space:nowrap;}",
    ".fpa-item-text{color:#555;}",
    ".fpa-item-actions{display:flex;gap:6px;}",
    ".fpa-empty{color:#999;font-size:12px;}",
  ].join("");
  styleParent.appendChild(style);

  // 注入约定是 <script defer>（保证 body 已解析）；若被放进 <head> 且漏写
  // defer，此处 document.body 尚为 null——降级为 DOMContentLoaded 后挂载，
  // 并在控制台提示注入偏差，避免整个批注器静默失效
  function mount() {
    if (mountRoot) {
      // shadow 形态：host 元素挂进 body，UI 挂进 shadow root
      document.body.appendChild(shadowHost);
      mountRoot.appendChild(highlight);
      mountRoot.appendChild(panel);
    } else {
      // 光 DOM 降级：与历史行为一致
      document.body.appendChild(highlight);
      document.body.appendChild(panel);
    }
    setStatus("批注模式：点选区块 → 输入意见 → 提交（轮次 " + state.round + "）。");
    if (UIDEBUG) refreshServerList(); // 面板「已提交意见」从服务器整表加载
  }
  if (document.body) {
    mount();
  } else {
    console.warn("[fenix-prototype] annotator.js 应以 <script defer> 注入（当前 body 未解析），已延迟至 DOMContentLoaded 挂载。");
    document.addEventListener("DOMContentLoaded", mount);
  }
})();
