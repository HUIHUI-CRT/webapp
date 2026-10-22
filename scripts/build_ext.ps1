<#
.SYNOPSIS
    编译 C++ 性能扩展 fastcore（pybind11 + CMake）。

.DESCRIPTION
    优先使用 CMake 配置并构建；若 CMake 缺失或配置失败，则退化为直接调用
    g++ 编译。产物写入 backend/build/，后端启动时会自动在该目录搜索扩展，
    找不到时使用纯 Python 回退，因此本脚本失败不会影响网站运行。

.NOTES
    1. 本文件必须以「带 BOM 的 UTF-8」保存，否则 Windows PowerShell 5.1 会把
       中文按 ANSI 解码导致语法错误。修改后请确认首字节为 EF BB BF。
    2. MSYS2 的编译器需要把自身的 bin 目录加入 PATH，否则 cc1plus 找不到
       libgmp / libmpc 等依赖会静默失败。

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_ext.ps1
#>
[CmdletBinding()]
param(
    [string]$Python = "",
    [string]$BuildDir = "",
    [string]$Compiler = "",
    [string]$MakeProgram = "",
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $BuildDir) { $BuildDir = Join-Path $root 'backend\build' }
$src = Join-Path $root 'backend\cpp\fastcore.cpp'

# ---------------------------------------------------------------- 定位工具
function Find-Exe([string]$name, [string[]]$candidates) {
    foreach ($c in $candidates) { if ($c -and (Test-Path $c)) { return $c } }
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return ""
}

if (-not $Python) {
    $Python = Find-Exe 'python' @((Join-Path $root '.venv\Scripts\python.exe'))
}
if (-not $Python) { throw '找不到 Python 解释器，请用 -Python 指定路径。' }

$cmake = Find-Exe 'cmake' @((Join-Path $root '.venv\Scripts\cmake.exe'))

# MSYS2 常见安装位置与工具链子目录（ucrt64 的产物与官方 Python 兼容性最好）
$msysRoots = @('C:\msys64', (Join-Path $env:USERPROFILE 'msys64'), 'C:\msys32')
$compilerCandidates = @()
$makeCandidates = @()
foreach ($r in $msysRoots) {
    foreach ($envName in 'ucrt64', 'mingw64', 'clang64', 'mingw32') {
        $compilerCandidates += Join-Path $r "$envName\bin\g++.exe"
        $makeCandidates += Join-Path $r "$envName\bin\mingw32-make.exe"
    }
}
if (-not $Compiler) { $Compiler = Find-Exe 'g++' $compilerCandidates }
if (-not $MakeProgram) { $MakeProgram = Find-Exe 'mingw32-make' $makeCandidates }

# 关键：把编译器所在目录加入 PATH，cc1plus / as / ld 的依赖库才能被找到
foreach ($bin in @($Compiler, $MakeProgram, $cmake)) {
    if ($bin) {
        $binDir = Split-Path -Parent $bin
        if ($env:PATH -notlike "*$binDir*") { $env:PATH = "$binDir;$env:PATH" }
    }
}

Write-Host "Python : $Python"
Write-Host "CMake  : $(if ($cmake) { $cmake } else { '(未找到)' })"
Write-Host "C++    : $(if ($Compiler) { $Compiler } else { '(未找到)' })"
Write-Host "Make   : $(if ($MakeProgram) { $MakeProgram } else { '(未找到)' })"
Write-Host "产物   : $BuildDir"

New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null
$ext = & $Python -c "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX'))"
$target = Join-Path $BuildDir "fastcore$ext"

# ---------------------------------------------------------------- 方式一：CMake
$built = $false
if ($cmake -and -not $Force) {
    # 上次可能用别的生成器配置过，清掉缓存避免「generator 不匹配」
    foreach ($stale in 'CMakeCache.txt', 'CMakeFiles') {
        $p = Join-Path $BuildDir $stale
        if (Test-Path $p) { Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue }
    }
    $cmakeArgs = @('-S', (Join-Path $root 'backend\cpp'), '-B', $BuildDir,
                   '-DCMAKE_BUILD_TYPE=Release', "-DPython_EXECUTABLE=$Python")
    if ($Compiler) { $cmakeArgs += "-DCMAKE_CXX_COMPILER=$Compiler" }
    if ($MakeProgram) {
        $cmakeArgs += '-G', 'MinGW Makefiles', "-DCMAKE_MAKE_PROGRAM=$MakeProgram"
    }
    Write-Host "`n[1/2] CMake 配置..." -ForegroundColor Cyan
    & $cmake @cmakeArgs
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[2/2] CMake 构建..." -ForegroundColor Cyan
        & $cmake --build $BuildDir --config Release
        if ($LASTEXITCODE -eq 0) {
            $found = Get-ChildItem $BuildDir -Filter 'fastcore*' -File -ErrorAction SilentlyContinue
            if ($found) { $built = $true }
        }
    }
    if (-not $built) { Write-Warning 'CMake 构建未成功，改用直接 g++ 编译。' }
}

# ------------------------------------------------------------ 方式二：直接 g++
if (-not $built) {
    if (-not $Compiler) { throw '既没有可用的 CMake 构建，也没有找到 C++ 编译器。' }
    $pyInclude = & $Python -c "import sysconfig; print(sysconfig.get_paths()['include'])"
    $pbInclude = & $Python -c "import pybind11; print(pybind11.get_include())"
    $pyBase    = & $Python -c "import sysconfig; print(sysconfig.get_config_var('installed_base'))"
    $pyVer     = & $Python -c "import sysconfig; print('python' + sysconfig.get_config_var('py_version_nodot'))"
    $libs = Join-Path (Join-Path $pyBase 'libs') "$pyVer.lib"
    Write-Host "`n直接编译: $Compiler" -ForegroundColor Cyan
    $gccArgs = @('-O3', '-shared', '-std=c++17', '-DMS_WIN64',
                 '-static-libgcc', '-static-libstdc++',
                 "-I$pyInclude", "-I$pbInclude", $src, '-o', $target)
    if (Test-Path $libs) { $gccArgs += @("-L$(Split-Path -Parent $libs)", "-l$pyVer") }
    & $Compiler @gccArgs
    if ($LASTEXITCODE -ne 0) { throw 'C++ 编译失败。' }
}

# ---------------------------------------------------------------- 验证导入
Write-Host "`n验证导入..." -ForegroundColor Cyan
& $Python -c "import sys; sys.path.insert(0, r'$BuildDir'); import fastcore; print('fastcore', fastcore.__version__, '引擎', fastcore.engine()); print('sha256 自检', fastcore.sha256_file(r'$src')[:16])"
if ($LASTEXITCODE -ne 0) { throw '扩展已编译但无法导入，请检查 Python 与编译器架构是否一致（应同为 64 位）。' }

Write-Host "`n构建完成：$target" -ForegroundColor Green
