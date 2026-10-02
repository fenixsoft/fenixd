# ADR-207：Dashboard 双样式管线并存——tailwind 仅服务 claude-* 迁移组件且按目录显式注册 content，不注册则类名静默不编译

date: 2026-10-03
status: accepted

## Context

dashboard 前端主体是 UmiJS + antd + less；自 claudecodeui 迁移 `claude-msg` 与会话输入控件时带入了 tailwind className 体系。tailwind CLI 在 `tailwind.config.js` 提供 content 配置时不再启用自动内容检测——编译范围由 content 数组显式限定，未列入目录的类名不会进 `tailwind.gen.css`，且构建零报错（静默缺失）。备选「antd/less 重写迁移组件样式」被否：原控件即按 tailwind 打磨（overlay 着色、键盘导航、菜单锚定细节），重写成本高于搬运且丢失跟随上游演进的能力。

## Decision

- dashboard 维持双样式管线并存：页面主体走 antd + less；tailwind 管线仅服务 `components/claude-*` 迁移组件家族（claude-msg、claude-composer），不用于新页面开发。
- tailwind content 数组按组件目录显式注册；任何新增消费 tailwind 的组件目录必须同步扩入 content 数组并在组件内 import `tailwind.gen.css`，MUST NOT 假定类名会被自动发现。
- tailwind 配置禁 preflight（避免重置 antd 全局样式）；darkMode 用 class 且全站不加 dark 类（`dark:` 变体不生效，全站恒亮色）；迁移组件颜色 token 映射为亮色 HSL 值。
- 迁移组件根节点使用独立类名空间，输入路径不被 antd 组件包裹，避免两套样式的特异性冲突。

## Consequences

- 新增 tailwind 组件目录漏注册 content 时构建不报错、样式静默缺失——该失败模式只能靠双端截图/视觉验证暴露；代码审查须把「新增组件目录」与「content 数组扩展」作为成对检查项。
- 迁移组件上游（claudecodeui）的 tailwind 类名可原样跟随演进，无需翻译为 antd；代价是仓库内同时存在两套样式语汇，贡献者须先辨认目标目录属哪条管线。
- 全站恒亮色成为样式管线约束：任何引入暗色的 SPEC 必须同时改造 tailwind darkMode 通道与迁移组件 token，不能只改 antd 主题。
