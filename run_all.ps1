<# Windows 便捷入口：转调 run.py（跨平台单一入口）。真正干活的逻辑只留 run.py 一份，两边不会再走岔。
   旧用法保持不变：
     .\run_all.ps1                      # 全部组
     .\run_all.ps1 -Only s02b,s03       # 指定组
     .\run_all.ps1 -UpdateBaseline      # 用本次结果刷新基线（确认状态确实变好了才用）
     .\run_all.ps1 -TimeoutSec 1800     # 每组超时；旧版本声明了却从未使用，现在真生效
#>
[CmdletBinding()]
param(
  [string]$Only = '',
  [switch]$UpdateBaseline,
  [int]$TimeoutSec = 900,
  [string]$Subject = '',
  [switch]$Quick
)
$ErrorActionPreference = 'Continue'
$Kit = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Kit

$py = Join-Path $Kit '.venv\Scripts\python.exe'
if(-not (Test-Path $py)){ $py = 'python' }
$argv = @('run.py')
if($Only){ $argv += @('--only', $Only) }
if($TimeoutSec){ $argv += @('--timeout', "$TimeoutSec") }
if($Subject){ $argv += @('--subject', $Subject) }
if($Quick){ $argv += '--quick' }
if($UpdateBaseline){ $argv += '--update-baseline' }
Write-Host "[run_all] -> & $py $($argv -join ' ')"
& $py @argv
exit $LASTEXITCODE
