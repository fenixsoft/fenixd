"""验证探针 s2：from 推演保真——姊妹 spec pushed 更新在前时恢复直写行推演正确。"""
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
    # 泄漏源（修复前）：姊妹 spec 的 pushed 更新把推演指针顶到 pushed
    line("2026-09-08T12:05:00.010000Z", "Updated SPEC 'add-foo-ui'",
         updates={"status": "pushed"}),
    # add-foo 恢复直写：取消中断后重启恢复（无 Transition 行）
    line("2026-09-08T12:06:00.000000Z", "Updated SPEC 'add-foo'",
         updates={"status": "ready",
                  "error": "Recovered from interrupted state: implementing"}),
]
(logs / "fenixd.log").write_text("\n".join(lines) + "\n", encoding="utf-8")

tl = get_spec_timeline(tmp, "add-foo")
rec = [e for e in tl if e["kind"] == "state" and e["to"] == "ready"]
print("COUNT=" + str(len(rec)))
if rec:
    print("FROM=" + rec[0]["from"])
    print("REASON_HAS_RECOVERED=" + str("Recovered from interrupted state" in rec[0]["reason"]))
    print("BACKWARD=" + str(rec[0].get("backward")))
shutil.rmtree(tmp, ignore_errors=True)
