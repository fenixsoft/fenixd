# 装配缺口与真实工厂集成断言

<!-- knowledge: capability=assembly-gap-real-factory rev=1
     sources=spec/knowledge/_inbox/done/optional-method-sink-silent-skip-1111.md -->

sink/store/服务装配链（接口契约 + 真实工厂 + 桩替身三层结构）代码的测试设计纪律：接口可选方法在真实实现上缺席是类型系统合法态、运行时被可选调用静默吞掉，静态检查零报错加全量单测全绿不构成装配正确性证据，必须有一条落到真实工厂的集成断言兜底。

## 规则

- **接口可选方法 ≠ 实现可缺席**：类型面声明为可选的方法（TS `method?` 形态），实现对象上缺席完全合法——静态检查（tsc）不报错；调用侧一旦写成可选调用（`obj.method?.()`），缺席即被静默吞掉：不抛错、无日志、零运行时痕迹。写 `?.` 调用的那一刻就等于裁定「实现缺席 = 静默降级」，因此每条可选调用链都必须配一条能落到真实工厂的集成断言，否则装配缺口只有真机冒烟能暴露。
- **桩替身系统性掩盖装配缺口**：桩替身是实现者人为重构的产物，形状永远比真实链路「完整」——桩「勤快地」实现全部方法（含可选方法）恰恰把真实实现的漏实现掩盖掉，桩越齐全越测不出装配缺口。涉及 sink/store/服务装配的测试至少一条走真实工厂 + 桩 ctx（只替外层依赖，装配主体用生产实现），全桩测试不替代这一条。
- **全绿 ≠ 装配正确**：tsc 零报错 + 全量单测全绿 + console 零报错，三者都不是装配正确性证据——装配缺口的唯一可靠暴露面是用户可见行为（功能面恒缺席、数据源恒为空）。排查此类现象先逆数据流找写入点，确认写入是否被可选调用静默吞掉。
- **静默降级必须留痕**：可选依赖缺席且行为差异用户可见时，降级分支留痕（console.warn 一次）给真机排查留抓手；零痕迹的静默降级让「设计内降级」与「装配缺口」在观测面上不可区分，是此类排查成本的主要来源。

## 代码锚点

纪律先例在宿主仓 dsh-plugins（跨仓，路径相对 dsh-plugins 仓根）：

- 先例实现：`fenix-dsh-dashboard-bridge/src/client/projectSync.ts`（`ProjectEntrySink` 可选方法契约面与 `options.sink.setProjectRows?.(rows)` 可选调用点）、`fenix-dsh-dashboard-bridge/src/client/index.ts`（真实工厂 `projectEntrySink` 逐一实现全部可选方法转发 `projectGroupStore`）
- 守卫测试：`fenix-dsh-dashboard-bridge/tests/projectSync.test.ts`（「sink 行沉淀回归」describe：真 sink 集成回归——`projectEntrySink(桩 ctx)` 直接喂 `startProjectSync`，断言 `typeof sink.setProjectRows === 'function'` 且对齐后 store.projectRows 落地；源码钉——index.ts 源码必须含 `projectGroupStore.setProjectRows(rows)` 转发行）

## 溯源

- 2026-11-11 optional-method-sink-silent-skip-1111（spec/knowledge/_inbox/done/optional-method-sink-silent-skip-1111.md） — 新建本页：折叠 dsh bridge `setProjectRows` 装配缺口案例的可迁移纪律（可选方法缺席合法 + `?.` 静默吞调用、桩替身系统性掩盖装配缺口、真实工厂集成断言 + 源码钉回归钉、静默降级留痕）
