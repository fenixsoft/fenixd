"""本地重放冻结场景（implementer 验证修复轮专用，不入库运行时）。

用法: python3 replay_scenarios.py <frozen_test_scenarios.json> [scenario_id ...]
- navigate base http://localhost:8787 → http://127.0.0.1:19004 (dev-server 服务 worktree statics)
- VisualDiffer 读取 project_root/.fenix/verify-progress/<spec>/baselines
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.verify_engine.engine import VerifyEngine

WORKTREE = Path(__file__).resolve().parents[2]
BASE_OLD = "http://localhost:8787"
BASE_NEW = "http://127.0.0.1:19004"


async def main():
    frozen = Path(sys.argv[1]).resolve()
    only = set(sys.argv[2:])
    raw = json.loads(frozen.read_text())
    for s in raw:
        for st in s.get("steps", []):
            if st.get("action") == "navigate" and BASE_OLD in (st.get("value") or ""):
                st["value"] = st["value"].replace(BASE_OLD, BASE_NEW)
            # mock_api 的 glob 目标同样要指向 dev-server，否则 mock 不命中走真实 API
            if st.get("action") == "mock_api" and BASE_OLD in (st.get("target") or ""):
                st["target"] = st["target"].replace(BASE_OLD, BASE_NEW)
        # 逐场景重放时，depends_on 拓扑无意义且只跑子集时会被依赖阻塞
        s.pop("depends_on", None)
    if only:
        raw = [s for s in raw if s["id"] in only]

    engine = VerifyEngine("impl-scratch-v2cfg-replay", WORKTREE)
    report = await engine.run(raw)
    print(json.dumps(report["summary"], ensure_ascii=False))
    for s in report["scenarios"]:
        if s["status"] == "pass":
            continue
        print(f"== {s['scenario_id']} [{s['status']}]")
        for a in s.get("assertion_results", []):
            if not a.get("pass"):
                print("   ASSERT FAIL:", a.get("type"), a.get("selector"), "| expected:", a.get("expected"), "| actual:", str(a.get("actual"))[:80])
        for st in s.get("step_results", []):
            if not st.get("success"):
                print("   STEP FAIL:", st.get("action"), st.get("target"), str(st.get("error"))[:200])
    vis = [s for s in report["scenarios"] for v in (s.get("visual_results") or []) if not v.get("pass")]
    print("visual-diff warn count:", len(vis))


if __name__ == "__main__":
    asyncio.run(main())
