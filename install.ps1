# =============================================================================
# fenixd 安装程序（Windows）— install.ps1（W10 安装链）
# =============================================================================
# Linux 侧对应物：install.sh。将 fenixd 框架安装到本机：
#   1. 依赖检查与安装（Python 3.10+ / git / Claude Code CLI + pip 依赖清单
#      requirements-win32.txt：psutil / pywin32 必选，PyYAML / httpx /
#      jsonschema 基线）
#   2. Claude Code skills 链接到 ~/.claude/skills/（symlink -> junction ->
#      copy 三级降级；copy 形态升级需重跑本脚本）
#   3. fenix-init 命令基线：写 .cmd shim 到 %LOCALAPPDATA%\Fenixd\bin 并把
#      该目录加入用户 PATH（win32 版 PATH 基线）
#   4. 生成用户级默认配置 ~\.fenix\config.yaml（幂等：已存在则跳过不覆盖）
#
# 用法：  powershell -ExecutionPolicy Bypass -File install.ps1
# 可重复执行（幂等）：已就绪项跳过，copy 降级形态每次重跑刷新。
# =============================================================================

$ErrorActionPreference = "Stop"

# 框架根目录 = 本脚本所在目录
$FenixdHome = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "================================================================"
Write-Host "  fenixd 安装程序 (Windows)"
Write-Host "  框架目录: ${FenixdHome}"
Write-Host "================================================================"

$Script:Fail = 0

# ── Python 解释器定位（py launcher 优先，回落 python）────────────────
$Py = $null
foreach ($candidate in @("py", "python")) {
    try {
        $null = & $candidate --version 2>$null
        if ($LASTEXITCODE -eq 0) { $Py = $candidate; break }
    } catch { }
}
if (-not $Py) {
    Write-Host "  [FAIL] 未找到 python（请安装 Python 3.10+ 并加入 PATH）"
    exit 1
}
if ($Py -eq "py") { $Py = @("py", "-3") } else { $Py = @("python") }

# 把 Python 主目录与 Scripts 目录前置进本进程 PATH：
# pip 安装 console-script 后的 "not on PATH" WARNING 在无控制台/重定向环境会被
# PS 5.1 升级为终止性 NativeCommandError（EAP=Stop）——从源头消除该警告，
# 且本进程后续可直接调用新装的可执行入口。
try {
    $pyDir = Split-Path -Parent (Invoke-Python -c "import sys; print(sys.executable)" | Select-Object -First 1)
    if ($pyDir) {
        $env:PATH = "$pyDir;$pyDir\Scripts;" + $env:PATH
    }
} catch { }

function Invoke-Python {
    # 以定位到的解释器执行（兼容 py -3 与 python 两种形态）。
    # 只透传 python 的 stdout 作为函数输出；退出码由 $LASTEXITCODE 自然携带。
    # （不得 `return $LASTEXITCODE`——那会把退出码混进输出流，污染调用方的
    #   stdout 捕获：$ver 会拿到 @("3.11", 0)，`$ver.Trim()` 即 Int32 崩溃。）
    & $Py[0] $Py[1..($Py.Count - 1)] @args
}

# ── 1. 依赖检查与安装 ─────────────────────────────────────────────
Write-Host "-- 依赖检查 --"

# Python 3.10+
$ver = Invoke-Python -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ($LASTEXITCODE -eq 0 -and $ver) {
    Invoke-Python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] python ($($ver.Trim()))"
    } else {
        Write-Host "  [FAIL] python 3.10+ (current: $($ver.Trim()))"
        $Script:Fail = 1
    }
} else {
    Write-Host "  [FAIL] python 不可用"
    $Script:Fail = 1
}

foreach ($tool in @("git", "claude")) {
    try {
        $null = & $tool --version 2>$null
    } catch { }
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] $tool"
    } else {
        Write-Host "  [FAIL] missing: $tool"
        $Script:Fail = 1
    }
}

