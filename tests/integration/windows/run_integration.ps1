# =============================================================================
# run_integration.ps1 — Windows 集成测试驱动（W11 dockur 过机通道）
# =============================================================================
# 在真实 Windows Guest 内执行（SSH 通道或 RDP 进入后；代码经 /shared 的
# Z: 盘或 UNC 直读）。依次：依赖自检 → 平台面 pytest 子集 → G1 清单逐项
# 驱动 → 汇总退出码。任一环节失败退出码非零；SKIP 必须在输出留环境阻塞
# 证据。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File \\host.lan\Data\fenixd\tests\integration\windows\run_integration.ps1
#   （或映射 Z: 后：cd Z:\fenixd\tests\integration\windows 再 -File run_integration.ps1）
# =============================================================================

$ErrorActionPreference = "Continue"

# 框架根 = 本脚本所在目录向上三级（tests/integration/windows → 框架根）。
# 注意不可用 Resolve-Path：对 UNC 它返回 "Microsoft.PowerShell.Core\FileSystem::"
# provider 前缀路径，powershell -File / python 都无法消费——必须走 .NET
# GetFullPath 归一成纯文件系统路径。
$FrameworkRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\.."))
$ChecklistPath = Join-Path $PSScriptRoot "g1_full_parity_checklist.md"

Write-Host "================================================================"
Write-Host "  fenixd Windows 集成测试"
Write-Host "  FrameworkRoot: ${FrameworkRoot}"
Write-Host "================================================================"

# ── 1. 依赖自检 ───────────────────────────────────────────────────
$Py = $null
foreach ($candidate in @("py", "python")) {
    try { $null = & $candidate --version 2>$null } catch { }
    if ($LASTEXITCODE -eq 0) { $Py = $candidate; break }
}
if (-not $Py) {
    Write-Host "[FAIL] python not found - run install.ps1 at framework root first"
    exit 1
}
if ($Py -eq "py") { $Py = @("py", "-3") } else { $Py = @("python") }

& $Py[0] $Py[1..($Py.Count - 1)] -c "import psutil, win32api" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] psutil/pywin32 missing - run install.ps1 at framework root first"
    exit 1
}
Write-Host "[OK] deps ready"

# ── 2. 平台面 pytest 子集（真实 win32 API 面）──────────────────────
Write-Host "-- platform pytest subset --"
Push-Location $FrameworkRoot
& $Py[0] $Py[1..($Py.Count - 1)] -m pytest tests/test_platform_pal.py tests/test_platform_guard.py -q
$PytestRc = $LASTEXITCODE
Pop-Location
if ($PytestRc -ne 0) {
    Write-Host "[FAIL] platform pytest not green (exit=$PytestRc)"
    exit $PytestRc
}
Write-Host "[OK] platform pytest green"

# ── 3. G1 清单逐项驱动 ────────────────────────────────────────────
# 清单条目 = G1-NN 编号；驱动器按编号调用本文件下方的步骤实现
# （G1 步骤注册表），清单 md 是权威定义（新增条目须同步注册实现）。
$Results = @{}

# ── G1 驱动共享助手 ───────────────────────────────────────────────
# 统一经 Invoke-G1Py / Start-G1Py 调 Python：兼容 py -3 与 python 两种形态，
# 避免把数组直接放命令位。$script:PyCmd = 解释器前缀（python 形态为 1 元素）。
$script:PyCmd = @($Py[0]) + @($Py | Select-Object -Skip 1)
$script:G1Proj = Join-Path $env:TEMP "fenix-g1\init-demo"   # G1-02 产出的骨架工程

function Invoke-G1Py {
    # 前台跑 python（stdout 透传），退出码 $LASTEXITCODE
    $pyArgs = @()
    if ($script:PyCmd.Count -gt 1) { $pyArgs = $script:PyCmd[1..($script:PyCmd.Count - 1)] }
    & $script:PyCmd[0] @pyArgs @args
}

function Start-G1Py {
    # 后台起 python 脚本：Start-G1Py -PyArgs @("script.py","--port","8787") -OutFile x.log -ErrFile e.log
    param([string[]]$PyArgs, [string]$OutFile, [string]$ErrFile)
    $pre = @()
    if ($script:PyCmd.Count -gt 1) { $pre = $script:PyCmd[1..($script:PyCmd.Count - 1)] }
    $spl = @{
        FilePath = $script:PyCmd[0]
        ArgumentList = ($pre + $PyArgs)
        PassThru = $true
        WindowStyle = "Hidden"
    }
    if ($OutFile) { $spl.RedirectStandardOutput = $OutFile }
    if ($ErrFile) { $spl.RedirectStandardError = $ErrFile }
    return Start-Process @spl
}

function New-G1Work([string]$Id) {
    $d = Join-Path $env:TEMP "fenix-g1\$Id"
    New-Item -ItemType Directory -Force -Path $d | Out-Null
    return $d
}

function Test-G1Proj {
    # G1-03+ 都消费 G1-02 的骨架；缺失时直接 FAIL 并留证（环境未就绪证据）
    if (Test-Path (Join-Path $script:G1Proj ".fenix\config.yaml")) { return $true }
    Write-Host ("[FAIL-GUARD] skeleton missing: {0} (G1-02 must pass first)" -f $script:G1Proj)
    return $false
}

