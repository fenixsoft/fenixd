# =============================================================================
# run_integration.ps1 — Windows 集成测试驱动（W11 dockur 过机通道）
# =============================================================================
# 在真实 Windows Guest 内执行（RDP 进入后；代码经 /shared 映射的 Z: 盘）。
# 依次：依赖自检 → 平台面 pytest 子集 → G1 清单逐项驱动 → 汇总退出码。
# 任一环节失败退出码非零；SKIP 必须在输出留环境阻塞证据。
#
# 用法：
#   cd Z:\fenixd\tests\integration\windows
#   powershell -ExecutionPolicy Bypass -File run_integration.ps1
# =============================================================================

$ErrorActionPreference = "Continue"

# 框架根 = 本脚本所在目录向上三级（tests/integration/windows → 框架根）
$FrameworkRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$ChecklistPath = Join-Path $PSScriptRoot "g1_full_parity_checklist.md"

Write-Host "================================================================"
Write-Host "  fenixd Windows 集成测试"
Write-Host "  框架根: ${FrameworkRoot}"
Write-Host "================================================================"

# ── 1. 依赖自检 ───────────────────────────────────────────────────
$Py = $null
foreach ($candidate in @("py", "python")) {
    try { $null = & $candidate --version 2>$null } catch { }
    if ($LASTEXITCODE -eq 0) { $Py = $candidate; break }
}
if (-not $Py) {
    Write-Host "[FAIL] 未找到 python——先在框架根跑 install.ps1 装依赖"
    exit 1
}
if ($Py -eq "py") { $Py = @("py", "-3") } else { $Py = @("python") }

& $Py[0] $Py[1..($Py.Count - 1)] -c "import psutil, win32api" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] psutil/pywin32 未就绪——先在框架根跑 install.ps1"
    exit 1
}
Write-Host "[OK] 依赖自检通过"

# ── 2. 平台面 pytest 子集（真实 win32 API 面）──────────────────────
Write-Host "-- 平台面 pytest 子集 --"
Push-Location $FrameworkRoot
& $Py[0] $Py[1..($Py.Count - 1)] -m pytest tests/test_platform_pal.py tests/test_platform_guard.py -q
$PytestRc = $LASTEXITCODE
Pop-Location
if ($PytestRc -ne 0) {
    Write-Host "[FAIL] 平台面 pytest 未全绿（exit=$PytestRc）"
    exit $PytestRc
}
Write-Host "[OK] 平台面 pytest 全绿"

# ── 3. G1 清单逐项驱动 ────────────────────────────────────────────
# 清单条目 = G1-NN 编号；驱动器按编号调用本文件下方的步骤实现
# （G1 步骤注册表），清单 md 是权威定义（新增条目须同步注册实现）。
$Results = @{}

# G1 步骤注册表：编号 → 幂等驱动块。条目实现遵循「最小可观测」原则——
# 每条只验证判据本身，产物落 $env:TEMP\fenix-g1\ 供取证。
$G1Steps = @{
    "G1-01" = {
        & (Join-Path $FrameworkRoot "install.ps1") | Out-Null
        return ($LASTEXITCODE -eq 0)
    }
    "G1-02" = {
        $work = Join-Path $env:TEMP "fenix-g1\init-demo"
        New-Item -ItemType Directory -Force -Path $work | Out-Null
        Push-Location $work
        & (Join-Path $FrameworkRoot "fenix-init") . --name win-demo --type web 2>&1 | Out-Null
        $rc = $LASTEXITCODE
        Pop-Location
        return (($rc -eq 0) -and (Test-Path (Join-Path $work ".fenix\config.yaml")))
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
        Write-Host ("[SKIP] {0}（无驱动实现——环境未就绪，见 README 止损纪律）" -f $id)
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
Write-Host ("  结果: PASS={0} FAIL={1} SKIP={2}" -f $PassCount, $FailList.Count, $SkipCount)
if ($FailList.Count -gt 0) {
    Write-Host ("  失败条目: {0}" -f ($FailList -join ", "))
}
if ($SkipCount -gt 0) {
    Write-Host "  SKIP 条目须在过机报告附环境阻塞证据并登记 findings"
}
Write-Host "================================================================"
if ($FailList.Count -gt 0 -or $SkipCount -gt 0) { exit 1 }
exit 0
