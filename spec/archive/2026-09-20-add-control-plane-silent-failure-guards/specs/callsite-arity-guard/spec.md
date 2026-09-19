# 生产调用点实参数量守卫（callsite-arity-guard）

## 需求

### R1 静态 arity 检查
- 测试套件 SHALL 提供一项静态 AST 守卫，扫描生产代码调用点（`core/**/*.py` 与仓库根 `fenixd.py`），对每个方法调用 `<obj>.<method>(...)` 判定：若调用提供的位置参数个数**少于**该方法定义的**最小必填位置参数个数**，且调用未包含 `*args` 展开（`ast.Starred`）与 `**kwargs` 展开（`keyword.arg is None`），则判为违规。
- 判定 SHALL 仅在该 `<method>` 名在 `core/` 中**唯一签名**、且该签名不含 `vararg`/`kwarg` 时生效（保守起步，避免无关类同名方法误报）。
- `self.<method>(...)` 同类内调用 SHALL 一并被覆盖。
- `staticmethod` 的首参不剥离；实例方法/类方法剥离首个 `self`/`cls`。

#### Scenario: 实参不足被拦截
- **WHEN** `core/` 中存在调用 `obj.handle_event("spec_implemented", spec)` 而 `handle_event` 的唯一签名要求 3 个必填位参
- **THEN** 守卫测试失败，报出 `文件:行 类.方法 调用给 N 个 / 要求 M 个`

#### Scenario: 关键字补足不误报
- **WHEN** 调用 `obj.handle_event("spec_implemented", spec, spec_entry=entry)` 或 `obj.handle_event("spec_implemented", spec_name="x", spec_entry=e)`，关键字名属于该签名
- **THEN** 不判违规（必填位参已由关键字满足）

#### Scenario: 变长展开不误报
- **WHEN** 调用 `obj.handle_event(*args)` 或 `obj.handle_event(**kw)`
- **THEN** 不判违规（实参数量静态不可知）

#### Scenario: 同名多签名不参与
- **WHEN**某方法名在 `core/` 中有 2 个及以上不同签名（如 `get` 在不同类中定义不同）
- **THEN** 该方法名不参与判定，不产生违规

### R2 误报白名单
- 守卫 SHALL 提供显式白名单以豁免确有其事的同名误报（如 `logger.warning(f"...")` 与某类 `warning(self, component, message)` 同名但语义无关）。
- 白名单条目 MUST 为 `(文件相对路径, 行号, 方法名)` 或等价最小粒度，MUST NOT 用文件级或全局通配豁免整类。

#### Scenario: 白名单精确豁免
- **WHEN** 某误报被逐条登记进白名单
- **THEN** 该行不再计违规，其余同类调用仍正常判定

### R3 守卫有效性自检
- 守卫测试 SHALL 包含"有牙"自检：断言候选方法集规模非空且高于下限（防止规则退化后永远绿）。

#### Scenario: 候选集退化即失败
- **WHEN** 候选方法集因构造规则错误退化为 0 或低于下限
- **THEN** 自检断言失败，提示守卫已失效

## 验收标准
- 单元测试：注入一段含 arity 违规的样例代码，守卫报出违规；注入合规调用，守卫不报。
- 单元测试：`*args`/`**kwargs`/关键字补足/同名多签名四类不误报。
- 落地实证：对当前 `core/` 运行守卫，违规数（白名单外）为 0。
