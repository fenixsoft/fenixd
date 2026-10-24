"""token_budget.py — TokenAccountant：token 用量累计/预算检查/告警/验证链侧车（refactor-core-packages 阶段 2）。

无状态组件：STATE 累计与告警都实时经门面回引（self._pm.state_machine 等），
测试在构造后替换 runner.state_machine / runner.logger 的路径保持有效。
"""

from datetime import datetime, timezone
import math
import threading

# code-review item 7f6062e65ecb：_accumulate_token_usage 的「read_one 读旧值 →
# 内存相加 → update_spec 写回」跨两次 state_machine 调用，state_machine 的锁
# 只护单次调用（update_spec 单次原子、read_one 无锁），同 spec 并发收工时后写
# 者会用陈旧 prev_* 覆盖先写者的累计。per-spec 进程内锁把该读改写对串行化；
# 锁表本身用全局锁保护（锁只覆盖同进程线程，跨进程字段级覆盖由 update_spec
# 自身 flock 兜底单次写原子）。
_ACCUM_LOCKS_GUARD = threading.Lock()
# [fenix-ignore:c00c25def3a1] 每 spec 仅一个小 Lock、量级极小；收尾弹键会破坏「他线程持锁中被弹出」的互斥、weakref 在 CPython _thread.lock 上不可用，修复反引入并发复杂度，维持现状
_ACCUM_LOCKS = {}  # spec_name -> threading.Lock

# code-review item a8dd529ad6f3：_unobserved_runs 的 ``+= 1`` 是「读-改-写」三步
# 操作，多线程收工路径（impl-ocr 并行车道、dashboard 线程）下并发自增会互相
# 覆盖丢失增量，DEBUG 审计口径失真。比照 _ACCUM_LOCKS_GUARD 用模块级锁串行化
# 自增；计数器本身仍挂实例，锁取模块级是因为 _token_accountant 惰性 property
# 在并发首次访问下可能产出多个实例，实例锁会随实例分裂而失效。
_UNOBSERVED_GUARD = threading.Lock()


def _spec_accumulate_lock(spec_name: str) -> threading.Lock:
    with _ACCUM_LOCKS_GUARD:
        lock = _ACCUM_LOCKS.get(spec_name)
        if lock is None:
            lock = threading.Lock()
            _ACCUM_LOCKS[spec_name] = lock
        return lock


def _to_int(value) -> int:
    """非数值容错转 int，非法/缺失回退 0（code-review item f6e985eed424）。

    STATE 条目可能被人工编辑或由历史版本写入非数值字符串（如 '12abc'），
    裸 int() 抛 ValueError 会从 _accumulate_token_usage 冒泡打断收工累计；
    容错口径与同函数 _cost_usd 的 try/except (TypeError, ValueError) 对齐。
    code-review item c7706d3ad78d：int(float("inf")) 抛的是 OverflowError
    （usage_info 经 json 往返或网关畸形回传可携带 inf），一并入捕、回退 0，
    口径与同包 maintenance_runs._safe_int（dc8f109b8b60）对齐。
    """
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return 0


