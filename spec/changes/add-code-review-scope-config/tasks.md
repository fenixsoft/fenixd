# add-code-review-scope-config 任务

## Deliverables

```yaml
- path: core/config.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/QualityPanel.tsx
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: tests/test_code_review_scope_config.py
  kind: new
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 配置层：scope 键与缺省回退

- [ ] 1.1 `core/config.py` `get_code_review_config()` 补 `scope` 键：取 `admin.code_review.scope`，值恰为 `full` 时返回 `full`，其余（缺失/`window`/非法字面量/非字符串类型）一律返回 `window`——巡检路径不因脏配置中断；docstring 补两档语义与回退规则

## 2. 触发层：周期路径按配置取 scope

- [ ] 2.1 `core/admin_monitor.py` 周期触发路径两处解硬编码：`collect_manifest` 调用按配置传 `scope="full"`（此时 `window_start=None`）或 `scope="window"`（既有 `window_start` 同源值）；`run_code_review` 调用同样按配置传 `scope`，`review_kind` 恒为 `scheduled`、其余实参不变；scope=`window` 路径的行为与改动前逐字节一致（含 manifest 空跳过、防重写入、单飞复位）
- [ ] 2.2 scope=`full` 时「窗口内无文件变更跳过」分支语义复核：全仓收集为空属异常态（受控仓必有文件），按既有 no_files 路径记录并跳过即可，不新增分支——在代码注释注明该判定对 full 档实际不可达的原因；full 档若真走该分支，日志文案须带 scope 标注（`admin_monitor.py` 既有文案写死「窗口内无文件变更…window_start=…」，full 档 window_start=None 下措辞失真、误导排障判别；文案改写落在 admin_monitor.py 内，scope=window 档日志保持逐字节不变）

## 3. 设置页 UI：审查范围下拉

- [ ] 3.1 `QualityPanel.tsx`「周期性代码审查」区块新增「审查范围」Select（选项 `当期审查（window）` / `全库审查（full）`，文案与项目页手动按钮一致）：表单状态初值读 `config.admin.code_review.scope`（缺失回显 window）；保存时并入既有 `admin.code_review` 段写回（对齐本区块既有 enabled/max_files 字段的保存链）
- [ ] 3.2 `npm run build` 通过（dist 为构建产物，reference）

## 4. 配置模板与文档

- [ ] 4.1 `.fenix/config.template.yaml` `admin.code_review` 注释示例段补 `scope` 行：两档取值、缺省 window、非法值回退规则、full 档受 max_files 上限约束的提示（注释风格对齐该段既有 enabled/max_files 行）

## 5. 测试与收尾

- [ ] 5.1 新增 `tests/test_code_review_scope_config.py`：覆盖 `get_code_review_config` scope 缺省/合法/非法回退；`admin_monitor` 周期触发在 scope=window 与 full 两档下 `collect_manifest`/`run_code_review` 的实参断言（沿用既有周期审查替身注入模式，落点 `tests/test_code_review.py:674-745`：AdminMonitor `_run_code_review_checkpoint` + fake `run_code_review` 注入形态）；守卫（防重/run_at/enabled 关闭）两档行为一致；临时文件走 tmp_path，不触真实用户级配置（对齐历史「用户级配置敏感测试」教训）
- [ ] 5.2 定向回归：`pytest tests/test_code_review_scope_config.py` 与既有 admin_monitor / code-review 相关定向测试全绿
