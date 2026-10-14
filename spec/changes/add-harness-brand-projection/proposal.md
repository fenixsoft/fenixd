## Why

dashboard 运行记录的对话组件族（claude-msg）把 harness 身份硬编码：`MessageItem.tsx` 的 `headerLabelFor` 恒返回 `'Claude'`、消息头像恒渲染 `ClaudeLogo`。dsh 通道的 run（今天已真实验收通过）在界面上全部显示为 Claude，误导取证与观感；后续每个新 harness 都会错标。组件文件名（ClaudeOutputPane 等）同样以 claude 命名，但文件名属历史包袱不强制改，耦合消除在内容层。

## What Changes

- 新增 `HarnessBrand` React context（`{ name, Logo }`）：对话组件经 context 取品牌名与图标，**外部投影注入**；context 缺省值 = Claude 品牌（claude 通道行为零变化）。
- 新增 `DshLogo` 组件：官方鲸鱼图标（来源 `https://www.deepseek.com/harness/favicon.svg`，MIT 项目官方品牌资产；副本已存本 change `assets/dsh-mark.svg`；组件内联时固化基础品牌蓝、移除其 `prefers-color-scheme` 媒体查询——固定浅色应用下暗色变体会浅底同色消失，见 design Decision 4）。
- 运行时真相源：runner 写 run_metrics 结构化行时增 `"harness": <adapter.name>` 字段；`dashboard/data/runs.py` 把它索引进 run meta；前端 run 视图按 run meta 的 harness 选品牌注入 Provider。
- 存量 run（无 harness 字段）与未知 harness 值回退：claude 品牌 / 首字母徽标，不崩。
- **BREAKING：无**（claude 显示不变；组件文件不改名）。

## Capabilities

### New Capabilities
- `harness-brand-projection`: 对话组件的品牌投影契约——context 缺省、按 run meta 注入、回退链（无字段→claude；未知值→首字母徽标）。

### Modified Capabilities

（无——展示层新增，不改既有需求。）

## Impact

- 前端：`claude-msg/MessageItem.tsx`、新增 `HarnessBrand.tsx`/`DshLogo.tsx`、`RunRecordModal.tsx`/`AdminRunModal.tsx` 注入点、图标资产、node --test 单测。
- 后端：`core/agent_runner/runner.py`（run_metrics 增 harness 字段）、`core/dashboard/data/runs.py`（run meta 暴露）。
- 不受影响：run jsonl canon（不往 claude 形状 schema 里塞 harness 字段，真相源走 run_metrics 旁路）；自由会话 SessionPanel（claude 专用，缺省品牌即正确，不改）。
