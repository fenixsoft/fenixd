"""验证探针 s5：既有 Transition 回退节点回归——reason 兜底文案与 backward 不变。"""
import json, tempfile, shutil, sys
from pathlib import Path
sys.path.insert(0, ".")
from core.dashboard.data import get_spec_timeline


def line(ts, msg, **ctx):
    e = {"timestamp": ts, "level": "INFO", "component": "state_machine", "message": msg}
    if ctx:
        e["context"] = ctx
    return json.dumps(e, ensure_ascii=False)


tmp = tempfile.mkdtemp()
logs = Path(tmp) / ".fenix" / "logs"
logs.mkdir(parents=True)
lines = [
    line("2026-09-08T12:00:00.000000Z", "Transition: spec-x ready → implementing"),
    line("2026-09-08T12:00:00.010000Z", "Updated SPEC 'spec-x'",
         updates={"status": "implementing"}),
    line("2026-09-08T12:02:00.000000Z", "Transition: spec-x implemented → testing"),
    line("2026-09-08T12:02:00.010000Z", "Updated SPEC 'spec-x'",
         updates={"status": "testing"}),
    # 真实回退：testing → implementing（Transition 行）
    line("2026-09-08T12:03:00.000000Z", "Transition: spec-x testing → implementing"),
    line("2026-09-08T12:03:00.010000Z", "Updated SPEC 'spec-x'",
         updates={"status": "implementing"}),
]
(logs / "fenixd.log").write_text("\n".join(lines) + "\n", encoding="utf-8")

tl = get_spec_timeline(tmp, "spec-x")
back = [e for e in tl if e["kind"] == "state"
        and e["from"] == "testing" and e["to"] == "implementing"]
print("BACK_COUNT=" + str(len(back)))
if back:
    print("REASON=" + back[0]["reason"])
    print("BACKWARD=" + str(back[0].get("backward")))
shutil.rmtree(tmp, ignore_errors=True)
