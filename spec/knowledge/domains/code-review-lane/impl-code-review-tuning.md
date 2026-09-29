# 实现期审查调优参数

<!-- knowledge: capability=impl-code-review-tuning rev=2
     sources=spec/archive/2026-09-24-add-impl-code-review-tuning,spec/archive/2026-09-26-add-impl-ocr-parallel-lane -->

实现期收尾审查三个调优参数（单请求超时 / 并发 / 力度）的配置读取、run 级注入与设置页编辑。

## 规则

- 三个 `ConfigLoader` 读取器读取合并后配置（用户级默认 + 项目级覆盖由既有 `resolve_config` 深合并完成）中的 `verify.impl_code_review_timeout_sec` / `verify.impl_code_review_concurrency` / `verify.impl_code_review_effort`。
- 三者同型回退语义：键缺失、`verify` 节缺失或非 dict、类型非法、超出合法区间时一律返回缺省值（fail-open，脏值不中断派发、不抛异常）；三个读取器各自独立，互不影响（`effort` 非法不连带 `timeout_sec` 回退）。
- 缺省值与合法区间：`timeout_sec` 缺省 `600`（正整数，不设上界——超大值由 ocr 侧报错兜底，框架侧只保证正整数）；`concurrency` 缺省 `4`（正整数）；`effort` 缺省 `"low"`（白名单 `low`/`medium`/`high`）。
- 三键缺省由读取器单点提供，不进 `resolve_config` 的缺省填充列表（避免 defaults 与读取器双源漂移）。
- run 级 ocr 超时注入：`_write_run_ocr_config` 写入的 `custom_providers.fenix-impl` 条目含 `timeout_sec`（取读取器解析值），与既有 `api_key` / `url` / `protocol` / `model` 同批原子写入（tempfile + `os.replace`），不新增独立写路径；写失败记 WARNING 并返回 `None`，不阻塞 run 派发。
- 审查命令承载并发与力度：命令含 `--concurrency <concurrency>` 与 `--effort <effort>`（取值来自对应读取器）。
- `effort` 单通道注入：虽有同名持久化 ocr 配置键，不额外经 run 级配置注入它（双通道会产生遮蔽歧义）。
- 审查命令不含 `--max-tokens-budget`（按 token 硬中止会令多数文件判 failed，审查覆盖残缺）。
- 设置页「质量」页签提供三参数读取回显与可视化编辑：`timeout_sec` 数字输入（正整数，附单位「秒」，回显 `600`）、`concurrency` 数字输入（正整数，回显 `4`）、`effort` 下拉选择（low/medium/high，回显 `low`）。
- 三键登记进设置页受管键清单（受 sources 标注与合并回显管辖）、「同步用户级设置」按页白名单（`_SYNC_PAGE_KEYS["quality"]["verify"]`）与读/写两侧镜像；保存序列化三键写入对应作用域配置，不覆写未在表单中出现的其它配置键。
- `.fenix/config.template.yaml` 的 `verify` 段登记三键及注释（语义 + 缺省值）；`docs/help/09-config.md` 文档化三键的语义、缺省值与合法取值范围；`docs/help/08-dashboard.md` 描述质量页签三项设置。

## 溯源

- [2026-09-24 add-impl-code-review-tuning](spec/archive/2026-09-24-add-impl-code-review-tuning/) — 新建三调优参数：独立读取器与回退语义、run 级 timeout 注入（原子写、失败降级）、命令承载 `--concurrency`/`--effort`（禁 `--max-tokens-budget`）、质量页签编辑与模板/帮助文档登记。
- [2026-09-26 add-impl-ocr-parallel-lane](spec/archive/2026-09-26-add-impl-ocr-parallel-lane/) — `impl_code_review_concurrency` 缺省值由 2 调整为 4（显式配置不受影响）；内联提示词段随车道化摘除后，并发与力度由审查车道命令承载。
