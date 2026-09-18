$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$userProfile = [Environment]::GetFolderPath('UserProfile')
$condaPython = Join-Path $userProfile '.conda\envs\ts\python.exe'
$venvPython = Join-Path $scriptDir '.venv\Scripts\python.exe'
$overridePython = $env:TIANSHUI_PYTHON

if ($overridePython -and (Test-Path $overridePython)) {
  $pythonExe = $overridePython
} elseif (Test-Path $condaPython) {
  $pythonExe = $condaPython
} elseif (Test-Path $venvPython) {
  $pythonExe = $venvPython
} else {
  throw "未找到可用的后端 Python 解释器。请先确认 GIS 环境已安装，或设置环境变量 TIANSHUI_PYTHON 指向可用的 python.exe。推荐路径: $condaPython"
}

Set-Location $scriptDir
& $pythonExe manage.py runserver 127.0.0.1:8000
