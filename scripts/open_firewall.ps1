<#
.SYNOPSIS
    放行入站端口，让局域网 / 外网可以访问本机网站。

.DESCRIPTION
    创建一条 Windows 防火墙入站规则，允许指定 TCP 端口。需要用管理员权限运行。
    局域网访问、以及路由器把公网端口映射到本机时，都需要这一步。

.NOTES
    本文件为「带 BOM 的 UTF-8」。

.EXAMPLE
    # 在“以管理员身份运行”的 PowerShell 中执行：
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\open_firewall.ps1 -Port 8000
.EXAMPLE
    # 查看/删除已创建的规则：
    Get-NetFirewallRule -DisplayName '多功能网站*' | Remove-NetFirewallRule
#>
[CmdletBinding()]
param(
    [int]$Port = 8000,
    [string]$RuleName = "",
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
if (-not $RuleName) { $RuleName = "多功能网站 TCP $Port" }

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw '需要管理员权限：请右键 PowerShell 选择“以管理员身份运行”，再执行本脚本。'
}

if ($Remove) {
    Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    Write-Host "已删除规则：$RuleName" -ForegroundColor Green
    return
}

$existing = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "规则已存在：$RuleName" -ForegroundColor Yellow
    return
}

New-NetFirewallRule `
    -DisplayName $RuleName `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort $Port `
    -Profile Any `
    -Description '多功能网站（博客 / 文件 / 聊天 / 画布）入站放行' | Out-Null

Write-Host "已放行入站 TCP $Port（规则名：$RuleName）" -ForegroundColor Green
Write-Host '如需撤销：' -NoNewline
Write-Host " powershell -ExecutionPolicy Bypass -File scripts\open_firewall.ps1 -Port $Port -Remove"
