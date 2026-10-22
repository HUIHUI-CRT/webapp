<#
.SYNOPSIS
    通过内网穿透把本机网站发布到公网，得到一个手机可直接访问的网址。

.DESCRIPTION
    使用 Cloudflare 的免费快速隧道（cloudflared），把本地 8000 端口映射成
    形如 https://xxxx.trycloudflare.com 的公网地址：
      * 不需要公网 IP、不需要路由器端口映射、不需要开放防火墙入站；
      * 自动提供 HTTPS，WebSocket 自动走 wss；
      * 无需注册 Cloudflare 账号。

    前提：先运行 scripts\start.ps1 把网站在本地跑起来。

.NOTES
    本文件必须以「带 BOM 的 UTF-8」保存，Windows PowerShell 5.1 才能正确读取中文。

    注意：
      1. 这个地址是公开的，拿到链接的人都能上传/下载文件、发文章、进聊天。
         演示结束请关闭本窗口（隧道随即失效）。
      2. 关闭或重启后地址会变；需要固定地址请改用 Cloudflare 命名隧道。

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\public_tunnel.ps1
#>
[CmdletBinding()]
param(
    [int]$Port = 8000,
    [string]$Cloudflared = "",
    [switch]$NoDownload
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$localExe = Join-Path $root '.tools\cloudflared.exe'

function Find-Cloudflared([string]$explicit) {
    if ($explicit -and (Test-Path $explicit)) { return $explicit }
    if (Test-Path $localExe) { return $localExe }
    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($p in @(
        "$env:ProgramFiles\cloudflared\cloudflared.exe",
        "$env:LOCALAPPDATA\Microsoft\WinGet\Links\cloudflared.exe"
    )) { if (Test-Path $p) { return $p } }
    return ""
}

$exe = Find-Cloudflared $Cloudflared

# 没装就自动下载到 .tools\（约 55 MB，只做一次）
if (-not $exe) {
    if ($NoDownload) {
        Write-Host '未找到 cloudflared，且已指定 -NoDownload。' -ForegroundColor Yellow
        exit 1
    }
    Write-Host '未找到 cloudflared，正在下载到 .tools\cloudflared.exe ...' -ForegroundColor Yellow
    $python = Join-Path $root '.venv\Scripts\python.exe'
    if (-not (Test-Path $python)) { $python = 'python' }
    New-Item -ItemType Directory -Force -Path (Join-Path $root '.tools') | Out-Null
    & $python -c "import urllib.request; urllib.request.urlretrieve('https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe', r'$localExe')"
    if (-not (Test-Path $localExe)) { throw 'cloudflared 下载失败。' }
    $exe = $localExe
}

Write-Host "cloudflared: $exe"

# 先确认本地服务在跑
$alive = $false
try {
    $resp = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 5
    $alive = $resp.StatusCode -eq 200
} catch { $alive = $false }

if (-not $alive) {
    Write-Warning "本地 http://127.0.0.1:$Port 尚未响应，请先在另一个窗口运行 scripts\start.ps1。"
}

Write-Host ''
Write-Host "正在为 http://127.0.0.1:$Port 建立公网隧道..." -ForegroundColor Cyan
Write-Host '稍等几秒，下面会打印一个 https://xxxx.trycloudflare.com 地址，'
Write-Host '用手机（移动网络或 Wi-Fi 均可）打开它即可访问网站。'
Write-Host ''
Write-Host '提醒：该地址对所有人公开，演示完请关闭本窗口。' -ForegroundColor Yellow
Write-Host ''

& $exe tunnel --url "http://127.0.0.1:$Port" --no-autoupdate
exit $LASTEXITCODE
