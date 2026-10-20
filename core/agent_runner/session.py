"""session.py — SessionTracker：resumable session id 提取与 usage 解析（claude CLI 流事件）（refactor-core-packages 阶段 3）。"""

from pathlib import Path
import json


def _to_int(value) -> int:
    """容错转 int：假值/非法值（None、非数值字符串等）统一回退 0（code-review item 7b1ad7313c54）。

    _extract_usage_info 的四个 token 字段原本各自复制一段同构的
    try/except (TypeError, ValueError) 容错转换，收敛为单一助手消除重复；
    ``value or 0`` 假值兜底与异常捕获口径和原四段逐字等价，容错思路与
    同包 token_budget._to_int / maintenance_runs._safe_int 一致（各自独立，不跨模块收敛）。
    code-review item 578ff5ba74ea：``int(float("inf"))`` 抛的是 OverflowError
    （畸形 usage 经网关回传或 JSON 往返可携带 Infinity），一并入捕、回退 0，
    口径与 token_budget._to_int（c7706d3ad78d）/ maintenance_runs._safe_int（dc8f109b8b60）对齐。
    """
    try:
        return int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0


class SessionTracker:
    """SessionTracker组件（门面 AgentRunner 的组合组件）。"""

    def __init__(self, pm):
        self._pm = pm  # 门面回引（design D3 规则 3：组件 → 门面 单向）

    @staticmethod
    def _resumable_session_id(
        session_id: str | None,
        session_provider: str | None,
        current_provider: str | None,
        reuse_worktree: bool,
    ) -> str | None:
        """决定本次 attempt 是否可 --resume（fix 跨 provider resume）。

        session 存在于其创建时的 CLAUDE_CONFIG_DIR；add-provider-failover 切换候选后
        baseurl/隔离目录均不同，携带旧 provider 的 session_id 去 --resume 必然
        'No conversation found with session ID' 秒挂——一次瞬态 unrecognized_model
        即烧尽全部 attempt。仅当 worktree 可复用且 provider 未变时才续跑。
        """
        if not reuse_worktree or not session_id:
            return None
        if session_provider != current_provider:
            return None
        return session_id

    @staticmethod
    def dsh_session_key(run_id: str) -> str:
        """dsh 通道的 fenixd 侧 session 记账键（add-dsh-adapter-integration 4.1：
        ``fenix-<run_id>`` 命名空间，design D3）。

        dsh 的 ``--session-id`` 是严格采纳语义（未知 id fail-loud），全新会话
        的 dsh 侧真实 id 由 session 事件回报（``session-<uuid>``，经投影 init
        落 run jsonl、_extract_session_id 原样取回）；本键是 fenixd 侧
        session 元数据的命名空间键（provider 指纹绑定的记账主体、采纳失败
        回退留痕的关联 id），MUST NOT 作为 ``--session-id`` 传给 dsh。
        """
        return f"fenix-{run_id}"

    @staticmethod
    def _extract_session_id(run_file: Path) -> str | None:
        """从 run 产物提取 session_id（供 --resume 续跑）。

        session_id 出现在两类事件：开头的 system/init 事件（会话建立时），以及
        结尾的 result 事件。max_turns/超时强杀时 CLI 不会输出 result 事件，
        必须从 init 事件取，否则 resume 在 Max turns 场景失效（fix）。
        文件不存在/损坏返回 None。
        """
        try:
            size = run_file.stat().st_size
            with run_file.open("rb") as f:
                if size > 65536:
                    f.seek(size - 65536)
                tail = f.read().decode("utf-8", "replace")
                f.seek(0)
                head = f.read(65536).decode("utf-8", "replace")
        except OSError:
            return None
        for chunk in (head, tail):
            for line in chunk.splitlines():
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(e, dict):
                    continue
                if e.get("type") == "result" and e.get("session_id"):
                    return e["session_id"]
                if e.get("type") == "system" and e.get("subtype") == "init" and e.get("session_id"):
                    return e["session_id"]
        return None

    @staticmethod
    def _extract_usage_info(result_event: dict | None) -> dict:
        """从 stream-json 终态 result 事件提取 usage 与成本（add-cost-observability D1）。

        返回结构固定（缺失字段按 0 / None 兜底），供收工处累加与展示层消费：
            {
              "input_tokens": int,            # input（含 prompt 缓存写/读，分项见下）
              "output_tokens": int,
              "cache_creation_input_tokens": int,
              "cache_read_input_tokens": int,
              "cost_usd": float | None,       # 网关回传 total_cost_usd 才非 None；不伪造
              "unobserved": True,             # result 缺失/非 dict 时才置位（见下）
            }

        Claude CLI stream-json 的 result 事件 usage 字段形如：
            {"input_tokens": N, "output_tokens": M,
             "cache_creation_input_tokens": C, "cache_read_input_tokens": R}
        旧版可能落在 ``total_cost_usd`` 或 ``cost_usd``。任何解析异常 → 全 0 / None（保守）。

        unobserved 语义（add-turn-limit-anchor-c design D4）：turn-limit/timeout
        等强杀路径无 result 终态事件，此时四数值键全 0 是**观测兜底**而非确认真实
        消耗为零——真实消耗大概率非零（对照 a2 实测成本证明）。result 为 None 或
        非 dict 时置 ``"unobserved": True``，供调用方区分「观测不到」与「确认为零」；
        正常 result 路径不置位。STATE 累计侧读固定四键，多余 key 自然忽略、不泄入
        展示层。调用方 12 处返回形状不变（向后兼容）。
        """
        empty = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "cost_usd": None,
        }
        if not isinstance(result_event, dict):
            return {**empty, "unobserved": True}
        usage = result_event.get("usage") or {}
        if not isinstance(usage, dict):
            usage = {}
        out = dict(empty)
        out["input_tokens"] = _to_int(usage.get("input_tokens"))
        out["output_tokens"] = _to_int(usage.get("output_tokens"))
        out["cache_creation_input_tokens"] = _to_int(usage.get("cache_creation_input_tokens"))
        out["cache_read_input_tokens"] = _to_int(usage.get("cache_read_input_tokens"))
        # 成本字段：仅网关真实回传时非空（design D5 / spec「金额展示不伪造」）
        cost = result_event.get("total_cost_usd")
        if cost is None:  # 键缺失或显式 null 均回退旧版键；显式判 None，0.0 不误回退
            cost = result_event.get("cost_usd")
        # cost 为 None 时 float(None) 抛 TypeError，由 except 归位 None（out 初始即 None）
        if cost is not None and type(cost) is bool:
            # bool 是 int 子类（code-review item 13ad2d001e8b，对齐
            # token_budget._check_token_budget 的 bool 钳制口径）：网关畸形回传
            # total_cost_usd=true 经 float() 成功折成 1.0 且是有限值，下游非有
            # 限值守卫拦不住，1.0 美元会真实累计进 STATE 成本——按缺失处理。
            cost = None
        try:
            out["cost_usd"] = float(cost)
        # OverflowError：JSON 任意精度往返可携带超大整数字面量（如 10**400），
        # float() 溢出——口径对齐 _to_int 兜底（code-review item 86f44192983b）
        except (TypeError, ValueError, OverflowError):
            out["cost_usd"] = None
        return out

    @staticmethod
    def extract_usage_info(result_event: dict | None) -> dict:
        """跨模块消费 ``_extract_usage_info`` 的公开入口（code-review item
        9795d1041268：harness 适配层按 design D8 只承诺依赖公开纯工具模块，
        不应锚定本类下划线私有成员）。产物与 ``_extract_usage_info`` 完全
        同一（直通转发）；类内既有消费路径与 runner 门面委托别名均不动。
        """
        return SessionTracker._extract_usage_info(result_event)
