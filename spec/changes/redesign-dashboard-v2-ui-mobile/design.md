# Design: redesign-dashboard-v2-ui-mobile

## Context

移动端原型确认环完成（六页、390px 基准、批注三轮），定稿入库本 SPEC prototype/。depends_on redesign-dashboard-v2-ui。

## Decisions

- **D1 断点单源**：<768px 断点判定与移动形态工具类收进 v2 theme.tsx 增量（断点 token + 复用现产 useIsMobile hook），六页统一消费，MUST NOT 散落断点魔法数
- **D2 形态切换**：桌面/移动两形态在页组件内按断点分支渲染（布局容器级分支，数据层共享），MUST NOT 拆成两套路由
- **D3 移动惯例遵循**：仓库移动端定调「改布局不改宽度、越界布局优先、渐进披露」；表格转卡片、目录抽屉（Drawer）对齐现产移动端惯例
- **D4 头部按钮收敛**（批注定稿）：移动端移除 新建 SPEC / 状态转移 / 搜索 三入口（桌面保留），对应动作由列表页/桌面端承载

## 偏离声明

无新增偏离：移动形态属 redesign-dashboard-v2-ui 已登记的 v2 例外域范围内行为，域专属 token 不变。

## Risks

- 双形态分支膨胀 → 分支收敛在布局容器级，卡片/行级组件抽为子件复用
- 依赖时序 → depends_on 硬约束，daemon 依赖唤醒机制保证前序合并后派发
