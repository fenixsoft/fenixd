"""验证探针 s6：timeline 数据契约（API 响应数据源）全部 state 节点携带 backward 布尔。"""
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
    line("2026-09-08T12:00:00.000000Z", "Transition: api-spec ready → implementing"),
    line("2026-09-08T12:00:00.010000Z", "Updated SPEC 'api-spec'",
         updates={"status": "implementing"}),
    line("2026-09-08T12:06:00.000000Z", "Updated SPEC 'api-spec'",
         updates={"status": "ready", "error": "Recovered from interrupted state"}),
]
(logs / "fenixd.log").write_text("\n".join(lines) + "\n", encoding="utf-8")

tl = get_spec_timeline(tmp, "api-spec")
states = [e for e in tl if e["kind"] == "state"]
print("ALL_HAVE_BACKWARD="
      + str(all("backward" in e and isinstance(e["backward"], bool) for e in states)))
rec = [e for e in states if e["to"] == "ready"]
print("RECOVERY_BACKWARD=" + str(rec[0]["backward"] if rec else "MISSING"))
shutil.rmtree(tmp, ignore_errors=True)
