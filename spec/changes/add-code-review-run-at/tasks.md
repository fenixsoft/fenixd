## Deliverables

```yaml
- path: core/config.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/code_review.py
  kind: modify
- path: core/dashboard/data/config_admin.py
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/QualityPanel.tsx
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: tests/test_code_review_run_at.py
  kind: new
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 配置单源

- [ ] 1.1 `core/config.py` `get_code_review_config` 新增 `run_at` 读取：cr 段存在且可被 `_parse_run_at` 同口径解析为合法 HH:MM 才生效；键缺失/非法字面量/非字符串类型一律回退 `get_self_review_config(config)["run_at"]`；docstring 补条目（含回退语义与用户定调「缺省同自省时点」）
- [ ] 1.2 `tests/test_code_review_run_at.py`：独立值生效 / 缺省回退 / 非法值（"abc"、123、"25:00"、bool）回退 / cr 段整体缺失回退，四组用例

## 2. 检查点换源

- [ ] 2.1 `core/admin_monitor.py` `_run_code_review_checkpoint` 触发判定改读 `cr_cfg["run_at"]`（删除 `sr_cfg` 依赖仅保留窗口侧既有用途），同步注释：`run_at 未到不触发` 的「与自省同口径」表述改为「独立键＋缺省回退（get_code_review_config 单源）」
- [ ] 2.2 `tests/test_code_review_run_at.py`：检查点触发用例——独立时点 "13:00" 时 01:00 轮 `reason=before_run_at` 不派发、13:00 后轮正常派发；缺省回退时 01:00 正常派发；`enabled=false` 全链路零动作（既有语义回归）

## 3. 窗口水位归审查车道

- [ ] 3.1 `core/code_review.py` `save_code_review_state` 扩展：周期审查收尾写入 `last_run_at`（本轮审查完成时刻，aware ISO8601 UTC；兼容保留 `last_run_date` 自然日防重字段）
- [ ] 3.2 `core/code_review.py` `compute_window`：`window_start` 优先读 `code_review_state.last_run_at`；字段缺失回退读 `self_review_state.last_run_at`；再缺失回退 `now - 24h`（三态口径）
- [ ] 3.3 `tests/test_code_review_run_at.py`：水位三态用例——有 `last_run_at` 取自身（自省已覆写也不受影响）/ 缺失回退自省 / 双缺失回退 24h；及 save 后 compute 读回一致

## 4. Dashboard 设置字段

- [ ] 4.1 `core/dashboard/data/config_admin.py`：透出 `admin.code_review.run_at` 读写字段（读取回退展示生效值、写入合法性校验 HH:MM、脏值拒绝并报错）
- [ ] 4.2 `core/dashboard/static/src/pages/settings/components/QualityPanel.tsx`：code-review 卡片增「触发时点」HH:MM 输入，占位提示「缺省同每日自省时点」；保存走既有面板脏检查与提交链路
- [ ] 4.3 `tests/test_code_review_run_at.py`：config_admin 字段读回退展示 / 写入合法值落盘 / 非法值拒绝三用例

## 5. 模板文档

- [ ] 5.1 `.fenix/config.template.yaml` `code_review` 段补 `run_at` 注释条目：本地时间 HH:MM、缺省回退 `admin.self_review.run_at`、解耦动机一句（避免与自省同刻齐发触发网关限流）
