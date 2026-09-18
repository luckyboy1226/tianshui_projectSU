param(
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $projectRoot 'runtime'
$nginxVersion = '1.31.6'
$geoserverVersion = '3.0.1'
$nginxHome = Join-Path $runtimeRoot "nginx-$nginxVersion"
$geoserverHome = Join-Path $runtimeRoot "geoserver-$geoserverVersion"
$installerGeoServerHome = Join-Path $runtimeRoot 'GeoServer'
$nginxArchive = Join-Path $runtimeRoot "nginx-$nginxVersion.zip"
$geoserverArchive = Join-Path $runtimeRoot "geoserver-$geoserverVersion-bin.zip"

function Get-Archive([string]$url, [string]$target) {
    if ($Force -or -not (Test-Path -LiteralPath $target)) {
        Write-Host "Downloading $url" -ForegroundColor Cyan
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $target
    }
}

function Test-ZipArchive([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) {
        return $false
    }
    try {
        $archive = [System.IO.Compression.ZipFile]::OpenRead($path)
        $archive.Dispose()
        return $true
    }
    catch {
        return $false
    }
}

New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null

if ($Force -or -not (Test-Path -LiteralPath (Join-Path $nginxHome 'nginx.exe'))) {
    Get-Archive "https://nginx.org/download/nginx-$nginxVersion.zip" $nginxArchive
    Expand-Archive -LiteralPath $nginxArchive -DestinationPath $runtimeRoot -Force
}

if (Test-Path -LiteralPath (Join-Path $installerGeoServerHome 'bin\startup.bat')) {
    $geoserverHome = $installerGeoServerHome
}

if ($Force -or -not (Test-Path -LiteralPath (Join-Path $geoserverHome 'bin\startup.bat'))) {
    if ($Force -or -not (Test-ZipArchive $geoserverArchive)) {
        Write-Host "Downloading GeoServer $geoserverVersion" -ForegroundColor Cyan
        & curl.exe --fail --location --retry 3 --output $geoserverArchive "https://downloads.sourceforge.net/project/geoserver/GeoServer/$geoserverVersion/geoserver-$geoserverVersion-bin.zip"
        if ($LASTEXITCODE -ne 0) {
            throw "GeoServer download failed. Check network access to SourceForge and retry this script."
        }
    }
    Expand-Archive -LiteralPath $geoserverArchive -DestinationPath $runtimeRoot -Force
}

if (-not (Test-Path -LiteralPath (Join-Path $nginxHome 'nginx.exe'))) {
    throw "Nginx installation failed: $nginxHome"
}
if (-not (Test-Path -LiteralPath (Join-Path $geoserverHome 'bin\startup.bat'))) {
    throw "GeoServer installation failed: $geoserverHome"
}

$nginxConfig = Join-Path $projectRoot 'deployment\nginx.conf'
Copy-Item -LiteralPath $nginxConfig -Destination (Join-Path $nginxHome 'conf\nginx.conf') -Force

Write-Host 'Runtime components installed.' -ForegroundColor Green
Write-Host "Nginx: $nginxHome" -ForegroundColor Green
Write-Host "GeoServer: $geoserverHome" -ForegroundColor Green
