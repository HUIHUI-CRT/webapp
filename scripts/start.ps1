<#
.SYNOPSIS
    一键启动多功能网站（博客 / 文件 / 聊天 / 画布）。

.DESCRIPTION
    1. 检查 .venv 虚拟环境，不存在则创建；
    2. 检查依赖是否齐全，缺失则按 requirements.txt 安装；
    3. 以 0.0.0.0 监听，使本机、局域网以及做了端口映射/内网穿透的外网都能访问；
    4. 打印全部访问地址，并（默认）打开浏览器。

.NOTES
    本文件必须以「带 BOM 的 UTF-8」保存，Windows PowerShell 5.1 才能正确读取中文。

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start.ps1
.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start.ps1 -Port 9000 -Reload
#>
[CmdletBinding()]
param(
    [string]$BindHost = "0.0.0.0",
    [int]$Port = 8000,
    [switch]$Reload,
    [switch]$NoBrowser,
    [switch]$SkipDeps
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# ------------------------------------------------------------ 0. 读取 .env
# 支持项目根目录的 .env（KEY=VALUE，# 开头为注释）。
# 已存在的同名环境变量优先，方便用系统环境变量临时覆盖。
$envFile = Join-Path $root '.env'
if (Test-Path $envFile) {
    $loaded = 0
    Get-Content $envFile -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith('#') -and $line.Contains('=')) {
            $key, $value = $line -split '=', 2
            $key = $key.Trim()
            $value = $value.Trim().Trim('"').Trim("'")
            if ($key -and -not [Environment]::GetEnvironmentVariable($key, 'Process')) {
                [Environment]::SetEnvironmentVariable($key, $value, 'Process')
                $loaded++
            }
        }
    }
    Write-Host "已加载 .env（$loaded 项）"
}

Write-Host "项目目录: $root" -ForegroundColor Cyan

# ------------------------------------------------------------ 1. 虚拟环境
$venvPython = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Host '未找到 .venv，正在创建虚拟环境...' -ForegroundColor Yellow
    python -m venv .venv
    if (-not (Test-Path $venvPython)) { throw '虚拟环境创建失败，请确认已安装 Python 3.10+。' }
}
Write-Host "解释器  : $venvPython"

# ------------------------------------------------------------ 2. 依赖检查
function Test-Deps {
    & $venvPython -c "import fastapi, uvicorn, multipart" 2>$null
    return ($LASTEXITCODE -eq 0)
}

if (-not $SkipDeps) {
    if (-not (Test-Deps)) {
        Write-Host '依赖不完整，正在安装 requirements.txt ...' -ForegroundColor Yellow
        # .tools\sitecustomize.py 修正 Python 3.14 在受限环境下 mkdtemp 权限过窄的问题，
        # 只作用于本次安装过程，不影响网站运行。
        $oldPythonPath = $env:PYTHONPATH
        $env:PYTHONPATH = (Join-Path $root '.tools')
        try {
            & $venvPython -m pip install --disable-pip-version-check -r (Join-Path $root 'requirements.txt')
            if ($LASTEXITCODE -ne 0) { throw '依赖安装失败。' }
        } finally {
            $env:PYTHONPATH = $oldPythonPath
        }
    } else {
        Write-Host '依赖    : 已就绪' -ForegroundColor Green
    }
}

# ------------------------------------------------------------ 3. 打印地址
function Get-LanAddresses {
    $list = @()
    try {
        $list = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
            Select-Object -ExpandProperty IPAddress
    } catch {
        try {
            $list = [System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) |
                Where-Object { $_.AddressFamily -eq 'InterNetwork' } |
                ForEach-Object { $_.IPAddressToString }
        } catch { $list = @() }
    }
    return ($list | Select-Object -Unique)
}

Write-Host ''
Write-Host '访问地址：' -ForegroundColor Cyan
Write-Host "  本机      http://127.0.0.1:$Port/index.html"
foreach ($ip in Get-LanAddresses) {
    Write-Host "  局域网    http://${ip}:$Port/index.html"
}
Write-Host "  接口文档  http://127.0.0.1:$Port/docs"
Write-Host ''
Write-Host '外网访问：' -ForegroundColor Cyan
Write-Host "  方式一（路由器端口映射）：把公网端口映射到本机 IP 的 $Port 端口，"
Write-Host '          并先用管理员权限执行 scripts\open_firewall.ps1 放行入站。'
Write-Host '  方式二（内网穿透）：执行 scripts\public_tunnel.ps1 获取一个临时公网地址。'
Write-Host ''
Write-Host '按 Ctrl+C 停止服务。' -ForegroundColor DarkGray

if (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:$Port/index.html" | Out-Null
}

# ------------------------------------------------------------ 4. 启动服务
# 不显式指定 --ws：uvicorn 默认 auto，会自动选择可用的 WebSocket 实现，
# 同时避免固定实现带来的弃用告警。
$uvicornArgs = @(
    '-m', 'uvicorn', 'backend.app.main:app',
    '--host', $BindHost,
    '--port', "$Port"
)
if ($Reload) { $uvicornArgs += '--reload' }

$env:APP_HOST = $BindHost; $env:APP_PORT = $Port; & $venvPython @uvicornArgs
exit $LASTEXITCODE
