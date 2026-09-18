$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $root 'backend'
$frontendDir = Join-Path $root 'frontend'
$backendScript = Join-Path $backendDir 'start_dev.ps1'
$frontendScript = Join-Path $frontendDir 'start_dev.ps1'
$userProfile = [Environment]::GetFolderPath('UserProfile')
$backendCondaPython = Join-Path $userProfile '.conda\envs\ts\python.exe'

if (-not (Test-Path $backendScript)) {
    throw "找不到后端启动脚本: $backendScript"
}

if (-not (Test-Path $frontendScript)) {
    throw "找不到前端启动脚本: $frontendScript"
}

if (-not (Test-Path $backendCondaPython)) {
    Write-Warning "未找到推荐的后端 GIS 环境: $backendCondaPython。可改用 backend\\.venv 或设置环境变量 TIANSHUI_PYTHON。"
}

$frontendPackage = Join-Path $frontendDir 'package.json'
if (-not (Test-Path $frontendPackage)) {
    throw "找不到前端 package.json: $frontendPackage"
}

$frontendNodeModules = Join-Path $frontendDir 'node_modules'
if (-not (Test-Path $frontendNodeModules)) {
    Write-Warning "前端依赖目录未找到: $frontendNodeModules。请先运行 frontend\npm install。"
}

function Test-PortAvailable {
    param(
        [int]$Port
    )

    try {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
        $listener.Start()
        $listener.Stop()
        return $true
    } catch {
        return $false
    }
}

$portChecks = @(
    @{ Port = 8000; Label = '后端'; Address = '127.0.0.1:8000' },
    @{ Port = 3000; Label = '前端'; Address = 'localhost:3000' }
)

$occupiedPorts = @()
foreach ($item in $portChecks) {
    if (-not (Test-PortAvailable -Port $item.Port)) {
        $occupiedPorts += $item
    }
}

if ($occupiedPorts.Count -gt 0) {
    Write-Warning '检测到目标端口已被占用，请先关闭对应程序后再启动：'
    foreach ($item in $occupiedPorts) {
        Write-Warning ("- {0}端口 {1}" -f $item.Label, $item.Address)
    }
    throw "端口占用阻止启动。"
}

Write-Host '正在启动后端...' -ForegroundColor Cyan
Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-NoExit', '-Command', "Set-Location '$backendDir'; & '$backendScript'" -WorkingDirectory $backendDir

Write-Host '正在启动前端...' -ForegroundColor Cyan
Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-NoExit', '-Command', "Set-Location '$frontendDir'; & '$frontendScript'" -WorkingDirectory $frontendDir

Write-Host ''
Write-Host '后端和前端已分别在新 PowerShell 窗口中启动。' -ForegroundColor Green
Write-Host '后端地址: http://127.0.0.1:8000/' -ForegroundColor Green
Write-Host '前端地址: http://localhost:3000/' -ForegroundColor Green
