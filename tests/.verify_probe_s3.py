"""验证探针 s3：前向直写节点 reason 置空 + backward=false + 不被就近 error 覆写。"""
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
    # 前向直写（无 Transition 行、无同行 error）——修复前会落「状态回退」兜底
    line("2026-09-08T12:01:00.000000Z", "Updated SPEC 'spec-x'",
         updates={"status": "implemented"}),
    # 10 分钟窗口内另一条带 error 的更新行（就近覆写射程内）
    line("2026-09-08T12:03:00.000000Z", "Updated SPEC 'spec-x'",
         updates={"status": "ready", "error": "验证失败，回退"}),
]
(logs / "fenixd.log").write_text("\n".join(lines) + "\n", encoding="utf-8")

tl = get_spec_timeline(tmp, "spec-x")
# 前向直写节点无 reason 会被折叠链吸收，扫折叠链中含 implemented 的节点
fwd = [e for e in tl if e["kind"] == "state"
       and "implemented" in (e.get("chain") or [e.get("to")])]
print("FWD_COUNT=" + str(len(fwd)))
if fwd:
    print("FWD_REASON_EMPTY=" + str(fwd[0]["reason"] == ""))
    print("FWD_BACKWARD=" + str(fwd[0].get("backward")))
    print("NO_BACKTRACK_TEXT=" + str("状态回退" not in fwd[0]["reason"]
                                     and "验证失败" not in fwd[0]["reason"]))
shutil.rmtree(tmp, ignore_errors=True)
