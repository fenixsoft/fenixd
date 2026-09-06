## Deliverables

```yaml
- path: core/dashboard/static/src/pages/settings/components/SystemPanel.tsx
  kind: new
- path: core/dashboard/static/src/pages/settings/index.tsx
  kind: modify
- path: core/dashboard/data.py
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: docs/help/08-config.md
  kind: modify
- path: tests/test_system_settings_config.py
  kind: new
```

## 1. 系统页签与配置契约

- [ ] 1.1 `core/dashboard/data.py`：`read_config` 白名单扩展 admin 段——返回 5 键（enabled/interval_minutes/escalation_cooldown_minutes/merge_breaker_threshold/shutdown_drain_seconds）+ 各自缺省值，与 llm/agents 段「缺省填充」形态一致；既有 llm/agents/verify 段返回结构逐字段不变；不透传未知 admin 键、不纳入 self_review 子段
- [ ] 1.2 `core/dashboard/data.py`：`write_config` admin 段校验分支——enabled 须 bool、interval_minutes 须正数、escalation_cooldown_minutes 须非负数、merge_breaker_threshold 须正整数、shutdown_drain_seconds 须非负整数；非法值拒绝保存并返回明确错误信息（沿用现有 config 写入校验错误形态）
- [ ] 1.3 新建 `core/dashboard/static/src/pages/settings/components/SystemPanel.tsx`：5 控件（Switch/数字输入）+ design.md 注解表文案逐条渲染；`index.tsx` 注册「系统」页签
- [ ] 1.4 `.fenix/config.template.yaml`：`admin.shutdown_drain_seconds` 默认值 1800→0，注释同步（0=快速停机 + interrupted 标记续做兜底；supervisor 强杀等待=值+120s）
- [ ] 1.5 `docs/help/08-config.md`：补 admin 段 5 键说明（排水窗口含双侧行为与 0 值语义）
- [ ] 1.6 新建 `tests/test_system_settings_config.py`：read_config admin 段回显（含缺省填充）/非法值拒绝/既有段零回归三组用例；dashboard 前端构建与相关 API 测试回归