# pip 依赖：逐项探测、缺失即装（幂等；对应 install.sh 的同构检查安装面）。
# 探测用 importlib.util.find_spec（不 import、零 stderr）——EAP=Stop 下原生
# stderr 会变 NativeCommandError 终止脚本；且 pip 包名 ≠ import 模块名
# （pywin32→win32api、PyYAML→yaml），直接 import 探测必假阴性。
# 必选两项失败置 fail；jsonschema 可选（缺失仅 json_schema 断言在验收期打回）。
$PipDeps = @(
    @{ Name = "psutil";     Mod = "psutil";     Req = "psutil>=5.9";      Optional = $false },
    @{ Name = "pywin32";    Mod = "win32api";   Req = "pywin32>=306";     Optional = $false },
    @{ Name = "PyYAML";     Mod = "yaml";       Req = "PyYAML>=6.0";      Optional = $false },
    @{ Name = "httpx";      Mod = "httpx";      Req = "httpx>=0.24";      Optional = $false },
    @{ Name = "jsonschema"; Mod = "jsonschema"; Req = "jsonschema>=4.17"; Optional = $true }
)
foreach ($dep in $PipDeps) {
    $mod = if ($dep.Mod) { $dep.Mod } else { $dep.Name }
    Invoke-Python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$mod') else 1)" 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] $($dep.Name)"
    } else {
        Write-Host "  [..] $($dep.Name) 未安装，正在 pip install..."
        # --no-warn-script-location：配合 PATH 前置双保险，杜绝脚本位置 WARNING
        # （stderr→ErrorRecord 在 EAP=Stop 下会终止脚本）；局部 EAP=Continue 兜底，
        # pip 的非零退出由 $LASTEXITCODE 判定，失败仍走 WARN/FAIL 分支。
        $eapBak = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        try {
            Invoke-Python -m pip install $dep.Req -q --disable-pip-version-check --no-warn-script-location 2>&1 | Out-Null
        } finally {
            $ErrorActionPreference = $eapBak
        }
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [OK] $($dep.Name) 安装完成"
        } elseif ($dep.Optional) {
            Write-Host "  [WARN] $($dep.Name) 安装失败（可稍后手动执行: pip install $($dep.Req)）"
        } else {
            Write-Host "  [FAIL] $($dep.Name) 安装失败，请手动执行: pip install $($dep.Req)"
            $Script:Fail = 1
        }
    }
}

if ($Script:Fail -ne 0) {
    Write-Host ""
    Write-Host "存在缺失依赖，请先安装后再运行本脚本。"
    exit 1
}

# ── 链接降级链（symlink -> junction -> copy）────────────────────────
# symlink 需管理员/开发者模式；junction 仅限目录但免提权（同卷）；copy 恒可
# 用（跨卷兜底，升级需重跑刷新）。返回 $true = 链接形态（免刷新），$false =
# copy 降级形态。
function Install-Link {
    param([string]$Source, [string]$Target)
    if (Test-Path $Target) {
        $item = Get-Item $Target -Force
        if ($item.LinkType -eq "SymbolicLink" -or $item.LinkType -eq "Junction") {
            # Target 在 PS5.1 是 string、PS7 是数组——contains 口径统一
            if (@($item.Target) -contains $Source) {
                Write-Host "  skip $(Split-Path -Leaf $Target)（已链接）"
                return $true
            }
            Write-Host "  [WARN] $(Split-Path -Leaf $Target) 已存在且指向他处，跳过（请手动处理）"
            return $true
        }
        Write-Host "  [WARN] $(Split-Path -Leaf $Target) 已存在且非链接形态，跳过（请手动处理）"
        return $true
    }
    # 1) symlink（目录与文件皆可；开发者模式/管理员下可用）
    try {
        New-Item -ItemType SymbolicLink -Path $Target -Value $Source -ErrorAction Stop | Out-Null
        Write-Host "  [OK] $(Split-Path -Leaf $Target) -> symlink"
        return $true
    } catch { }
    # 2) junction（仅目录）
    if (Test-Path $Source -PathType Container) {
        try {
            New-Item -ItemType Junction -Path $Target -Value $Source -ErrorAction Stop | Out-Null
            Write-Host "  [OK] $(Split-Path -Leaf $Target) -> junction"
            return $true
        } catch { }
    }
    # 3) copy（兜底；升级需重跑本脚本刷新）
    try {
        if (Test-Path $Source -PathType Container) {
            Copy-Item -Path $Source -Destination $Target -Recurse
        } else {
            Copy-Item -Path $Source -Destination $Target
        }
        Write-Host "  [OK] $(Split-Path -Leaf $Target) -> copy（降级形态：升级需重跑本脚本刷新）"
        return $false
    } catch {
        Write-Host "  [FAIL] $(Split-Path -Leaf $Target) 链接/复制失败: $_"
        $Script:Fail = 1
        return $true
    }
}

