"""验证探针 s1：前缀名 spec 零泄漏（真实 get_spec_timeline 执行）。"""
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
    line("2026-09-08T12:00:00.000000Z", "Transition: add-foo ready → implementing"),
    line("2026-09-08T12:00:00.010000Z", "Updated SPEC 'add-foo'",
         updates={"status": "implementing"}),
    line("2026-09-08T12:01:00.000000Z", "Transition: add-foo-ui implemented → testing"),
    line("2026-09-08T12:01:00.010000Z", "Updated SPEC 'add-foo-ui'",
         updates={"status": "testing"}),
    line("2026-09-08T12:02:00.000000Z", "Transition: add-foo-ui testing → verified"),
    line("2026-09-08T12:02:00.010000Z", "Updated SPEC 'add-foo-ui'",
         updates={"status": "verified"}),
    line("2026-09-08T12:03:00.000000Z", "Transition: add-foo-ui verified → done"),
    line("2026-09-08T12:03:00.010000Z", "Updated SPEC 'add-foo-ui'",
         updates={"status": "done"}),
    line("2026-09-08T12:04:00.000000Z", "Transition: add-foo-ui done → pushed"),
    line("2026-09-08T12:04:00.010000Z", "Updated SPEC 'add-foo-ui'",
         updates={"status": "pushed"}),
]
(logs / "fenixd.log").write_text("\n".join(lines) + "\n", encoding="utf-8")

tl = get_spec_timeline(tmp, "add-foo")
states = [e for e in tl if e["kind"] == "state"]
print("BASE_TOS=" + json.dumps([e["to"] for e in states]))
leaked = [t for t in ("testing", "verified", "done", "pushed") if t in [e["to"] for e in states]]
print("LEAK=" + json.dumps(leaked))

tl2 = get_spec_timeline(tmp, "add-foo-ui")
states2 = [e for e in tl2 if e["kind"] == "state"]
print("UI_CHAIN=" + json.dumps(states2[0].get("chain") if states2 else []))
shutil.rmtree(tmp, ignore_errors=True)
