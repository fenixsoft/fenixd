# 实现期审查开关配置（verify.impl_code_review）

<!-- knowledge: capability=impl-code-review-setting rev=1
     sources=spec/archive/2026-09-23-add-impl-code-review-gate -->

布尔配置键 `verify.impl_code_review` 控制「实现阶段末尾的代码质量审查」是否启用，以及设置页对该键的读写回显。

## 规则

- 键位于既有 `verify` 配置节内，与 `verify.static_scope` / `verify.deps_mode` 同级。
- 缺省 `false`；未配置、类型非法（非 bool，如字符串 `"yes"`、数字 `1`）一律按未启用处理（fail-open，脏值不启用审查、不中断派发、不抛异常）。
- 两级作用域：用户级配置文件设为默认，项目级同名键覆盖；解析与既有 `verify.*` 键同源同优先级（项目级 > 用户级 > 代码缺省）。
- 关闭（含缺省）时表现为「无此功能」：提示词零注入、审查相关产物零校验。
- 设置页「验证」页签提供开关控件，与既有 `verify` 节读写链路同源（界面写入的值能被读回、界面显示的值即实际生效值）：
  - 保存随既有 `verify` patch 一并提交（与 `static_scope` / `deps_mode` 同一个 `verify` 对象），不单独另立配置节；
  - 服务端读路径回显该键、写路径合并该键、来源标注登记该键（「继承自用户级」标注与其它 `verify.*` 键行为一致）；
  - 开关关闭为缺省呈现态；配置缺失时界面显示为关闭，不显示「未知」或空值。
- 将已开启的开关关闭并保存时，配置文件写入 `false`（而非删除该键），重新读取返回 `false`。
- `.fenix/config.template.yaml` 的 `verify` 段列出该键，值为 `false` 并附说明注释（实现阶段末尾的代码质量审查开关），使模板与代码默认值、界面缺省三者口径一致。

## 溯源

- 2026-09-23 add-impl-code-review-gate — 新建配置键语义（缺省 false / fail-open / 两级作用域）、设置页「验证」页签同源开关读写、配置模板登记。
