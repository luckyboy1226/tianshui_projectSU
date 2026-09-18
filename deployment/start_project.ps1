param(
    [switch]$NoBrowser,
    [switch]$NoPause,
    [switch]$SkipElevation
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $projectRoot 'backend'
$frontendIndex = Join-Path $projectRoot 'frontend\dist\index.html'
$runtimeRoot = Join-Path $projectRoot 'runtime'
$pythonExe = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.conda\envs\ts\python.exe'
$nginxRoot = $null
$nginxExe = $null
$geoserverHome = $null
$geoserverStartup = $null
$nginxConfigSource = Join-Path $projectRoot 'deployment\nginx.conf'
$nginxConfigTarget = $null
$projectUrl = 'http://localhost:8081/'
$redisRuntime = Join-Path $runtimeRoot 'services\redis\Redis-8.10.1-Windows-x64-msys2-with-Service'
$redisServiceExe = Join-Path $redisRuntime 'RedisService.exe'
$redisConfig = Join-Path $redisRuntime 'redis.conf'
$redisDataDirectory = Join-Path $runtimeRoot 'services\redis\data'

function Write-Step([string]$message) {
    Write-Host "[START] $message" -ForegroundColor Cyan
}

function Write-Ok([string]$message) {
    Write-Host "[ OK  ] $message" -ForegroundColor Green
}

function Write-Warn([string]$message) {
    Write-Host "[WARN ] $message" -ForegroundColor Yellow
}

function Test-ListeningPort([int]$port) {
    $client = [Net.Sockets.TcpClient]::new()
    try {
        $connection = $client.BeginConnect('127.0.0.1', $port, $null, $null)
        if (-not $connection.AsyncWaitHandle.WaitOne(800)) {
            return $false
        }
        $client.EndConnect($connection)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Wait-ForUrl([string]$url, [int]$attempts = 20) {
    for ($attempt = 1; $attempt -le $attempts; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return $true
            }
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }
    return $false
}

function Start-ProjectService([string]$serviceName) {
    $service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
    if ($null -eq $service) {
        Write-Warn "Windows service not found: $serviceName"
        return
    }

    if ($service.Status -ne 'Running') {
        Write-Step "Starting Windows service: $serviceName"
        Start-Service -Name $serviceName
        $service.WaitForStatus('Running', [TimeSpan]::FromSeconds(20))
    }
    Write-Ok "Windows service is running: $serviceName"
}

function Start-LocalRedis {
    if (Test-ListeningPort 6379) {
        Write-Ok 'Redis is already listening on port 6379'
        return
    }

    $service = Get-Service -Name 'TianshuiRedis' -ErrorAction SilentlyContinue
    if ($null -ne $service) {
        Start-ProjectService 'TianshuiRedis'
    }
    elseif ((Test-Path -LiteralPath $redisServiceExe) -and (Test-Path -LiteralPath $redisConfig)) {
        # A non-administrator can still run the local development Redis process.
        # The dedicated service is preferred where its registration is available.
        New-Item -ItemType Directory -Path $redisDataDirectory -Force | Out-Null
        Write-Step 'Starting local Redis on port 6379'
        Start-Process -FilePath $redisServiceExe `
            -ArgumentList @('run', '-c', $redisConfig, '--dir', $redisDataDirectory, '--port', '6379', '--foreground') `
            -WorkingDirectory $redisRuntime `
            -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $runtimeRoot 'redis.out.log') `
            -RedirectStandardError (Join-Path $runtimeRoot 'redis.err.log')
        Start-Sleep -Seconds 2
    }
    else {
        throw "Redis runtime files are missing: $redisServiceExe"
    }

    if (-not (Test-ListeningPort 6379)) {
        throw "Redis did not become ready. Check: $runtimeRoot\redis.err.log"
    }
    Write-Ok 'Redis is ready on port 6379'
}

function Find-RuntimeDirectory([string]$prefix, [string]$requiredFile) {
    $directory = Get-ChildItem -LiteralPath $runtimeRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object {
            ($_.Name -like "$prefix*" -or ($prefix -eq 'geoserver-' -and $_.Name -eq 'GeoServer')) -and
            (Test-Path -LiteralPath (Join-Path $_.FullName $requiredFile))
        } |
        Sort-Object Name -Descending |
        Select-Object -First 1
    if ($null -eq $directory) {
        throw "未找到运行组件 $prefix*（需要文件: $requiredFile）。请先运行 deployment\\install_runtime.ps1。"
    }
    return $directory.FullName
}

# Redis and GeoServer are Windows services and may require administrator rights.
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
$isAdministrator = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdministrator -and -not $SkipElevation) {
    $elevatedArguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    if ($NoBrowser) { $elevatedArguments += ' -NoBrowser' }
    if ($NoPause) { $elevatedArguments += ' -NoPause' }
    Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $elevatedArguments
    exit 0
}

try {
    New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null

    $nginxRoot = Find-RuntimeDirectory 'nginx-' 'nginx.exe'
    $nginxExe = Join-Path $nginxRoot 'nginx.exe'
    $nginxConfigTarget = Join-Path $nginxRoot 'conf\nginx.conf'
    $geoserverHome = Find-RuntimeDirectory 'geoserver-' 'bin\startup.bat'
    $geoserverStartup = Join-Path $geoserverHome 'bin\startup.bat'

    if (-not (Test-Path -LiteralPath $pythonExe)) {
        throw "Python not found: $pythonExe"
    }
    if (-not (Test-Path -LiteralPath $frontendIndex)) {
        throw "Frontend build not found: $frontendIndex"
    }
    if (-not (Test-Path -LiteralPath $nginxExe)) {
        throw "Nginx not found: $nginxExe"
    }
    if (-not (Test-Path -LiteralPath $nginxConfigSource)) {
        throw "Nginx configuration not found: $nginxConfigSource"
    }

    # Keep the dedicated Nginx installation in sync with this project's
    # deployment settings before it is started.
    Copy-Item -LiteralPath $nginxConfigSource -Destination $nginxConfigTarget -Force

    # Load project service credentials saved for the current Windows user.
    foreach ($variableName in @(
        'TIANSHUI_CELERY_BROKER_URL',
        'TIANSHUI_CELERY_RESULT_BACKEND',
        'TIANSHUI_DB_NAME',
        'TIANSHUI_DB_USER',
        'TIANSHUI_DB_PASSWORD',
        'TIANSHUI_DB_HOST',
        'TIANSHUI_DB_PORT',
        'TIANSHUI_SECRET_KEY',
        'GEOSERVER_URL',
        'GEOSERVER_USERNAME',
        'GEOSERVER_PASSWORD'
    )) {
        $variableValue = [Environment]::GetEnvironmentVariable($variableName, 'User')
        if (-not [string]::IsNullOrWhiteSpace($variableValue)) {
            Set-Item -Path "Env:$variableName" -Value $variableValue
        }
    }

    Start-LocalRedis

    if (Test-ListeningPort 8080) {
        Write-Ok 'GeoServer is already listening on port 8080'
    }
    else {
        Write-Step 'Starting local GeoServer on port 8080'
        $javaHome = $env:JAVA_HOME
        if (-not $javaHome -or -not (Test-Path -LiteralPath (Join-Path $javaHome 'bin\java.exe'))) {
            $javaHome = 'D:\JDK17'
        }
        if (-not (Test-Path -LiteralPath (Join-Path $javaHome 'bin\java.exe'))) {
            throw 'GeoServer requires Java 17 or 21. Set JAVA_HOME to a valid JRE/JDK directory.'
        }
        $env:JAVA_HOME = $javaHome
        Start-Process -FilePath $geoserverStartup `
            -WorkingDirectory $geoserverHome `
            -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $runtimeRoot 'geoserver.out.log') `
            -RedirectStandardError (Join-Path $runtimeRoot 'geoserver.err.log')

        if (-not (Wait-ForUrl 'http://127.0.0.1:8080/geoserver/web/')) {
            throw "GeoServer did not become ready. Check: $runtimeRoot\geoserver.err.log"
        }
        Write-Ok 'GeoServer is ready'
    }

    Write-Step 'Ensuring GeoServer workspace exists'
    & $pythonExe manage.py shell -c "from environment.geoserver_config import GeoServerManager; assert GeoServerManager().create_workspace()"
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not create the GeoServer workspace.'
    }
    Write-Ok 'GeoServer workspace is ready'

    # 部署脚本启动了独立 Worker，因此强制 API 仅入队，避免请求线程同步跑 GIS 计算。
    $env:CELERY_BROKER_URL = $env:TIANSHUI_CELERY_BROKER_URL
    $env:CELERY_RESULT_BACKEND = $env:TIANSHUI_CELERY_RESULT_BACKEND
    $env:CELERY_TASK_ALWAYS_EAGER = 'false'
    $env:DJANGO_SETTINGS_MODULE = 'tianshuipy.settings_postgresql'
    $celeryConcurrency = if ($env:TIANSHUI_CELERY_CONCURRENCY) {
        [Math]::Max(2, [int]$env:TIANSHUI_CELERY_CONCURRENCY)
    } else {
        [Math]::Max(2, [Environment]::ProcessorCount * 2)
    }

    if (Test-ListeningPort 8000) {
        Write-Ok 'Django backend is already listening on port 8000'
    }
    else {
        Write-Step 'Starting Django backend on port 8000'
        Start-Process -FilePath $pythonExe `
            -ArgumentList @('manage.py', 'runserver', '127.0.0.1:8000', '--noreload') `
            -WorkingDirectory $backendRoot `
            -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $runtimeRoot 'django.out.log') `
            -RedirectStandardError (Join-Path $runtimeRoot 'django.err.log')
    }

    $celeryWorker = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -eq 'python.exe' -and
            $_.CommandLine -match '(?i)celery' -and
            $_.CommandLine -match '(?i)tianshuipy' -and
            $_.CommandLine -match '(?i)worker'
        } |
        Select-Object -First 1

    if ($null -ne $celeryWorker) {
        Write-Ok 'Celery worker is already running'
    }
    else {
        Write-Step 'Starting Celery worker'
        Start-Process -FilePath $pythonExe `
            -ArgumentList @('-m', 'celery', '-A', 'tianshuipy', 'worker', '-l', 'info', '--pool=threads', "--concurrency=$celeryConcurrency", '--queues=geo.high,geo.default,geo.low', '-Ofair') `
            -WorkingDirectory $backendRoot `
            -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $runtimeRoot 'celery.out.log') `
            -RedirectStandardError (Join-Path $runtimeRoot 'celery.err.log')
    }

    if (Test-ListeningPort 8081) {
        Write-Step 'Reloading Nginx configuration on port 8081'
        Start-Process -FilePath $nginxExe `
            -ArgumentList @('-s', 'reload', '-p', $nginxRoot, '-c', 'conf/nginx.conf') `
            -WorkingDirectory $nginxRoot `
            -Wait `
            -WindowStyle Hidden
        Write-Ok 'Nginx configuration reloaded'
    }
    else {
        Write-Step 'Starting Nginx on port 8081'
        Start-Process -FilePath $nginxExe -WorkingDirectory $nginxRoot -WindowStyle Hidden
    }

    Write-Step 'Waiting for the backend API'
    if (Wait-ForUrl 'http://127.0.0.1:8000/api/v1/environment/ecological-indices/') {
        Write-Ok 'Django API is ready'
    }
    else {
        Write-Warn "Django API did not become ready. Check: $runtimeRoot\django.err.log"
    }

    Write-Step 'Waiting for the Nginx website'
    if (Wait-ForUrl $projectUrl) {
        Write-Ok "Project is ready: $projectUrl"
        if (-not $NoBrowser) {
            Start-Process $projectUrl
        }
    }
    else {
        Write-Warn "Website did not become ready: $projectUrl"
    }
}
catch {
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    if (-not $NoPause) {
        Read-Host 'Press Enter to close'
    }
    exit 1
}

if (-not $NoPause) {
    Write-Host ''
    Read-Host 'Startup finished. Press Enter to close this window'
}
