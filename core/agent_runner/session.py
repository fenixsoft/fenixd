"""session.py — SessionTracker：resumable session id 提取与 usage 解析（claude CLI 流事件）（refactor-core-packages 阶段 3）。"""

from pathlib import Path
import json


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
        try:
            out["input_tokens"] = int(usage.get("input_tokens") or 0)
        except (TypeError, ValueError):
            out["input_tokens"] = 0
        try:
            out["output_tokens"] = int(usage.get("output_tokens") or 0)
        except (TypeError, ValueError):
            out["output_tokens"] = 0
        try:
            out["cache_creation_input_tokens"] = int(usage.get("cache_creation_input_tokens") or 0)
        except (TypeError, ValueError):
            out["cache_creation_input_tokens"] = 0
        try:
            out["cache_read_input_tokens"] = int(usage.get("cache_read_input_tokens") or 0)
        except (TypeError, ValueError):
            out["cache_read_input_tokens"] = 0
        # 成本字段：仅网关真实回传时非空（design D5 / spec「金额展示不伪造」）
        cost = result_event.get("total_cost_usd", result_event.get("cost_usd"))
        if cost is None:
            out["cost_usd"] = None
        else:
            try:
                out["cost_usd"] = float(cost)
            except (TypeError, ValueError):
                out["cost_usd"] = None
        return out
