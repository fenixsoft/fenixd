## Context

`fenixd.py` `_check_admin_invoke_requests` 消费 Dashboard/CLI 写入的 `.fenix/admin_invoke_request.json`，构造信号时硬编码 `signal_type: "manual-intervention"`。处置收尾自动复位（`core/admin_monitor.py` `_reset_env_blocked_after_disposition`，调用点前置检查 `sig_type in DISPOSITION_AUTO_RESET_SIGNAL_TYPES`）因此对人工唤起通道永不命中。fix-verify-serving-disk-reclaim（2026-09-18）处置记录已点名：「升级/手动通道投递 admin 时透传底层 signal_type……使 _reset_env_blocked_after_* 不命中」，属桶 1 残余机制缺口。

## Goals / Non-Goals

- Goals：手动唤起处置成功后，底层信号属自动复位集合的 spec 能被框架机械复位，不需二次人工
- Non-Goals：不改前端/CLI 唤起入口（透传在 daemon 侧完成）；不改自动复位集合成员与复位路径本身；不改节流与 store 记录语义

## Decisions

- **D1 daemon 侧反查而非入口带参**：请求文件加字段的方案要求改 Dashboard/CLI 两条入口且旧格式请求文件兼容期行为含糊；daemon 消费时用既有 `admin_store` 查询（`unhandled_for` 同族）反查 spec 最近未处置信号的 signal_type，入口零改动、新旧请求文件通用。
- **D2 新增 `underlying_signal_type` 字段而非替换顶层类型**：若把顶层 signal_type 换成底层类型，store 记录/节流锚点/活动区展示全部跟着变，可能与自动检测通道的 latest_signal 节流互相吞并（既有注释明确「二者各自走 store 记录与节流锚点，互不吞并」）。独立字段让复位门扩展一处生效，其余零回归。
- **D3 复位门扩展收在判定点**：`admin_monitor.py` 调用点前置检查与 `_reset_env_blocked_after_disposition` 的守卫均改为「signal_type 或 underlying_signal_type 命中」，单点改动，orphaned_state 等独立复位路径不动。

## Risks / Trade-offs

- [反查到陈旧信号类型] → 只查未处置（非 handled）记录且取最新一条；处置完成后该记录被 mark_handled，二次唤起自然取到新信号。
- [透传字段被未来消费点误读] → 字段可选、缺省 None，仅复位门消费；在字段写入处注释语义与消费点清单。

## Migration Plan

纯增量字段与判定扩展，无存量数据迁移；daemon 重启后生效（重启由 supervisor 信号机制承接，不属本 SPEC 任务）。

## Open Questions
