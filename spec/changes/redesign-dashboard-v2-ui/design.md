# Design: redesign-dashboard-v2-ui

## Context

原型确认环已完成（ui-ux-pro-max 情报 → 4 风格候选 → 方案 B 多轮批注迭代 → 6 页定稿），定稿原型与截图入库于本 SPEC `prototype/`。用户明确：开发期全部 v2 页面挂 `/v2/` 前缀、不影响既有页面；页面样式修改同步输出新 DESIGN.md。

## Goals

- 6 个 v2 页面（真实 API 数据）按原型落地，路由 `/v2/*`
- 设计语言单源独立文件，零触碰现产 theme.ts 与既有组件
- DESIGN.md 增补例外域小节（修正案程序：用户「按此定稿」为定稿事件，本设计文档即 diff 级提案，SPEC 实现执行写入）

## Decisions

- **D1 路由隔离**：`config/routes.ts` 追加 `/v2/*` 分支（layout 沿用 ProLayout），既有条目零改动；v2 菜单项由 v2 页面族自行声明（不进既有菜单组，避免污染现产导航）
- **D2 主题单源独立**：新建 `src/pages/v2/theme.tsx`（Bento token 常量 + ConfigProvider 主题），页面根节点局部 ConfigProvider 包裹；MUST NOT 修改现产 theme.ts（宪法配色单源在 v2 域经修正案后由新单源承载）
- **D3 设计语言**（定稿原型提取）：页底 #f8fafc / 白磁贴 radius 16 / 软阴影 / 主按钮黑 #0f1115 / 链接蓝 #4176e6 / 胶囊徽标 999 / 数字 tabular-nums / 表格 fixed 布局 + 首列 14px 缩进 + 长文本 pre-wrap
- **D4 数据复用**：v2 页面复用 `services/dashboard.ts` 既有 API 客户端与类型；信息架构对齐现产页（如 SPEC 详情的项目信息 8 项、任务清单、五页签）
- **D5 DESIGN.md 修正案**：新增「例外域：v2 商业化界面域」小节；偏离声明见下节；写入时机 = 本 SPEC 实现批内（用户已确认「同步输出新的DESIGN.md」）
- **D6 静态渲染**：v2 域延续静态渲染红线（零装饰动效；antd 组件默认微交互不在此列）

## 偏离声明（对既有宪法）

| 偏离条目 | 理由 | 适用范围 |
|---|---|---|
| 圆角：磁贴 16 / 胶囊 999（一般域现为 antd 默认 6/4/8） | Bento 语言定稿原型；商业观感核心形态 | 仅 v2 域六页 |
| 配色单源换轨：v2 主题独立文件（原 theme.ts dsh 表） | 用户定稿「黑主色按钮 + 蓝链接」新基线；不触碰现产文件 | 仅 v2 域 |
| 页底浅灰 #f8fafc（一般域现为白底） | 磁贴层次需要 | 仅 v2 域 |
| 语义色 error #dc2626 / warning #d97706（原 dsh #ec1313/#f59e0b） | 候选方案 B 定稿色板 | 仅 v2 域 |

以上偏离随 DESIGN.md v2 例外域小节一并转正；v2 域外任何页面不得引用 v2 主题。

## Risks

- 路由/菜单污染 → D1 菜单声明约束
- 双主题并存漂移 → v2 域外禁用 v2 主题（code review 对照）
- API 语义缺口（如 SPEC 详情 Hook 数据）→ 按既有端点最小适配，缺口字段显式「—」不伪装 0

## Migration

无数据迁移；既有页面零改动；v2 页面开发期独立可达，验收后由用户决定是否切换默认路由（另行立项）。
