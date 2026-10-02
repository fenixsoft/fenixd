# SPEC 自动归档
<!-- knowledge: capability=auto-spec-archive rev=1
     sources=spec/archive/2026-09-09-add-spec-archive -->

终态 SPEC 积压超过阈值时，daemon 按完成时间从最久到最新自动把目录移入 `spec/archive/`，保持 `spec/changes/` 只留活跃工作。

## 规则

- 配置键 `archive.auto_threshold`（用户级与项目级均可设置，项目级优先，参与配置热更新）：done/pushed 终态 SPEC 的未归档数量超过阈值时触发自动归档；缺省 50；设为 0 表示禁用。
- daemon 主循环以独立低频计时（分钟级）周期检查每个项目：统计状态为 done/pushed 且未归档（`spec/changes/<name>/` 目录仍存在）的 SPEC 数量。
- 完成时间取 `STATE.md` 条目的 `updated` 字段（终态 SPEC 的 entry 恒定不变，`updated` 即完成时间）。
- 阈值为 0 时跳过检查，不做任何归档；未配置时按缺省 50 生效。
- 非终态（如 implementing）与已归档条目不计入阈值统计。
- 单个 SPEC 归档失败（如目标目录已存在）时跳过该条并记录日志，继续处理其余，不中断检查循环。
- 设置页「其他」面板提供阈值输入控件（非负整数，0 = 禁用说明），与既有 `runs.keep` 字段并列；保存后（含直接编辑配置文件）经热更新生效，无需重启 daemon。

## 溯源

- 2026-09-09 2026-09-09-add-spec-archive（spec/archive/2026-09-09-add-spec-archive） — 新增自动归档：阈值配置与设置页控件、daemon 周期检查与最久优先归档、单条失败不阻塞