# ── 2. 安装 Claude Code skills ───────────────────────────────────
Write-Host "-- 安装 Claude Code skills --"
$SkillsDir = Join-Path $env:USERPROFILE ".claude\skills"
New-Item -ItemType Directory -Force -Path $SkillsDir | Out-Null
Get-ChildItem -Path (Join-Path $FenixdHome "skills") -Directory | ForEach-Object {
    $null = Install-Link -Source $_.FullName -Target (Join-Path $SkillsDir $_.Name)
}

# ── 3. fenix-init 命令基线（win32 PATH 版）────────────────────────
Write-Host "-- 安装 fenix-init 命令 --"
# shim 目录：用户域（免提权），python shim 转发框架根的 fenix-init 脚本
# （Windows 无 shebang 执行模型，经 .cmd 包装解释器转发）。
$ShimDir = Join-Path $env:LOCALAPPDATA "Fenixd\bin"
New-Item -ItemType Directory -Force -Path $ShimDir | Out-Null
$FenixInitSrc = Join-Path $FenixdHome "fenix-init"
$PyExe = (Invoke-Python -c "import sys; print(sys.executable)")
$PyExe = $PyExe.Trim()
@"
@echo off
"$PyExe" "$FenixInitSrc" %*
"@ | Set-Content -Path (Join-Path $ShimDir "fenix-init.cmd") -Encoding ASCII
Write-Host "  [OK] fenix-init.cmd -> ${ShimDir}"

# 用户 PATH 基线：ShimDir 不在用户 PATH 时追加（幂等；Machine 域不动）。
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (($null -eq $UserPath) -or -not (($UserPath -split ";") -contains $ShimDir)) {
    $NewPath = if ($UserPath) { "$UserPath;$ShimDir" } else { $ShimDir }
    [Environment]::SetEnvironmentVariable("Path", $NewPath, "User")
    Write-Host "  [OK] 已将 ${ShimDir} 加入用户 PATH（新开终端生效）"
} else {
    Write-Host "  skip PATH（${ShimDir} 已在用户 PATH）"
}

# ── 4. 生成用户级默认配置 ────────────────────────────────────────
# 与 install.sh 同构：全新安装后 Dashboard 设置页（用户级模式）不再提示
# 「配置文件不存在」；幂等——已存在则跳过（绝不覆盖，存量文件含 apikey）。
# 模板只含注释文档、不固化默认值：未写出的键由框架代码默认值兜底，升级
# 自动跟随新默认。失败降级为 WARN 不阻断安装（仅 UX 增强，非硬依赖）。
Write-Host "-- 生成用户级默认配置 --"
$UserConfigPath = Join-Path $env:USERPROFILE ".fenix\config.yaml"
$UserConfigTemplate = Join-Path $FenixdHome ".fenix\config.user.template.yaml"
if (Test-Path $UserConfigPath) {
    Write-Host "  skip ${UserConfigPath}（已存在，不覆盖既有配置）"
} elseif (-not (Test-Path $UserConfigTemplate)) {
    Write-Host "  [WARN] 模板缺失（${UserConfigTemplate}），跳过生成；"
    Write-Host "         可从 Dashboard 设置页（用户级模式）保存任意页签创建该文件"
} else {
    try {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $UserConfigPath) | Out-Null
        Copy-Item -Path $UserConfigTemplate -Destination $UserConfigPath
        Write-Host "  [OK] ${UserConfigPath}（用户级默认配置已生成）"
    } catch {
        Write-Host "  [WARN] 用户级默认配置生成失败（不影响安装，可稍后手工创建）: $_"
    }
}

Write-Host ""
Write-Host "================================================================"
Write-Host "  安装完成！"
Write-Host "================================================================"
Write-Host "  下一步："
Write-Host "    1. 进入你的项目目录，运行: fenix-init"
Write-Host "    2. 启动框架: /fenix-setup"
Write-Host "    3. 创建需求: /fenix-new `"你的想法`""
Write-Host ""
Write-Host "  Windows 承载：daemon 常驻经 NSSM 服务（nssm install），安装见"
Write-Host "  core/platform/win32.py D 组 docstring 与知识页 platform-abstraction。"
if (-not (Test-Path (Join-Path $FenixdHome "core\dashboard\static\dist\index.html"))) {
    Write-Host ""
    Write-Host "  [WARN] 未检出 dashboard 构建产物（dist 不入 git）："
    Write-Host "     cd ${FenixdHome}\core\dashboard\static && npm install && npm run build"
}
Write-Host "================================================================"
if ($Script:Fail -ne 0) { exit 1 }
