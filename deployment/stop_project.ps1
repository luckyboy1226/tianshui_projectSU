param(
    [switch]$NoPause,
    [switch]$SkipElevation
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $projectRoot 'runtime'
$nginxRoot = Get-ChildItem -LiteralPath $runtimeRoot -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like 'nginx-*' -and (Test-Path -LiteralPath (Join-Path $_.FullName 'nginx.exe')) } |
    Sort-Object Name -Descending |
    Select-Object -First 1 -ExpandProperty FullName
$nginxExe = if ($nginxRoot) { Join-Path $nginxRoot 'nginx.exe' } else { $null }

function Write-Ok([string]$message) {
    Write-Host "[ OK  ] $message" -ForegroundColor Green
}

function Write-Warn([string]$message) {
    Write-Host "[WARN ] $message" -ForegroundColor Yellow
}

function Stop-ProjectProcess([int]$processId, [string]$description) {
    try {
        Stop-Process -Id $processId -ErrorAction Stop
        Write-Ok "Stopped: $description"
    }
    catch {
        Write-Warn "Could not stop $description : $($_.Exception.Message)"
    }
}

function Get-ListeningProcessIds([int]$port) {
    # Get-NetTCPConnection can be unavailable to a non-elevated shell on some
    # Windows installations. netstat provides a reliable fallback for the
    # dedicated local project ports.
    $processIds = @()
    try {
        $connections = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop
        $processIds += @($connections | ForEach-Object { [int]$_.OwningProcess })
    }
    catch {
        $netstatLines = & "$env:SystemRoot\System32\netstat.exe" -ano -p tcp 2>$null
        $pattern = "^\s*TCP\s+\S+:$port\s+\S+\s+LISTENING\s+(\d+)\s*$"
        foreach ($line in $netstatLines) {
            if ($line -match $pattern) {
                $processIds += [int]$Matches[1]
            }
        }
    }
    return @($processIds | Select-Object -Unique)
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
$isAdministrator = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdministrator -and -not $SkipElevation) {
    $elevatedArguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    if ($NoPause) { $elevatedArguments += ' -NoPause' }
    Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $elevatedArguments
    exit 0
}

try {
    # Stop only the Celery workers that belong to this project.
    $celeryWorkers = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -eq 'python.exe' -and
            $_.CommandLine -match '(?i)celery' -and
            $_.CommandLine -match '(?i)tianshuipy' -and
            $_.CommandLine -match '(?i)worker'
        }
    if ($celeryWorkers) {
        foreach ($worker in $celeryWorkers) {
            Stop-ProjectProcess $worker.ProcessId 'Tianshui Celery worker'
        }
    }
    else {
        Write-Ok 'Tianshui Celery worker is not running'
    }

    # Stop only a Django development server that explicitly listens on this project's port.
    $backendListeners = Get-ListeningProcessIds 8000
    $backendStopped = $false
    foreach ($processId in $backendListeners) {
        $backendProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
        if ($backendProcess -and $backendProcess.Name -eq 'python.exe' -and $backendProcess.CommandLine -match 'manage\.py\s+runserver\s+127\.0\.0\.1:8000') {
            Stop-ProjectProcess $processId 'Tianshui Django backend'
            $backendStopped = $true
        }
        elseif ($null -eq $backendProcess) {
            # Port 8000 is reserved for this project; stopping it is safer than
            # leaving a stale backend that prevents the updated one from starting.
            Stop-ProjectProcess $processId 'Tianshui backend occupying port 8000'
            $backendStopped = $true
        }
    }
    if (-not $backendStopped) {
        Write-Ok 'Tianshui Django backend is not running'
    }

    # This controls only the Nginx installation dedicated to port 8081.
    if (Test-Path -LiteralPath $nginxExe) {
        $nginxResult = Start-Process -FilePath $nginxExe `
            -ArgumentList @('-s', 'quit', '-p', $nginxRoot, '-c', 'conf/nginx.conf') `
            -WorkingDirectory $nginxRoot `
            -Wait `
            -PassThru `
            -WindowStyle Hidden
        if ($nginxResult.ExitCode -eq 0) {
            Write-Ok 'Stopped Tianshui Nginx on port 8081'
        }
        else {
            Write-Ok 'Tianshui Nginx is not running'
        }
    }
    else {
        Write-Warn "Nginx was not found: $nginxExe"
    }

    Write-Host ''
    Write-Host 'Redis and GeoServer were left running because they may be used by other projects.' -ForegroundColor Cyan
}
catch {
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    if (-not $NoPause) {
        Read-Host 'Press Enter to close'
    }
    exit 1
}

if (-not $NoPause) {
    Read-Host 'Project shutdown finished. Press Enter to close this window'
}
