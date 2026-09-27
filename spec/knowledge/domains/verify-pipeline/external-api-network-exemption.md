<!-- knowledge: capability=external-api-network-exemption rev=1 origin=prehistoric sources=git:44e1443ba-..2026-09-02 -->

# 外部 API 网络错误豁免

依赖外部 API 的验证场景可显式声明豁免网络类控制台错误，避免环境网络抖动污染裁决。

## 现行规则

- 场景字段 `external_net_errors_ok`，缺省 `False`：默认不豁免，外部 API 网络类控制台错误照常计为失败证据。
- 仅当场景显式声明 `external_net_errors_ok: true` 时，豁免「外部 API 网络类控制台错误」，不据此判 fail；序列化时只在 true 时落盘该字段。
- 豁免路径上，豁免标记本身不得被误计为控制台错误。
- 豁免是场景级显式声明，不做全局开关，不按 URL 自动推断。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基础规则