function Register-G1Spec([string]$Name) {
    # fenix_spec new 只建目录、不写状态（STATE.md 注册属 /fenix-new LLM 命令面
    # 流程职责）；命令面发现机制读 .fenix\STATE.md（data.parse_state），不经
    # 文件系统扫描——驱动用 StateMachine.add_spec 补注册，使 SPEC 可被发现。
    $pyFile = Join-Path $env:TEMP "fenix-g1\register-$Name.py"
@"
import sys
sys.path.insert(0, r"$script:G1Proj\.fenix")
from core.state_machine import StateMachine
sm = StateMachine(r"$script:G1Proj\.fenix\STATE.md")
print("registered:", sm.add_spec("$Name", {}))
"@ | Set-Content $pyFile -Encoding UTF8
    Invoke-G1Py $pyFile 2>&1 | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Resolve-Nssm {
    # 三处探测：PATH → chocolatey → tools（pal._require_nssm 只探 PATH，win32.py）
    foreach ($p in @((Get-Command nssm.exe -ErrorAction SilentlyContinue).Source,
                     "C:\ProgramData\chocolatey\bin\nssm.exe",
                     "C:\tools\nssm\nssm.exe")) {
        if ($p -and (Test-Path $p)) { return $p }
    }
    return $null
}

function Start-G1Supervisor([string]$OutDir, [string]$Tag) {
    # supervisor 子进程即 daemon 看门狗（bin/fenixd_supervisor.py 平台无关直启 daemon）
    return Start-G1Py -PyArgs @((Join-Path $script:G1Proj ".fenix\bin\fenixd_supervisor.py"),
                                "--project-root", $script:G1Proj) `
        -OutFile (Join-Path $OutDir "$Tag.out.log") -ErrFile (Join-Path $OutDir "$Tag.err.log")
}

function Get-G1Runtime {
    $f = Join-Path $script:G1Proj ".fenix\daemon_runtime.json"
    if (-not (Test-Path $f)) { return $null }
    try { return Get-Content $f -Raw | ConvertFrom-Json } catch { return $null }
}

function Wait-G1DaemonPid([int]$Seconds = 30) {
    # 轮询 daemon_runtime.json 直到出现存活 pid（秒级收敛）
    foreach ($i in 1..$Seconds) {
        Start-Sleep 1
        $rt = Get-G1Runtime
        if ($rt -and $rt.pid -and (Get-Process -Id $rt.pid -ErrorAction SilentlyContinue)) { return $rt.pid }
    }
    return $null
}

function Stop-G1Tree([object]$Proc) {
    if ($Proc -and -not $Proc.HasExited) { Stop-Process -Id $Proc.Id -Force -ErrorAction SilentlyContinue }
}

# G1 步骤注册表：编号 → 幂等驱动块。条目实现遵循「最小可观测」原则——
# 每条只验证判据本身，产物落 $env:TEMP\fenix-g1\<id>\ 供取证。
$G1Steps = @{
    "G1-01" = {
        # 独立进程跑 install.ps1：脚本内的 `exit` 不会杀死本驱动会话，
        # 且与 CI/文档用法（powershell -File install.ps1）语义一致。
        powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $FrameworkRoot "install.ps1") | Out-Null
        return ($LASTEXITCODE -eq 0)
    }
    "G1-02" = {
        $work = Join-Path $env:TEMP "fenix-g1\init-demo"
        New-Item -ItemType Directory -Force -Path $work | Out-Null
        Push-Location $work
        # fenix-init 是无扩展名 Python 脚本（#!/usr/bin/env python3），
        # Windows 无 shebang 执行语义，必须显式经解释器调用。
        Invoke-G1Py (Join-Path $FrameworkRoot "fenix-init") . --name win-demo --type web 2>&1 | Out-Null
        $rc = $LASTEXITCODE
        Pop-Location
        return (($rc -eq 0) -and (Test-Path (Join-Path $work ".fenix\config.yaml")))
    }
    "G1-03" = {
        # judge: fenixd.py 常驻出现 + daemon_runtime.json 记 pid；第二 supervisor
        # 实例被单例锁拒绝秒退（fenixd.py daemon.lock）
        if (-not (Test-G1Proj)) { return $false }
        $work = New-G1Work "G1-03"
        if (-not (Test-Path (Join-Path $script:G1Proj ".fenix\bin\fenixd_supervisor.py"))) { return $false }
        $s1 = Start-G1Supervisor $work "sup1"
        $pid1 = Wait-G1DaemonPid 40
        $s2 = Start-G1Supervisor $work "sup2"
        foreach ($i in 1..12) { Start-Sleep -Milliseconds 800; if ($s2.HasExited) { break } }
        $singleton = $s2.HasExited
        $resident = ($null -ne $pid1)
        Stop-G1Tree $s2
        Stop-G1Tree $s1
        if ($pid1) { Stop-Process -Id $pid1 -Force -ErrorAction SilentlyContinue }
        ("resident={0} singleton={1} pid={2}" -f $resident, $singleton, $pid1) | Set-Content (Join-Path $work "verdict.txt")
        return ($resident -and $singleton)
    }
    "G1-04" = {
        # judge: 杀 daemon → supervisor 拉起新 pid 且 runtime 刷新；
        # proc_starttime 键在 Windows 现已落盘（supervisor ctypes GetProcessTimes），
        # 键缺失才 FAIL—— starttime 比对面收编即本条判据（不降级）。
        if (-not (Test-G1Proj)) { return $false }
        $work = New-G1Work "G1-04"
        $s1 = Start-G1Supervisor $work "sup1"
        $old = Wait-G1DaemonPid 40
        if (-not $old) { Stop-G1Tree $s1; return $false }
        Stop-Process -Id $old -Force
        $new = $null; $hasSt = $false
        foreach ($i in 1..45) {
            Start-Sleep 1
            $rt2 = Get-G1Runtime
            if ($rt2 -and $rt2.pid -and ($rt2.pid -ne $old) -and (Get-Process -Id $rt2.pid -ErrorAction SilentlyContinue)) {
                $new = $rt2.pid; $hasSt = ($null -ne $rt2.proc_starttime); break
            }
        }
        if ($new) { Stop-Process -Id $new -Force -ErrorAction SilentlyContinue }
        Stop-G1Tree $s1
        ("adopted={0} old={1} new={2} proc_starttime_present={3}" -f ($null -ne $new), $old, $new, $hasSt) | Set-Content (Join-Path $work "verdict.txt")
        return (($null -ne $new) -and $hasSt)
    }
    "G1-05" = {
        # judge: nssm install fenixd-win-demo + 服务态 RUNNING（sc query 数字态 4）
        if (-not (Test-G1Proj)) { return $false }
        $work = New-G1Work "G1-05"
        $nssm = Resolve-Nssm
        if (-not $nssm) {
            "nssm.exe not found (PATH / C:\ProgramData\chocolatey\bin / C:\tools\nssm)" | Set-Content (Join-Path $work "nssm-missing.txt")
            return $false
        }
        $env:PATH = "$(Split-Path $nssm);$env:PATH"   # pal._require_nssm 只探 PATH
        # 预清历轮半成品服务（断链轮遗留 SERVICE_PAUSED/STOPPED 会让 install 撞名或 start 报 PAUSED）
@"
import pathlib, sys
sys.path.insert(0, r"$FrameworkRoot")
from core.systemd_hosting import unit_name_for
print(unit_name_for(pathlib.Path(r"$script:G1Proj")).replace(".service", ""))
"@ | Set-Content (Join-Path $work "svcname.py") -Encoding UTF8
        $svcName = (Invoke-G1Py (Join-Path $work "svcname.py") 2>$null | Select-Object -Last 1)
        if ($svcName) {
            (& $nssm stop $svcName) 2>$null | Out-Null
            (& $nssm remove $svcName confirm) 2>$null | Out-Null
        }
@"
import json, pathlib, sys
sys.path.insert(0, r"$FrameworkRoot")
from core.platform import api as pal
from core.systemd_hosting import unit_name_for
root = pathlib.Path(r"$script:G1Proj")
r = pal.install_unit(root)   # 幂等：已 RUNNING 时 already=True
name = unit_name_for(root).replace(".service", "")
pathlib.Path(root, ".fenix", "service_name.txt").write_text(name, encoding="utf-8")
print(json.dumps({"install": r, "name": name, "is_running": pal.is_running(root)}))
"@ | Set-Content (Join-Path $work "install.py") -Encoding UTF8
        Invoke-G1Py (Join-Path $work "install.py") 2>&1 | Set-Content (Join-Path $work "install.json")
        $name = Get-Content (Join-Path $script:G1Proj ".fenix\service_name.txt") -ErrorAction SilentlyContinue
        (& $nssm status $name) 2>&1 | Set-Content (Join-Path $work "nssm-status.txt")   # 证据留档（NSSM 原生输出 UTF-16LE，勿用正则判）
        $svc = Get-Service $name -ErrorAction SilentlyContinue                          # SCM API 原生判态：Running ≡ sc query 态 4
        $j = Get-Content (Join-Path $work "install.json") -Raw -ErrorAction SilentlyContinue
        return (($j -match '"is_running": true') -and ($svc -and $svc.Status -eq "Running"))
    }
    "G1-06" = {
        # judge: nssm stop → 服务 STOPPED + 无孤儿 daemon/supervisor 残留
        if (-not (Test-G1Proj)) { return $false }
        $work = New-G1Work "G1-06"
        $nssm = Resolve-Nssm
        if (-not $nssm) { return $false }
        $env:PATH = "$(Split-Path $nssm);$env:PATH"
@"
import json, pathlib, sys
sys.path.insert(0, r"$FrameworkRoot")
from core.platform import api as pal
root = pathlib.Path(r"$script:G1Proj")
pal.stop(root)
print(json.dumps({"is_running": pal.is_running(root)}))
"@ | Set-Content (Join-Path $work "stop.py") -Encoding UTF8
        Invoke-G1Py (Join-Path $work "stop.py") 2>&1 | Set-Content (Join-Path $work "stop.json")
        $name = Get-Content (Join-Path $script:G1Proj ".fenix\service_name.txt") -ErrorAction SilentlyContinue
        (& $nssm status $name) 2>&1 | Set-Content (Join-Path $work "nssm-status.txt")
        Start-Sleep 2
        $projEsc = [regex]::Escape($script:G1Proj)
        $orphans = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match "fenixd(_supervisor)?\.py" -and $_.CommandLine -match $projEsc }
        $orphans.CommandLine | Set-Content (Join-Path $work "orphans.txt")
        $j = Get-Content (Join-Path $work "stop.json") -Raw -ErrorAction SilentlyContinue
        return (($j -match '"is_running": false') -and (-not $orphans))
    }
    "G1-07" = {
        # judge: 8787 监听 + 200；SO_EXCLUSIVEADDRUSE → 第二实例 bind 失败拒绝（非静默劫持）
        $work = New-G1Work "G1-07"
        $dash = Join-Path $FrameworkRoot "bin\fenix_dashboard.py"
        $p1 = Start-G1Py -PyArgs @($dash, "--serve", "--port", "8787") -ErrFile (Join-Path $work "inst1.err.log")
        $ok200 = $false
        foreach ($i in 1..20) { Start-Sleep 1
            try { if ((Invoke-WebRequest "http://127.0.0.1:8787/" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) { $ok200 = $true; break } } catch {} }
        $p2 = Start-G1Py -PyArgs @($dash, "--serve", "--port", "8787") -ErrFile (Join-Path $work "inst2.err.log")
        # 两种合法终态：非 serve 占用者 → p2 拒绝退出(rc≠0)；同身份旧 serve → p2 接管(p1 亡 p2 活)
        foreach ($i in 1..15) { Start-Sleep 1; if ($p2.HasExited -or $p1.HasExited) { break } }
        $rejected = $p2.HasExited -and ($p2.ExitCode -ne 0)
        $tookover = (-not $p2.HasExited) -and $p1.HasExited
        Get-Content (Join-Path $work "inst2.err.log") -ErrorAction SilentlyContinue | Set-Content (Join-Path $work "inst2.rejection.txt")
        Stop-G1Tree $p1
        Stop-G1Tree $p2
        return ($ok200 -and ($rejected -or $tookover))
    }
    "G1-08" = {
        # judge: 对旧实例端口再启动 → 旧实例被接管终止，≤9s 重绑成功
        $work = New-G1Work "G1-08"
        $dash = Join-Path $FrameworkRoot "bin\fenix_dashboard.py"
        $a = Start-G1Py -PyArgs @($dash, "--serve", "--port", "8787") -ErrFile (Join-Path $work "a.err.log")
        foreach ($i in 1..20) { Start-Sleep 1
            try { (Invoke-WebRequest "http://127.0.0.1:8787/" -UseBasicParsing -TimeoutSec 2) | Out-Null; break } catch {} }
        $t0 = Get-Date
        $b = Start-G1Py -PyArgs @($dash, "--serve", "--port", "8787") -ErrFile (Join-Path $work "b.err.log")
        # 先等旧实例亡（接管信号生效；B 经 UNC 导入醒来需数秒），再轮 200 计重绑耗时
        foreach ($i in 1..12) { Start-Sleep 1; if ($a.HasExited) { break } }
        $elapsed = $null; $back = $false
        foreach ($i in 1..15) { Start-Sleep 1
            try { if ((Invoke-WebRequest "http://127.0.0.1:8787/" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) {
                $elapsed = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1); $back = $true; break } } catch {} }
        $aDead = $a.HasExited   # 旧实例经接管路径终止
        Stop-G1Tree $a
        Stop-G1Tree $b
        ("back200={0} elapsed_s={1} old_dead={2}" -f $back, $elapsed, $aDead) | Set-Content (Join-Path $work "verdict.txt")
        return ($back -and $aDead -and ($null -ne $elapsed) -and ($elapsed -le 9))
    }
    "G1-09" = {
        # judge: serve 进程收 CTRL_BREAK → 优雅停机闭包走完（端口释放），非硬死
        $work = New-G1Work "G1-09"
@"
import json, subprocess, sys, time, urllib.request
sys.path.insert(0, r"$FrameworkRoot")
from core.platform import api as pal
p = subprocess.Popen([sys.executable, r"$FrameworkRoot" + r"\bin\fenix_dashboard.py", "--serve", "--port", "8787"],
                     creationflags=0x200)
up = False
for _ in range(20):
    time.sleep(1)
    try:
        up = urllib.request.urlopen("http://127.0.0.1:8787/", timeout=2).status == 200
        if up: break
    except Exception:
        pass
pal.terminate_graceful(p)   # stdin EOF -> CTRL_BREAK -> grace -> TerminateProcess
rc = p.wait(30)
down = False
for _ in range(3):
    try:
        urllib.request.urlopen("http://127.0.0.1:8787/", timeout=2)
    except Exception:
        down = True
        break
    time.sleep(1)
print(json.dumps({"up": up, "exitcode": str(rc), "down": down}))
"@ | Set-Content (Join-Path $work "graceful.py") -Encoding UTF8
        Invoke-G1Py (Join-Path $work "graceful.py") 2>&1 | Set-Content (Join-Path $work "graceful.json")
        $j = Get-Content (Join-Path $work "graceful.json") -Raw -ErrorAction SilentlyContinue
        return (($j -match '"up": true') -and ($j -match '"down": true'))
    }
    "G1-10" = {
        # judge: 分层击杀 stdin EOF → CTRL_BREAK → TerminateProcess 全链生效；
        # 子进程树（孙进程）无残留
        $work = New-G1Work "G1-10"
        $gpFile = Join-Path $work "grandchild.pid"
@"
import json, sys, time
sys.path.insert(0, r"$FrameworkRoot")
from core.platform import api as pal
import psutil
gp_file = r"$gpFile"
child_code = (
    "import subprocess;"
    "g=subprocess.Popen(['ping','-n','60','127.0.0.1'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
    "open(r'{0}','w').write(str(g.pid));"
    "g.wait()"
).format(gp_file)
p = pal.spawn_detached([sys.executable, "-c", child_code])   # Popen 句柄（terminate_graceful 契约）
gpid = None
for _ in range(10):
    time.sleep(0.5)
    try:
        gpid = int(open(gp_file).read())
        break
    except Exception:
        pass
pal.terminate_graceful(p)
rc = p.wait(30)
time.sleep(2)
gone = (gpid is None) or (not psutil.pid_exists(gpid))
probe0 = True
if p.pid:
    probe0 = (pal.kill_tree(p.pid, 0, caller="g1-10", resolve=False) is not True)
print(json.dumps({"child_exit": str(rc), "grandchild_gone": gone, "probe0_false": bool(probe0)}))
"@ | Set-Content (Join-Path $work "layered.py") -Encoding UTF8
        Invoke-G1Py (Join-Path $work "layered.py") 2>&1 | Set-Content (Join-Path $work "layered.json")
        $j = Get-Content (Join-Path $work "layered.json") -Raw -ErrorAction SilentlyContinue
        return (($j -match '"grandchild_gone": true') -and ($j -match '"probe0_false": true'))
    }
    "G1-11" = {
        # judge: 子进程再派孙进程，父（驱动进程）自然退出 → Job 句柄关闭 →
        # KILL_ON_JOB_CLOSE 使孙进程一并消亡
        $work = New-G1Work "G1-11"
        $gpFile = Join-Path $work "grandchild.pid"
@"
import subprocess, sys
sys.path.insert(0, r"$FrameworkRoot")
from core.platform import api as pal
child_code = (
    "import subprocess,sys;"
    "sys.path.insert(0,r'{0}');"
    "from core.platform import api as pal;"
    "pal.bind_to_parent();"
    "g=subprocess.Popen(['ping','-n','60','127.0.0.1'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
    "open(r'{1}','w').write(str(g.pid));"
    "g.wait()"
).format(r"$FrameworkRoot", r"$gpFile")
p = pal.spawn_detached([sys.executable, "-c", child_code], new_session=True)
import os, time
for _ in range(30):
    if os.path.exists(r"$gpFile"):
        break
    time.sleep(0.5)   # 等子进程完成 bind + 写 pid 再退；父先亡会掐死 import 期子进程
print(p.pid)
"@ | Set-Content (Join-Path $work "bind_exit.py") -Encoding UTF8
        Invoke-G1Py (Join-Path $work "bind_exit.py") 2>&1 | Set-Content (Join-Path $work "bind.out.txt")   # 父退出即「父死」触发 KILL_ON_JOB_CLOSE
        $gpid = $null
        foreach ($i in 1..10) { Start-Sleep 1; $gpid = Get-Content $gpFile -ErrorAction SilentlyContinue; if ($gpid) { break } }
        Start-Sleep 4
        $gone = $false
        if ($gpid) { $gone = ($null -eq (Get-Process -Id $gpid -ErrorAction SilentlyContinue)) }
        ("grandchild={0} gone={1}" -f $gpid, $gone) | Set-Content (Join-Path $work "verdict.txt")
        return $gone
    }
    "G1-12" = {
        # judge: 真 CTRL_BREAK 死法落 Windows 闭集标签；143 数字形态不误标
        # （win32.exit_code_signal_name 已 DWORD 归一有符号 wait 形态）
        $work = New-G1Work "G1-12"
@"
import json, os, signal, subprocess, sys, time
sys.path.insert(0, r"$FrameworkRoot")
from core.platform import api as pal
p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                     creationflags=0x200)   # python 默认 CTRL_BREAK 处理器即死（ping 会自捕获打统计继续跑）
time.sleep(1)
os.kill(p.pid, signal.CTRL_BREAK_EVENT)   # 同组投递 -> 0xC000013A 控制台事件死法族
rc = p.wait(15)
print(json.dumps({
    "real_ctrl_break_rc": str(rc),
    "label_signed": pal.exit_code_signal_name(rc),
    "label_unsigned": pal.exit_code_signal_name(0xC000013A),
    "external_kill": pal.exit_code_signal_name(0xFFFFFFFF),
    "external_kill_signed": pal.exit_code_signal_name(-1),
    "sigterm_143_not_mislabeled": pal.exit_code_signal_name(143),
    "posix_neg15_not_mislabeled": pal.exit_code_signal_name(-15),
    "zero": pal.exit_code_signal_name(0)}))
"@ | Set-Content (Join-Path $work "labels.py") -Encoding UTF8
        Invoke-G1Py (Join-Path $work "labels.py") 2>&1 | Set-Content (Join-Path $work "labels.json")
        $j = Get-Content (Join-Path $work "labels.json") -Raw -ErrorAction SilentlyContinue
        return (($j -match '"label_signed": "CTRL_BREAK"') -and
                ($j -match '"label_unsigned": "CTRL_BREAK"') -and
                ($j -match '"external_kill": "SIGKILL"') -and
                ($j -match '"external_kill_signed": "SIGKILL"') -and
                ($j -match '"sigterm_143_not_mislabeled": null') -and
                ($j -match '"posix_neg15_not_mislabeled": null'))
    }
    "G1-13" = {
        # 已由第 2 环节 pytest 子集覆盖：test_msvcrt_lock_two_process_mutual_exclusion
        # （tests/test_platform_pal.py Windows-only 层）即本条判据本体——
        # 双进程 pal.try_lock 互斥、他方持锁返回 None。
        return $true
    }
    "G1-14" = {
        # judge: junction 免提权成功；跨卷目录落 copy 降级并留痕
        # （无第二卷时跨卷面仅落证不判 FAIL——清单环境阻塞证据纪律）
        $work = New-G1Work "G1-14"
        $src = Join-Path $work "src"
        New-Item -ItemType Directory -Force -Path $src | Out-Null
        Set-Content (Join-Path $src "a.txt") "g1-14"
@"
import json, os, shutil, sys
sys.path.insert(0, r"$FrameworkRoot")
from core.platform import api as pal
work = r"$work"
src = os.path.join(work, "src")
dst = os.path.join(work, "dst-link")
if os.path.lexists(dst):
    if os.path.islink(dst):
        os.rmdir(dst)   # 目录链接/网络挂载点：仅摘链（isdir 跟链会误选 rmtree 崩）
    elif os.path.isdir(dst):
        shutil.rmtree(dst)
    else:
        os.remove(dst)

def is_link(p):
    try:
        os.readlink(p)
        return True
    except OSError:
        return False

pal.ensure_link(src, dst)   # symlink -> CreateJunction -> copytree
junction_ok = is_link(dst) and open(os.path.join(dst, "a.txt")).read().strip() == "g1-14"
sysdrive = os.environ.get("SystemDrive", "C:")
vol = None
for d in "CDEFGH":
    r = d + ":\\"
    if (d + ":") != sysdrive and os.path.isdir(r):
        try:
            if shutil.disk_usage(r).free > (1 << 20):
                vol = r
                break
        except OSError:
            pass
cross = {"volume": vol, "copied": None, "was_link": None}
if vol:
    xdst = os.path.join(vol, "fenix-g1", "G1-14", "dst-copy")
    os.makedirs(os.path.dirname(xdst), exist_ok=True)
    if os.path.lexists(xdst):
        (shutil.rmtree if os.path.isdir(xdst) else os.remove)(xdst)
    pal.ensure_link(src, xdst)
    cross = {"volume": vol, "copied": (not is_link(xdst)) and os.path.isfile(os.path.join(xdst, "a.txt")), "was_link": is_link(xdst)}
print(json.dumps({"junction_ok": junction_ok, "cross": cross}))
"@ | Set-Content (Join-Path $work "link.py") -Encoding UTF8
        Invoke-G1Py (Join-Path $work "link.py") 2>&1 | Set-Content (Join-Path $work "link.json")
        $j = Get-Content (Join-Path $work "link.json") -Raw -ErrorAction SilentlyContinue
        $okJ = $j -match '"junction_ok": true'
        $okC = -not ($j -match '"copied": false')   # 无第二卷 → copied:null → 只判 junction 并落证
        return ($okJ -and $okC)
    }
    "G1-15" = {
        # judge: 并发 atomic_write_text 同一文件内容完整无截断（os.replace
        # 占用抖动 20ms×5 重试兜底）
        $work = New-G1Work "G1-15"
@"
import concurrent.futures, json, pathlib, sys
sys.path.insert(0, r"$FrameworkRoot")
from core.fs_utils import atomic_write_text
target = pathlib.Path(r"$work") / "target.txt"

def w(k):
    ok = 0
    for i in range(25):
        try:
            atomic_write_text(target, ("X" * 4096) + ":worker{}:{}\n".format(k, i))
            ok += 1
        except Exception:
            pass
    return ok

with concurrent.futures.ThreadPoolExecutor(4) as ex:
    done = sum(ex.map(w, range(4)))
data = target.read_text(encoding="utf-8") if target.exists() else ""
print(json.dumps({"writes_ok": done, "final_len": len(data),
                  "no_interleave": data.startswith("X" * 4096) and data.count("\n") == 1}))
"@ | Set-Content (Join-Path $work "atomic.py") -Encoding UTF8
        Invoke-G1Py (Join-Path $work "atomic.py") 2>&1 | Set-Content (Join-Path $work "atomic.json")
        $j = Get-Content (Join-Path $work "atomic.json") -Raw -ErrorAction SilentlyContinue
        return (($j -match '"writes_ok": 100') -and ($j -match '"no_interleave": true'))
    }
    "G1-16" = {
        # judge: /fenix-status 数据面（bin/fenix_status.py）全 SPEC 进度渲染正常
        if (-not (Test-G1Proj)) { return $false }
        $work = New-G1Work "G1-16"
        Invoke-G1Py (Join-Path $script:G1Proj ".fenix\bin\fenix_status.py") 2>&1 | Set-Content (Join-Path $work "status.out.json")
        $rc = $LASTEXITCODE
        $body = Get-Content (Join-Path $work "status.out.json") -Raw -ErrorAction SilentlyContinue
        $ok = $false
        if ($rc -eq 0 -and $body) {
            try { $null = $body | ConvertFrom-Json; $ok = $true } catch { $ok = ($body.Length -gt 100) }  # JSON 或富文本渲染均可
        }
        return $ok
    }
    "G1-17" = {
        # judge: /fenix-process <spec> 单 SPEC 详细进度呈现（g1-demo 需先存在且
        # 在 .fenix\STATE.md 注册——发现机制读状态文件不扫文件系统）
        if (-not (Test-G1Proj)) { return $false }
        $work = New-G1Work "G1-17"
        Invoke-G1Py (Join-Path $script:G1Proj ".fenix\bin\fenix_spec.py") "new" "g1-demo" 2>$null | Out-Null
        Register-G1Spec "g1-demo" | Out-Null
        Invoke-G1Py (Join-Path $script:G1Proj ".fenix\bin\fenix_process.py") "g1-demo" 2>&1 | Set-Content (Join-Path $work "process.out.json")
        $rc = $LASTEXITCODE
        $body = Get-Content (Join-Path $work "process.out.json") -Raw -ErrorAction SilentlyContinue
        return (($rc -eq 0) -and ($body -match "g1-demo"))
    }
    "G1-18" = {
        # judge: /fenix-new 原生生成器建 SPEC 立项骨架（幂等：先清残留 g1-demo）
        if (-not (Test-G1Proj)) { return $false }
        $work = New-G1Work "G1-18"
        foreach ($loc in @("spec\changes\g1-demo", "spec\archive\g1-demo")) {
            $p = Join-Path $script:G1Proj $loc
            if (Test-Path $p) { Remove-Item -Recurse -Force $p -ErrorAction SilentlyContinue }
        }
        Invoke-G1Py (Join-Path $script:G1Proj ".fenix\bin\fenix_spec.py") "new" "g1-demo" 2>&1 | Set-Content (Join-Path $work "new.out.json")
        $rc = $LASTEXITCODE
        Register-G1Spec "g1-demo" | Out-Null   # /fenix-new 全流程含状态注册
        $made = (Test-Path (Join-Path $script:G1Proj "spec\changes\g1-demo"))
        $body = Get-Content (Join-Path $work "new.out.json") -Raw -ErrorAction SilentlyContinue
        return (($rc -eq 0) -and $made -and ($body -match "g1-demo"))
    }
    "G1-19" = {
        # judge: /fenix-approve 脚本面（StateMachine 读面）跑通；push 步骤需 git
        # remote 不入判据。评审车道 spawn/击杀面已由 G1-09/10 覆盖。
        if (-not (Test-G1Proj)) { return $false }
        $work = New-G1Work "G1-19"
@"
import json, sys
sys.path.insert(0, r"$script:G1Proj\.fenix")
from core.state_machine import StateMachine
sm = StateMachine(r"$script:G1Proj\.fenix\STATE.md")
done = sm.get_by_status("done")
print(json.dumps({"ok": True, "done_count": len(done)}))
"@ | Set-Content (Join-Path $work "lane.py") -Encoding UTF8
        Invoke-G1Py (Join-Path $work "lane.py") 2>&1 | Set-Content (Join-Path $work "lane.json")
        return (Select-String -Path (Join-Path $work "lane.json") -Pattern '"ok": true' -Quiet)
    }
    "G1-20" = {
        # judge: /fenix-archive → spec/archive 落位（g1-demo 缺失则幂等自建）
        if (-not (Test-G1Proj)) { return $false }
        $work = New-G1Work "G1-20"
        if (-not (Test-Path (Join-Path $script:G1Proj "spec\changes\g1-demo"))) {
            Invoke-G1Py (Join-Path $script:G1Proj ".fenix\bin\fenix_spec.py") "new" "g1-demo" 2>$null | Out-Null
        }
        Get-ChildItem (Join-Path $script:G1Proj "spec\archive") -Filter "*g1-demo" -ErrorAction SilentlyContinue |
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue   # 历轮归档残留幂等预清
        Invoke-G1Py (Join-Path $script:G1Proj ".fenix\bin\fenix_archive.py") "g1-demo" 2>&1 | Set-Content (Join-Path $work "archive.out.txt")
        $rc = $LASTEXITCODE
        # archive 落位带日期前缀（spec\archive\<date>-<name>），判据用通配
        return (($rc -eq 0) -and (Test-Path (Join-Path $script:G1Proj "spec\archive\*g1-demo")))
    }
    "G1-21" = {
        # judge: /fenix-dashboard 注册项目 + 跨项目视图可访问（200 + 注册项在册）
        $work = New-G1Work "G1-21"
        $dash = Join-Path $FrameworkRoot "bin\fenix_dashboard.py"
        Invoke-G1Py $dash "--add-project" $script:G1Proj 2>&1 | Out-Null
        $p = Start-G1Py -PyArgs @($dash, "--serve", "--port", "8787") -ErrFile (Join-Path $work "serve.err.log")
        $ok200 = $false; $registered = $false
        foreach ($i in 1..20) { Start-Sleep 1
            try { if ((Invoke-WebRequest "http://127.0.0.1:8787/" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) { $ok200 = $true; break } } catch {} }
        if ($ok200) {
            try {
                $api = Invoke-RestMethod "http://127.0.0.1:8787/api/projects" -TimeoutSec 3
                $names = ($api | Out-String)
                $registered = ($names -match [regex]::Escape($script:G1Proj)) -or ($names -match "win-demo")
            } catch {}
        }
        Stop-G1Tree $p
        ("http200={0} registered={1}" -f $ok200, $registered) | Set-Content (Join-Path $work "verdict.txt")
        return ($ok200 -and $registered)
    }
    "G1-22" = {
        # judge: daemon 已在时 restart_request 优雅重启链（收编既有 daemon，不双拉）
        if (-not (Test-G1Proj)) { return $false }
        $work = New-G1Work "G1-22"
        $s1 = Start-G1Supervisor $work "sup1"
        $old = Wait-G1DaemonPid 40
        if (-not $old) { Stop-G1Tree $s1; return $false }
        @{ reason = "g1-22-verify"; origin = "run_integration"; date = (Get-Date -Format "yyyy-MM-dd") } |
            ConvertTo-Json | Set-Content (Join-Path $script:G1Proj ".fenix\restart_request") -Encoding UTF8
        $new = $null
        foreach ($i in 1..45) {
            Start-Sleep 1
            $rt = Get-G1Runtime
            if ($rt -and $rt.pid -and ($rt.pid -ne $old) -and (Get-Process -Id $rt.pid -ErrorAction SilentlyContinue)) { $new = $rt.pid; break }
        }
        $rrGone = -not (Test-Path (Join-Path $script:G1Proj ".fenix\restart_request"))
        if ($new) { Stop-Process -Id $new -Force -ErrorAction SilentlyContinue }
        Stop-G1Tree $s1
        ("restarted={0} old={1} new={2} request_cleared={3}" -f ($null -ne $new), $old, $new, $rrGone) | Set-Content (Join-Path $work "verdict.txt")
        return (($null -ne $new) -and $rrGone)
    }
    "G1-23" = {
        # judge: 原型评审链——假原型落位 + 项目注册 + dashboard 伺服 +
        # proto_serve 端到端验证（其 rc=0 即内部已验评审地址 200）
        $work = New-G1Work "G1-23"
        $protoDir = Join-Path $script:G1Proj ".fenix\prototypes\g1-proto"
        New-Item -ItemType Directory -Force -Path $protoDir | Out-Null
        Set-Content (Join-Path $protoDir "index.html") "<html><body>g1-23 proto</body></html>"
        $dash = Join-Path $FrameworkRoot "bin\fenix_dashboard.py"
        $serve = Join-Path $FrameworkRoot "skills\fenix-prototype\scripts\proto_serve.py"
        if (-not (Test-Path $serve)) {
            "proto_serve.py missing: $serve" | Set-Content (Join-Path $work "missing.txt")
            return $false
        }
        Invoke-G1Py $dash "--add-project" $script:G1Proj 2>&1 | Out-Null
        $p = Start-G1Py -PyArgs @($dash, "--serve", "--port", "8787") -ErrFile (Join-Path $work "serve.err.log")
        $ok200 = $false
        foreach ($i in 1..20) { Start-Sleep 1
            try { if ((Invoke-WebRequest "http://127.0.0.1:8787/" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) { $ok200 = $true; break } } catch {} }
        $served = $false
        if ($ok200) {
            Invoke-G1Py $serve "--project" $script:G1Proj "--spec" "g1-proto" "--dashboard-port" "8787" --json 2>&1 |
                Set-Content (Join-Path $work "proto.out.json")
            $served = ($LASTEXITCODE -eq 0)
        }
        Stop-G1Tree $p
        return $served
    }
    "G1-24" = { return $true }  # 已由第 2 环节 pytest 子集覆盖
    "G1-25" = { return $true }  # 同上（guard 集在 pytest 子集内）
}

# 未注册实现步骤的条目 = SKIP（留证据；等价于环境未就绪，不计 PASS）。
$CheckIds = Select-String -Path $ChecklistPath -Pattern '^\| (G1-\d+) \|' |
    ForEach-Object { $_.Matches[0].Groups[1].Value }

$PassCount = 0
$SkipCount = 0
$FailList = @()
foreach ($id in $CheckIds) {
    if (-not $G1Steps.ContainsKey($id)) {
        Write-Host ("[SKIP] {0} (no driver registered - see README discipline)" -f $id)
        $SkipCount += 1
        continue
    }
    $ok = & $G1Steps[$id]
    if ($ok) {
        Write-Host ("[PASS] {0}" -f $id)
        $PassCount += 1
    } else {
        Write-Host ("[FAIL] {0}" -f $id)
        $FailList += $id
    }
}

Write-Host "================================================================"
Write-Host ("  RESULT: PASS={0} FAIL={1} SKIP={2}" -f $PassCount, $FailList.Count, $SkipCount)
if ($FailList.Count -gt 0) {
    Write-Host ("  FAILED: {0}" -f ($FailList -join ", "))
}
if ($SkipCount -gt 0) {
    Write-Host "  SKIP entries need env-blocking evidence per README discipline"
}
Write-Host "================================================================"
if ($FailList.Count -gt 0 -or $SkipCount -gt 0) { exit 1 }
exit 0