class TokenAccountant:
    """token 用量与预算告警组件（门面 AgentRunner 的组合组件）。"""

    def __init__(self, pm):
        self._pm = pm  # 门面回引（design D3 规则 3：组件 → 门面 单向）
        # add-turn-limit-anchor-c（D4）：unobserved usage 跳过累计的 DEBUG 留痕
        # 计数——供成本审计区分「确认为零」与「观测不到」（强杀路径真实消耗
        # 大概率非零）。仅内存计数 + DEBUG 日志，不新增 STATE 字段（展示层
        # 不伪造原则：无可展示的真实数字就不展示）。
        self._unobserved_runs = 0

    def _accumulate_token_usage(self, spec_name: str, usage_info: dict) -> None:
        """收工处累加本次 run 的 usage 到 STATE 内部字段（add-cost-observability D1）。

        ``_tokens_in`` = input + cache_creation + cache_read（保守计入缓存读，design D-风险）；
        ``_tokens_out`` = output。成本仅网关回传 total_cost_usd 时累计到 ``_cost_usd``，
        否则不写（不伪造，spec「金额展示不伪造」）。累加后触发预算阈值检查。

        unobserved 语义（add-turn-limit-anchor-c D4）：usage_info 带
        ``"unobserved": True``（强杀路径无 result 终态，四数值键全零只是观测
        兜底而非确认零）时**跳过累计**（全零本就不增），并计入 DEBUG 留痕计数
        供审计区分「零消耗」与「未观测」——不凭空补数、不把不可观测当零入账。

        state_machine 缺失（测试/未初始化）时安全跳过；STATE 条目缺失不写（spec 必已注册）。
        """
        if self._pm.state_machine is None:
            return
        if not isinstance(usage_info, dict):
            usage_info = {}
        if usage_info.get("unobserved"):
            # code-review item a8dd529ad6f3：自增取模块级锁串行化，避免多线程
            # 收工并发「读-改-写」互相覆盖丢失增量；锁内快照 total 供日志使用，
            # 保证日志数字与本次自增一致。
            with _UNOBSERVED_GUARD:
                self._unobserved_runs += 1
                total = self._unobserved_runs
            self._pm.logger.debug(
                "agent_runner",
                f"token usage unobserved for '{spec_name}' — skipped accumulation "
                f"(unobserved total: {total}, "
                f"add-turn-limit-anchor-c D4)",
            )
            return
        tokens_in = (
            _to_int(usage_info.get("input_tokens", 0))
            + _to_int(usage_info.get("cache_creation_input_tokens", 0))
            + _to_int(usage_info.get("cache_read_input_tokens", 0))
        )
        tokens_out = _to_int(usage_info.get("output_tokens", 0))
        cost = usage_info.get("cost_usd")

        # code-review item 7f6062e65ecb：同 spec 并发收工（impl-ocr 并行车道等
        # 同 spec 多 run 在飞，或 dashboard 线程同时 update_spec 同条目）时，
        # 跨两次调用的读改写不串行会导致后写者拿陈旧 prev_* 覆盖先写者的累计。
        # per-spec 锁内完成「读 → 相加 → 写回」整体。
        with _spec_accumulate_lock(spec_name):
            try:
                entry = self._pm.state_machine.read_one(spec_name) or {}
            except Exception as e:
                # code-review item 67824f1f7c03：读失败会永久漏计本轮 usage，与
                # 下方写失败 warning 留痕口径对齐（行为不变：仍跳过本轮累计）
                self._pm.logger.warning(
                    "agent_runner",
                    f"token 累计读 STATE 失败 '{spec_name}'，跳过本轮累计: {e}",
                )
                return
            if not isinstance(entry, dict):
                # code-review item 1cacd875677d：STATE 条目被损坏/误写为标量时
                # 不能静默吞掉——否则本轮及后续 usage 累计永久丢失且不可察觉，
                # 与上方读失败（67824f1f7c03）留痕口径对齐：WARNING 记录 spec
                # 与实际类型后跳过本轮累计（行为不变，仍不累计）
                self._pm.logger.warning(
                    "agent_runner",
                    f"token 累计读 STATE 条目类型异常 '{spec_name}'"
                    f"（{type(entry).__name__}），跳过本轮累计",
                )
                return
            prev_in = _to_int(entry.get("_tokens_in", 0))
            prev_out = _to_int(entry.get("_tokens_out", 0))
            new_in = prev_in + tokens_in
            new_out = prev_out + tokens_out
            # 缓存分项累计（spec 详情「缓存命中/命中率」展示）：字段缺失（历史 spec）从 0 起步
            prev_cache_read = _to_int(entry.get("_cache_read_tokens", 0))
            prev_cache_creation = _to_int(entry.get("_cache_creation_tokens", 0))
            updates = {
                "_tokens_in": new_in,
                "_tokens_out": new_out,
                "_cache_read_tokens": prev_cache_read
                + _to_int(usage_info.get("cache_read_input_tokens", 0)),
                "_cache_creation_tokens": prev_cache_creation
                + _to_int(usage_info.get("cache_creation_input_tokens", 0)),
            }
            # 成本：仅网关真实回传时累计；网关不回传则不写 _cost_usd（保持缺失语义）
            if cost is not None and type(entry.get("_cost_usd")) is bool:
                # code-review item ccbf36ac4b84：既有 _cost_usd 被人工/历史版本
                # 写成布尔值时，下方 ``float(entry.get("_cost_usd", 0) or 0)``
                # 会放行——true 经 float(True)=1.0 静默按 1 美元并入总额、false
                # 折 0，均无 warning 留痕，与同块非法字符串（918342f2200f）记
                # warning 后跳过的损坏值处置口径不一致。比照 _check_token_budget
                # （b75b390dd579）的 budget bool 钳制口径用 ``type(x) is bool``
                # 精确排除（bool 是 int 子类，isinstance 会连带误伤合法 int）：
                # 命中记 warning 后跳过本轮成本累计；token 分项不受影响，仍正常写回。
                self._pm.logger.warning(
                    "agent_runner",
                    f"token 累计既有成本值非法 '{spec_name}'"
                    f"（既有 _cost_usd={entry.get('_cost_usd')!r}，"
                    f"本轮 cost={cost!r}），跳过本轮成本累计",
                )
            elif cost is not None and type(cost) is bool:
                # code-review item c40186889899：本轮 usage_info.get("cost_usd")
                # 为布尔值时 float(True)=1.0 / float(False)=0.0 转换成功且为有限
                # 值，下方有限值守卫拦不住，成本被静默按 1/0 美元入账且无任何
                # 留痕——与既有 _cost_usd 的 bool 钳制（ccbf36ac4b84）及
                # _check_token_budget（b75b390dd579）/maintenance_runs 的全仓
                # bool 剔除口径不一致（生产调用方经 _extract_usage_info 归一后
                # bool 已折 None，此处为调用方绕过归一直传裸 dict 的纵深防御）。
                # 比照上方既有值钳制同口径用 ``type(cost) is bool`` 精确排除
                # （bool 是 int 子类，isinstance 会连带误伤合法 int）：记 warning
                # 后跳过本轮成本累计；token 分项不受影响，仍正常写回。
                self._pm.logger.warning(
                    "agent_runner",
                    f"token 累计本轮成本值非法 '{spec_name}'"
                    f"（本轮 cost={cost!r}），跳过本轮成本累计",
                )
            elif cost is not None:
                try:
                    prev_cost = float(entry.get("_cost_usd", 0) or 0)
                    total_cost = prev_cost + float(cost)
                except (TypeError, ValueError, OverflowError):
                    # code-review item 918342f2200f：既有 _cost_usd（或本轮 cost）
                    # 为非法值时不能静默吞掉——本轮合法成本被丢弃且损坏值原样
                    # 滞留，之后每一轮合法成本都会在同一分支继续被丢弃、成本观测
                    # 永久失真。比照上方读失败（67824f1f7c03）/类型异常
                    # （1cacd875677d）的留痕口径：记 warning（含 spec 名与双方
                    # 实际值形态）后跳过本轮成本累计；token 分项不受影响，仍正常
                    # 写回。
                    # code-review item 864a2142f6f3：cost 或既有 _cost_usd 为超大
                    # 整数（JSON/YAML 任意精度往返，如 10**400）时 float() 抛
                    # OverflowError，同样沿收尾调用链冒泡中断累计路径——入捕，
                    # 口径与同模块 _to_int（c7706d3ad78d）/预算读取
                    # （858e28e2e186）对齐。
                    self._pm.logger.warning(
                        "agent_runner",
                        f"token 累计成本值非法 '{spec_name}'"
                        f"（既有 _cost_usd={entry.get('_cost_usd')!r}，"
                        f"本轮 cost={cost!r}），跳过本轮成本累计",
                    )
                else:
                    # code-review item 864a2142f6f3：inf/nan 经 float() 转换成功、
                    # 穿透上方 except，静默写入 _cost_usd 会因 inf/NaN 的吸收性
                    # 持续污染后续每一轮求和。非有限值比照 _check_token_budget
                    # （b75b390dd579）的 NaN/inf 兜底口径：记 warning 后跳过本轮
                    # 成本累计，不写 _cost_usd；token 分项不受影响。
                    if not math.isfinite(total_cost):
                        self._pm.logger.warning(
                            "agent_runner",
                            f"token 累计成本值非有限 '{spec_name}'"
                            f"（既有 _cost_usd={entry.get('_cost_usd')!r}，"
                            f"本轮 cost={cost!r}，累计结果={total_cost!r}），"
                            f"跳过本轮成本累计",
                        )
                    else:
                        updates["_cost_usd"] = total_cost
            try:
                self._pm.state_machine.update_spec(spec_name, updates)
            except Exception as e:
                self._pm.logger.warning(
                    "agent_runner",
                    f"token 累计写 STATE 失败 '{spec_name}': {e}",
                )
                return
        # 预算阈值检查（D4）：80% / 100% 均为警告级，不自动冻结
        self._check_token_budget(spec_name, new_in)

    def _check_token_budget(self, spec_name: str, tokens_in: int) -> None:
        """预算阈值告警（add-cost-observability D4）：80% / 100% 均为警告级，幂等不重复。

        配置 ``agents.token_budget_millions``（缺省 50，0=关闭）。越过 80% 线发警告级告警
        并置位 ``_token_warn_80``；越过 100% 线发警告级告警并置位 ``_token_alert_100``
        （2026-09-01 用户决策：两档均降为警告，不发严重事件）。
        告警 MUST NOT 修改 spec 状态（不自动冻结，design 决策有意为之）。
        """
        budget = self._pm._get_config("agents.token_budget_millions", 50)
        # code-review item 8a37762cf313：config 若被误写成非法字符串（如 "8a"），
        # 裸 budget <= 0 比较抛 TypeError、float() 抛 ValueError，沿锁外的
        # _accumulate_token_usage 调用点冒泡到 runner 收工路径，中断其后的验证链
        # 侧车与指标记录；纯数字字符串（如 "80"）则被 float() 静默接受为合法
        # 预算，不记 warning 也不回退缺省。容错口径与同模块 _to_int 对齐：非法
        # 值记 warning 并回退缺省 50，保证预算检查永不向收工路径抛异常。
        # code-review item b75b390dd579：NaN/inf 经 float() 成功且穿透下方
        # ``not budget or budget <= 0`` 守卫（not nan 与 nan <= 0 均为 False），
        # ratio 变 NaN 后 80%/100% 两档比较恒 False，预算告警被静默禁用且无
        # warning 留痕；bool（true）经 float(True)=1.0 被误读为 1M 预算。比照
        # 同模块 _positive_number 的 NaN/inf 兜底与 _record_daily_provider_attempt
        # 的 bool 排除口径统一钳制：畸形值记 warning 并回退缺省 50。
        # code-review item 858e28e2e186：config 被写成巨大整型（YAML 任意精度，
        # 如 10**400）时 float(budget) 抛 OverflowError，不在 (TypeError,
        # ValueError) 捕获范围内，同样会沿收工路径冒泡中断其后的验证链侧车。
        # 入捕后统一走 budget_ok=False 回退缺省 50，口径与 infra_breaker.
        # threshold/cooldown_minutes 的同类守卫一致。
        budget_ok = True
        if type(budget) is bool:
            budget_ok = False
        else:
            try:
                budget = float(budget)
            except (TypeError, ValueError, OverflowError):
                budget_ok = False
            else:
                if budget != budget or budget in (float("inf"), float("-inf")):
                    budget_ok = False
                elif budget < 0:
                    # code-review item d988dcfea775：负数（如 -5，多半是漏敲符号
                    # 的配置笔误）此前穿透校验后在下方 budget <= 0 处与合法关闭
                    # 值 0 一样静默 return，无任何留痕。比照同块 bool/NaN/inf 口径
                    # 统一记 warning 并回退缺省 50；关闭语义只保留 0 一个文档化入口。
                    budget_ok = False
        if not budget_ok:
            self._pm.logger.warning(
                "agent_runner",
                f"agents.token_budget_millions 配置非法 {budget!r}，回退缺省 50M",
            )
            budget = 50.0
        if not budget or budget <= 0:
            return  # 0 = 唯一合法的关闭入口（负数已在上方校验块回退缺省 50）
        budget_tokens = budget * 1_000_000
        if budget_tokens <= 0:
            return
        # code-review item ccbe24b883c0：tokens_in 恒为 int（_to_int 全分支回退
        # int），但超大整数（STATE 被人工写为 10**400，或网关畸形回传 usage）在
        # int/float 除法里触发 int→float 转换抛 OverflowError——本调用点在锁外且
        # 无 try 保护，异常沿 _accumulate_token_usage 冒泡到收工路径，中断其后的
        # 验证链侧车，与上方 config（858e28e2e186）/cost（864a2142f6f3）「检查
        # 永不向收工路径抛异常」的防护口径不一致。比照 cost 侧口径入捕：预算信息
        # 不可用，记 warning 后跳过本轮预算检查；合法值除法行为不变。
        try:
            ratio = tokens_in / budget_tokens
        except OverflowError:
            self._pm.logger.warning(
                "agent_runner",
                f"token 累计值超大（预算信息不可用）'{spec_name}'"
                f"（_tokens_in={tokens_in!r}），跳过本轮预算检查",
            )
            return

        # code-review item d005329ef9d3：「查标志-发告警-置位」跨 read_one/
        # update_spec 两次 state_machine 调用，锁外执行时同 spec 并发收工
        # （impl-ocr 并行车道等）双方都读到 flag=False，各自发一条 80%/100%
        # 告警并各写一次 STATE——docstring 承诺的「幂等不重复」在并发窗口内
        # 不成立。复用 _spec_accumulate_lock 把「查标志-判定-置位」并成临界区
        # （threading.Lock 不可重入：调用点 _accumulate_token_usage 须在锁外
        # 调本方法，本方法内不得再经持锁路径被调用）。config 读取与 ratio
        # 计算不涉共享标志，留在锁外保持临界区最小。
        # code-review item 9fff308e34f4：告警发射（_send_token_alert 的 LLM
        # 叙事自 upgrade-narrative-to-investigation 3.1 起已异步补叙化——
        # schedule_narrative 只起后台线程零阻塞；此前经 attach_narrative →
        # build_narrative 同步调用带超时可达数十秒）不得占住临界区——同 spec
        # 并发收工线程会在锁入口被阻塞拖慢收尾。锁内只完成「是否本线程发射」
        # 的判定与标志置位读改写，锁释放后再发射；发射权由锁内置位判定唯一化，
        # 同阈值仍只发一次，语义不变。
        fire_100 = False
        fire_80 = False
        with _spec_accumulate_lock(spec_name):
            try:
                entry = self._pm.state_machine.read_one(spec_name) or {}
            except Exception as e:
                # code-review item b6e08ef1cbbc：读失败时标志真值不可知（可能早已
                # 置位），按「未置位」继续会在 STATE 短暂不可读窗口内每次收工重复
                # 发射同档告警（下方置位写失败本就静默 pass，封不住重发）。比照
                # 上游 _accumulate_token_usage 的读失败口径：记 warning 后直接
                # return 跳过本轮检查，「幂等不重复」在读失败窗口同样成立。锁内
                # return，由 with 释放 _spec_accumulate_lock，持锁结构不变。
                self._pm.logger.warning(
                    "agent_runner",
                    f"token 预算检查读 STATE 失败 '{spec_name}'，跳过本轮检查: {e}",
                )
                return
            if not isinstance(entry, dict):
                # code-review item b3a08d363a84：STATE 条目被损坏/误写为标量时
                # 不能静默置空继续——两枚标志恒读 False，置位写对损坏条目若不
                # 生效，同 spec 每轮收工都会重复发射同档告警，正落入上方
                # b6e08ef1cbbc 注释所述的重复告警面。比照同函数读失败
                # （b6e08ef1cbbc）与上游 _accumulate_token_usage 类型异常
                # （1cacd875677d）口径：记 warning 后直接 return 跳过本轮检查。
                # 锁内 return，由 with 释放 _spec_accumulate_lock，持锁结构不变。
                self._pm.logger.warning(
                    "agent_runner",
                    f"token 预算检查读 STATE 条目类型异常 '{spec_name}'"
                    f"（{type(entry).__name__}），跳过本轮检查",
                )
                return
            warn_flag = bool(entry.get("_token_warn_80", False))
            alert_flag = bool(entry.get("_token_alert_100", False))

            if ratio >= 1.0:
                # code-review item 77b028d83c3b：无条件接管 ratio>=1.0，归一遗留
                # 不一致态——c41873e0bfa2 修复只封死「首次越过 100%」时的补发路径，
                # 未归一已存在的不一致 STATE（条目为修复部署前写入：旧 100% 分支
                # 只置 _token_alert_100，或 _token_warn_80 被人工清除）：旧首分支
                # 因 alert_flag=True 被跳过，ratio>=0.8 的 elif 便会向已超 100% 的
                # spec 补发「预算 80% 提醒告警」，先 100% 后 80% 的倒置时间线仍会
                # 出现一次。现在：alert 未置位才发 100% 告警；无论是否告警，只要
                # warn_flag 未置位就顺带补写 _token_warn_80=True（不发 80% 告警），
                # 把遗留不一致态一次性归一。
                fire_100 = not alert_flag
                if not alert_flag or not warn_flag:
                    try:
                        # code-review item c41873e0bfa2：从 80% 以下一次性越到 100%
                        # 以上时同步置位低档标志——tokens_in 单调递增，两标志同写
                        # 即可彻底封死补发路径。
                        self._pm.state_machine.update_spec(
                            spec_name, {"_token_alert_100": True, "_token_warn_80": True}
                        )
                    except Exception:
                        pass
            elif ratio >= 0.8 and not warn_flag:
                fire_80 = True
                try:
                    self._pm.state_machine.update_spec(spec_name, {"_token_warn_80": True})
                except Exception:
                    pass
        # 锁外发射（9fff308e34f4）：临界区内只剩 STATE 读改写，慢速 LLM 叙事
        # 调用不再阻塞同 spec 并发收工的锁入口。
        if fire_100:
            self._send_token_alert(spec_name, tokens_in, budget, "warning", "预算 100% 警告")
        elif fire_80:
            self._send_token_alert(spec_name, tokens_in, budget, "warning", "预算 80% 提醒告警")

    def _send_token_alert(
        self, spec_name: str, tokens_in: int, budget: float, severity: str, title: str
    ) -> None:
        """写一条 token 预算 human-escalation-alert（复用 AdminStore，与 pm_engine 同管道）。

        severity 统一为 warning（80%/100% 两档均为警告级，2026-09-01 用户降噪决策）。
        告警携带裁决注册表 choices（ignore/freeze_stop_loss/raise_budget）时保持
        未处理进待处理队列——前端告警区只对 unhandled 记录渲染裁决下拉，且
        alert-resolve 对 handled 记录 409 拒绝，born-handled 会让快照的 choices
        永不可消费、注册表与 alert-resolve 的 token_budget 场景全部落空
        （code-review item ded34cd04dc5；对本信号有意调整 2026-09-01
        「警告级不进待办」的降噪口径——「知情确认」选项本身即降噪出口）。
        choices 为空（信号未来退出注册表）时维持旧降噪决策：写入即标记
        handled，仅留历史记录。不修改 spec 状态。
        """
        try:
            from core.admin_store import AdminStore, ESCALATION, severity_needs_human

            store = AdminStore(self._pm.project_root, self._pm.logger)
            pct = tokens_in / (float(budget) * 1_000_000) * 100.0
            payload = {
                "kind": ESCALATION,
                "signal_type": "token_budget",
                "spec": spec_name,
                "severity": severity,
                "description": (
                    f"{title}：spec '{spec_name}' 累计 input token 已用 "
                    f"{tokens_in / 1_000_000:.2f}M / 预算 {budget:.0f}M（{pct:.0f}%）"
                ),
                "evidence": (
                    f"_tokens_in={tokens_in}; budget_millions={budget}; " f"ratio={pct:.1f}%"
                ),
                "recommended_action": (
                    "检查是否失控烧钱；如需冻结请在 Dashboard / STATE.md 人工处置"
                    "（本告警不自动冻结 spec）"
                ),
            }
            # add-human-adjudication-choices 2.6：token_budget 在裁决注册表内
            # （ignore/freeze_stop_loss/raise_budget）——发射点快照 choices 进
            # 告警记录（本路径直写 AdminStore，不经 _send_human_escalation_alert）。
            from core.dashboard.data.adjudication_choices import choices_for

            choices = choices_for("token_budget")
            if choices:
                payload["choices"] = list(choices)
            rec = store.append(payload)
            # 注册表覆盖（choices 已快照）→ 保持未处理进待办队列，选项才有人可
            # 执行（item ded34cd04dc5）；无 choices 的警告级仍按 2026-09-01 降噪
            # 决策 born-handled，不占待办
            # code-review item 3e202131bd3a：文件损坏留底被下限保护拒写时 append
            # 返回 None（core/admin_store.py append 契约，item 2570ca391771：
            # 记录未落盘，按未落地处理）——此时跳过 born-handled 闭环标记，避免
            # rec["id"] 抛 TypeError 被外层误记为「Failed to send token budget
            # alert」（告警本就未落盘，崩溃在 mark_handled 阶段使归因失真）。
            if rec is not None:
                # upgrade-narrative-to-investigation 3.1：告警已以机械文案落盘，
                # 注册表内信号（choices 已快照）落盘后调度后台补叙（侧车承载，
                # alert_id 取落地记录 id；叙事时延/失败零阻塞本发射路径）。
                if choices:
                    from core.adjudication_narrative import schedule_narrative

                    schedule_narrative(rec["id"], payload, self._pm)
                # born-handled 分支（choices 分支与 append None 守卫的完整解释
                # 见上方 rec 判空前的共享注释，不再重复）
                if not choices and not severity_needs_human(severity):
                    store.mark_handled(rec["id"])
            self._pm.logger.warning(
                "agent_runner",
                f"token budget alert ({severity}) for '{spec_name}': "
                f"{tokens_in / 1_000_000:.2f}M / {budget:.0f}M",
            )
        except Exception as e:
            self._pm.logger.error(
                "agent_runner",
                f"Failed to send token budget alert for '{spec_name}': {e}",
            )

    def _record_verify_progress_tokens(
        self, spec_name: str, agent_type: str, usage_info: dict
    ) -> None:
        """验证链侧车：把 planner run 的 usage 逐轮追加到 tokens.json（D3）。

        路径 ``.fenix/verify-progress/<spec>/tokens.json``，结构：
            {"runs": [{"agent_type": "planner-plan", "timestamp": "...",
                       "input_tokens": N, "output_tokens": M, "cost_usd": X|null}, ...]}
        场景执行为 Python 无 LLM，不入。报告合成时按本侧车求和（task 2.2）。

        仅 agent_type 以 ``planner`` 开头时记录；非 LLM run（verifier 场景执行）不计。
        code-review item 7b8aa5d1aa64 口径澄清：judge 不入本侧车——dispute-judge/
        spec-review 走 run_dispute_judge/run_spec_review 直连收工路径，不经本函数的
        两个调用点（_finalize_success / _exhausted_result），故「本链增量 Token」
        实际只覆盖 planner 消耗。
        写入失败静默跳过（观测增强，不能阻断主流程）。
        """
        if not isinstance(agent_type, str) or not agent_type.startswith("planner"):
            return
        if not isinstance(usage_info, dict):
            usage_info = {}
        # code-review item 1e3f44bb351f：usage_info 带 unobserved=True（turn-limit/
        # timeout 强杀路径，四数值键全零只是观测兜底而非确认零）时跳过本侧车
        # 落盘——对齐 _accumulate_token_usage 的 D4 口径：不把不可观测当零入账，
        # 逐轮记录不得呈现为「确认零消耗」。
        if usage_info.get("unobserved"):
            return
        tokens_json = (
            self._pm.project_root / ".fenix" / "verify-progress" / spec_name / "tokens.json"
        )
        # code-review item f58099cfae63：锁 + 原子写副本（fcntl flock + mkstemp +
        # fsync + os.replace，约 55 行）与同包 maintenance_runs._append_token_run
        # 逐行同构却各自演进（条目键形态、临时文件清理写法已现微差）——直接委托
        # 公共助手，消除双份漂移面。惰性 import：maintenance_runs 不依赖本模块，
        # 无 import 环。
        from core.agent_runner.maintenance_runs import (
            _append_token_run,
            _token_usage_fields,
        )

        entry = {
            "agent_type": agent_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **_token_usage_fields(usage_info),
        }
        _append_token_run(tokens_json, entry)
