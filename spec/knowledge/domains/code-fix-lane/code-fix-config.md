# code-fix 车道配置

<!-- knowledge: capability=code-fix-config rev=1
     sources=spec/archive/2026-09-26-add-code-review-auto-fix -->

`admin.code_review_fix.*` 配置段：自动修复总开关与批大小，含校验、缺省语义、Dashboard 读写与设置页 UI。

## 规则

### 参数与缺省
- `admin.code_review_fix.enabled`：总开关，缺省 `false`，严格 bool（非 bool 值回退 `false`）。
- `admin.code_review_fix.batch_size`：每批条目数，缺省 `20`，须为正整数（bool、≤0、非整数回退 `20`）。
- 读取器为 `ConfigLoader.get_code_review_fix_config(config)`（形态对齐既有 `get_code_review_config`）：段非 dict 视为缺省；段缺失不报错，返回 `{"enabled": False, "batch_size": 20}`。

### Dashboard 受管键读写
- `_SOURCE_KEYS` 含 `"admin.code_review_fix"`；定义缺省回显常量 `_DEFAULT_CODE_REVIEW_FIX = {"enabled": False, "batch_size": 20}` 并在 `read_config` 缺省段回显；`read_config` / `read_effective_config` 经 `get_code_review_fix_config` 回显生效值；`_deep_merge_managed` 支持该段合并写入。
- `write_config` 前置校验 `enabled` 严格 bool、`batch_size` 正整数，非法明确失败，不静默忽略、不半写。
- `_SYNC_PAGE_KEYS` 的 `quality` 页签以 `"admin": ["code_review_fix"]` 形态登记（用户级同步）；段缺失时读侧回显缺省，不得 500。

### 模板与文档
- `.fenix/config.template.yaml` 含 `admin.code_review_fix` 段示例（`enabled: false` / `batch_size: 20`）；该入库文件的 admin 段以整段注释的惰性形态存在，不得写成未注释的活配置（那会改变所有项目的生效缺省）。
- `docs/help/09-config.md` 的「Dashboard 设置页与配置键映射」表含两个键的映射行，并有专节说明语义与缺省。

### 设置页 UI
- 设置页「质量」页签的「代码质量」卡片内、「周期性代码审查」之后渲染「自动修复代码问题」开关与批大小输入：开关绑定 `code_review_fix_enabled`（回填自 `config.code_review_fix?.enabled === true`）；批大小绑定 `code_review_fix_batch_size`（数值输入，合法范围 1–1000，缺失回填 20）。
- 保存必须经同一个 `<Form>` 实例提交 `code_review_fix: {enabled, batch_size}`，不得因控件脱管而提交恒缺省值。
- 前端 service 类型含 `CodeReviewFixConfig { enabled?, batch_size? }` 与 `ConfigData.code_review_fix?`。

## 溯源

- [2026-09-26 2026-09-26-add-code-review-auto-fix](spec/archive/2026-09-26-add-code-review-auto-fix/) — 新建本页：enabled/batch_size 参数定义与非法回退、Dashboard 受管键读写链、模板与帮助文档同步、设置页质量页签开关与批大小。
