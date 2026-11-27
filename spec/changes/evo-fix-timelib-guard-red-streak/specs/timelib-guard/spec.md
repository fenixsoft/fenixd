# 能力：timelib 时间语义守卫（timelib-guard）

## 目的

生产代码（core/ 全部 Python 与 fenixd.py）时间原语使用单一化：一律走 core/timelib.py 原语（now_utc / now_local / parse_ts / from_epoch / to_storage / fmt_display），AST 静态守卫拦截五类禁用模式（零参 now、utcnow、utcfromtimestamp、无 tz fromtimestamp、白名单外 fromisoformat），防止 naive 时间与本地/UTC 语义混淆回归。

## 守卫机制

- 扫描器：tests/fenix_guards.py scan_time_primitives；core/timelib.py 本体在扫描豁免清单内（原语实现自身可用底层调用）。
- 永久白名单 TIME_WHITELIST（tests/test_timelib_guard.py）：零豁免稳态棘轮，条目只许收缩、无对应违例的僵尸键报失败——语义是「存量豁免」，与临时登记正交。
- 已知红基线 KNOWN_RED_BASELINE（本能力新增）：临时登记清单，条目形态 (仓库相对路径, 模式名, 理由, 到期日 YYYY-MM-DD)。判定规则：
  - 基线条目命中的违例不计入失败分桶，但基线条目到期日早于今日即失败（回绿时限）；
  - 基线条目对应违例已消失（已修）即失败提示收缩（僵尸检测同款）；
  - 基线外违例非空即失败（现状语义）。
- 基线与白名单互不混用：新违例不得回填 TIME_WHITELIST，只能登记 KNOWN_RED_BASELINE 并带到期日。

## 修复语义约定

- epoch → 日分桶：走 timelib.from_epoch(...).date()（UTC 日桶，与写侧 aware UTC 分层约定同源；已由 code-fix 4fec3994c 合入），调用点禁止回退裸 fromtimestamp；「epoch → 本地日分桶」如需引入另行立项。
- ISO 串 → datetime/epoch：走 timelib.parse_ts（唯一解析入口，失败返 None，调用方保持既有 None 语义；naive 输入按本地时区解读是 timelib 唯一策略）。