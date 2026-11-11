# 可选方法在真实实现上缺席：`?.` 静默吞调用（fenix-dsh-dashboard-bridge setProjectRows 案例）

日期：2026-11-11 ｜ 域：harness-integration / TypeScript 工程习惯 ｜ 来源：dsh 文件右键「在 Fenix 项目中定位」冒烟排查

## 现象

bridge 插件（/root/dsh-plugins/fenix-dsh-dashboard-bridge）的文件右键定位菜单在真机永远不出现。逐层排查：服务注入 OK（contextMenus/sessions 都在）→ 菜单注册 OK → resolve 路径匹配数据源 `projectGroupStore.getSnapshot().projectRows` 恒为空数组。

## 根因

`startProjectSync` 的对齐步把路径行沉淀写成可选调用：

```ts
options.sink.setProjectRows?.(rows)
```

而真实 sink 工厂 `projectEntrySink`（index.ts:425）返回的对象**漏实现了 `setProjectRows`**——类型面 `ProjectEntrySink` 把该方法声明为可选（`setProjectRows?(rows)`），于是：

- tsc 不报错（可选方法在实现对象上缺席是合法的）；
- 运行时 `?.` 把调用静默吞掉（不抛错、无日志）；
- 单测全绿——projectSync.test 的桩 sink「勤快地」实现了全部方法，掩盖了真实实现的缺席（桩越齐全越测不出装配缺口）。

## 修复与回归钉

1. `projectEntrySink` 补 `setProjectRows(rows) { projectGroupStore.setProjectRows(rows) }`。
2. 新增**真 sink 集成回归**：`projectEntrySink(桩 ctx)` 直接喂 `startProjectSync`，断言 store.projectRows 落地——不再用自造桩 sink。
3. 源码钉：`index.ts` 源码必须含 `projectGroupStore.setProjectRows(rows)` 转发行。

## 教训（可迁移）

- **接口可选方法 ≠ 实现可缺席**：写 `?.` 调用的那一刻就决定了「缺席 = 静默降级」，必须配一条能落到真实工厂的集成断言，否则装配缺口只有真机冒烟能暴露。
- **桩替身会系统性地掩盖装配缺口**：桩为实现者的人为重构产物，形状永远比真实链路「完整」；涉及 sink/store/服务装配的测试，至少一条要走真实工厂 + 桩 ctx。
- **静默降级必须留痕**：可选依赖缺席时若行为差异用户可见（本例菜单不出现），考虑在降级分支 console.warn 一次，给真机排查留抓手。
- 排查路径：现象（菜单缺失）→ 服务注入探针（临时 globalThis 挂 `__probe` 函数回读运行时状态，验证后移除）→ 数据源空数组 → 逆着数据流找写入点 → 发现写入被 `?.` 吞掉。探针法对「插件模块作用域不可直接触达」的场景特别有效。

## 关联

- bridge README.zh.md（6 固定条目 + 文件右键定位）
- fenixd spec/changes/add-project-home-tab（深链 `?tab=home&path=` 消费端）
