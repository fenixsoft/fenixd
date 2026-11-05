# Proposal: redesign-dashboard-v2-ui

## Why

当前 dashboard 各页视觉粗糙，不像一个商业产品。经原型确认环（ui-ux-pro-max 情报 × 4 风格候选 × 多轮批注迭代），用户已定稿「Bento 磁贴工作台」设计语言（浅灰底白磁贴大圆角软阴影、黑主色 #0f1115 + 蓝链接 #4176e6、语义胶囊徽标、tabular-nums 数字、分段按钮 ACTIVE 黑底），并要求全部页面在开发期以 `/v2/` 前缀访问、不影响既有页面；同时本次页面样式修改须同步输出新的 DESIGN.md（宪法修正案）。

## What Changes

- 新增 `/v2/*` 路由族（6 页）：概览 / 项目详情 / SPEC 详情 / 配置 / 帮助 / 运维，实现与既有页面同源的 `/api/` 真实数据消费，布局与组件选型以 `prototype/` 六张定稿原型为 UI 真相源
- 既有路由与页面零改动（守卫断言路由表既有条目不变、既有页面渲染不受影响）
- 新增 v2 主题单源（Bento token 常量），不触碰现产 theme.ts
- DESIGN.md 同步重生成：新增「例外域：v2 商业化界面域」小节登记定稿设计语言，既有条款不回溯改动

## Capabilities

### v2-commercial-ui（ADDED）

- `/v2/` 前缀路由族与页面隔离
- 六页面 Bento 化实现（原型绑定契约生效）
- DESIGN.md v2 界面域修正案

## Impact

- 新文件：`src/pages/v2/` 目录族 + v2 主题单源；`config/routes.ts` 增量注册；`DESIGN.md` 增补例外域小节
- 不改动：既有页面组件、theme.ts、ProLayout 全局配置、后端 API
- 风险：路由表膨胀与菜单污染（v2 菜单项需按原型入口设计）；构建产物体积增量（可接受）
