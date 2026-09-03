## Context

SPEC 列表页（`renderProject`/`specRow`，`core/dashboard/static/app.js`）目前：
- 表头列：状态 / 名称 / 优先级 / 创建时间 / 任务进度 / 验证 / 耗时 / 错误 / 文档（`document`）
- 「错误」列显示 `STATE.md` 条目的 `error` 字段，前端截断 50 字符 + `title` 属性兜底
- 已有 `GET /api/spec-doc?project=<p>&spec=<s>&doc=proposal|design` 返回文档原文（markdown 字符串，`found` 标记缺失）
- 已有 `mdRender()`（vendored `marked` v18，GFM + 链接白名单/http/mailto + 转义）服务文档弹窗
- 列表通过 SSE 事件驱动约 2 秒重渲染一次（`load()` 全量重建 tbody）

两处改进均为纯前端改动（复用上述端点与渲染管线），服务端零改动。

## Goals / Non-Goals

**Goals:**
- 悬停 SPEC 名称即见 proposal.md 的 `## Why` 段，Markdown 渲染，不打断行点击、排序、过滤
- 「错误」窄列改为行下方跨全列信息子行，消息不再截断、换行可读
- 对服务端 / API / 既有测试零影响

**Non-Goals:**
- 不修改 `/api/spec-doc` 或任何服务端行为
- 不做 Why 的索引/搜索/详情页复用
- 不改变 `error` 字段的产生与内容（命名「信息」仅指展示语义，不改字段名）

## Decisions

### D1: Why 内容客户端按需获取，服务端零改动
首次 hover 某 SPEC 时 fetch `/api/spec-doc?doc=proposal`，前端提取 Why 段并渲染；结果按 `(project, spec)` 缓存于内存 `Map`，重复 hover 直接命中。理由：列表 2 秒全量重渲染，若在 `/api/specs` 中预解析 why 会让每次刷新为每个 SPEC 读 proposal.md，payload 与 IO 同步增长，且 `parse_state` 是概览/详情/列表公共路径，风险面更大。
**负缓存策略**：fetch 失败不缓存（下次 hover 自动重试）；「无 Why 段/文档缺失」作为 `found: false` 结果缓存，避免同一 SPEC 反复发起无效请求。

### D2: Why 段提取在 markdown 源文本上完成
前端从 `content` 字符串按行提取：定位 `/^##\s+why\s*$/i` 标题行，取其后直到下一个 `/^##\s/m` 标题行（或文末）的内容，`trim()` 后为空则视为无 Why 段。提取先于渲染，保留 markdown 语义；不渲染后再截 DOM。

### D3: 提示框用 position: fixed 模拟 div，视口内翻转
hint 容器为 `position: fixed` 的 div，打开时以目标单元格 `getBoundingClientRect()` 计算初始位置，优先放名称下方；空间不足（视口底部/右侧放不下）时向上/向左翻转，宽度上限 420px、高度上限约 60vh，超出 `overflow-y: auto`（Why 段落长时可滚动，滚动由元素自身容器承担）。不用 `position: absolute` 于表格内，原因：`.spec-table-wrap` 有横向滚动容器，absolute 与滚动/裁剪相互纠缠，fixed + 视口坐标最稳。
**交互细节**：hover 用 ~200ms 延迟打开（防快速划过闪烁）；`mouseleave`、`document` 任意 `click`（含触发行跳转的点击）、`document` 滚动（capture 阶段捕获，覆盖表格 wrap 滚动与窗口滚动）均关闭 hint。

### D4: 「错误」列整体移除，信息改子行
- `headers` 数组删除 `{ key: 'error', label: '错误' }`；`sortValue()` 删除 `error` case（排序能力一并移除）
- `specRow` 删除错误单元格，改为返回两个 `<tr>`：主行 +（条件性）信息子行 `<tr class="spec-info-row"><td colspan="8">…</td></tr>`；`colspan` 固定等于剩余表头列数（8：状态/名称/优先级/创建时间/任务进度/验证/耗时/文档），表头与子行用同一常量派生，避免手动数列
- `error` 为 null/空字符串时返回单个主行（无空洞行高）
- 子行内容：`esc(s.error)` + `white-space: pre-wrap`（保留消息内换行），前加「信息」小徽标体现语义；不截断

## Risks / Trade-offs

- **hint 首开延迟**：本地接口 + 小文件，首开毫秒级；期间显示「加载中…」占位，缓存后零延迟。可接受。
- **fetch 重复请求**：`found: false` 负缓存仅对单 SPEC 生效，proposal.md 编辑后新开标签页即取新内容；同页受缓存约束属预期。
- **渲染安全**：Why 内容经既有 `mdRender` 管线（转义 + 链接白名单），与文档弹窗同一约束，无新增 XSS 面。
- **行高变化**：信息子行增加该 SPEC 行的总高度属有意行为，不破坏对齐（子行仅在有消息时出现）。
- **测试盲区**：改动集中在静态 JS/CSS，服务端测试逻辑不变；回归跑 `tests/test_dashboard.py` 确认无破坏，前端行为建议实现后人工浏览器验证（hover 显示、渲染、缓存、子行换行、刷新保持）。