<#
Registers the local Windows Redis runtime as the project-specific
TianshuiRedis service. Run from an Administrator PowerShell prompt.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$redisRuntime = Join-Path $projectRoot 'runtime\services\redis\Redis-8.10.1-Windows-x64-msys2-with-Service'
$redisServiceExe = Join-Path $redisRuntime 'RedisService.exe'
$redisConfig = Join-Path $redisRuntime 'redis.conf'
$redisDataDirectory = Join-Path $projectRoot 'runtime\services\redis\data'

if (-not (Test-Path -LiteralPath $redisServiceExe)) {
    throw "Redis runtime was not found: $redisServiceExe"
}
if (-not (Test-Path -LiteralPath $redisConfig)) {
    throw "Redis configuration was not found: $redisConfig"
}

New-Item -ItemType Directory -Path $redisDataDirectory -Force | Out-Null
$existing = Get-Service -Name 'TianshuiRedis' -ErrorAction SilentlyContinue
if ($null -eq $existing) {
    & $redisServiceExe install -c $redisConfig --dir $redisDataDirectory --port 6379 --service-name TianshuiRedis --start-mode auto
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to register TianshuiRedis service (exit code: $LASTEXITCODE)."
    }
}

Start-Service -Name 'TianshuiRedis'
(Get-Service -Name 'TianshuiRedis') | Select-Object Status, Name, StartType
