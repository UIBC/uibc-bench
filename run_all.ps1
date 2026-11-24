<# 一键跑：按场景组顺序执行，产物落 runs\<时间戳>\，跑完自动与基线比对并生成可视化看板。
   用法：
     .\run_all.ps1                      # 全部组
     .\run_all.ps1 -Only s02b,s03       # 指定组
     .\run_all.ps1 -UpdateBaseline      # 用本次结果刷新基线（确认状态确实变好了才用）
#>
[CmdletBinding()]
param(
  [string]$Only = '',
  [switch]$UpdateBaseline,
  [int]$TimeoutSec = 900
)
$ErrorActionPreference = 'Continue'
$Kit = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Kit

$ts = Get-Date -Format 'yyyyMMdd_HHmmss'
$runDir = Join-Path $Kit "runs\$ts"
New-Item -ItemType Directory -Force -Path $runDir | Out-Null
$log = Join-Path $runDir 'run.log'

$py = Join-Path $Kit '.venv\Scripts\python.exe'
if(-not (Test-Path $py)){ $py = 'python' }
Write-Host "[run] python = $py"
Write-Host "[run] 输出目录 = $runDir"

$groups = Get-ChildItem (Join-Path $Kit 'harness') -Filter 's*.py' | Where-Object { $_.Name -match '^s\d{2}' } | Sort-Object Name
if($Only){
  $want = $Only.Split(',') | ForEach-Object { $_.Trim().ToLower() }
  $groups = $groups | Where-Object { $n = $_.BaseName.ToLower(); $want | Where-Object { $n -like "*$_*" } }
}
if(-not $groups){ Write-Host '[run] 没有匹配的场景组'; exit 1 }

"=== run $ts ===" | Out-File -LiteralPath $log -Encoding utf8
$fail = 0
foreach($g in $groups){
  $out = Join-Path $runDir ($g.BaseName + '_results.json')
  Write-Host "`n[run] ▶ $($g.Name)"
  $sw = [Diagnostics.Stopwatch]::StartNew()
  $txt = & $py $g.FullName $out 2>&1 | Out-String
  $sw.Stop()
  $txt | Out-File -LiteralPath $log -Append -Encoding utf8
  Write-Host $txt.Trim()
  Write-Host ("[run] ◀ {0} 用时 {1:N0}s" -f $g.BaseName, $sw.Elapsed.TotalSeconds)
  if(-not (Test-Path $out)){ $fail++ }
}

# 汇总与比对
$cmp = Join-Path $Kit 'compare_baseline.py'
if(Test-Path $cmp){
  & $py $cmp $runDir --baseline (Join-Path $Kit 'baseline.json') $(if($UpdateBaseline){'--update'}) 2>&1 | Out-String | Write-Host
}
Write-Host "`n[run] 完成：$runDir"
Get-ChildItem $runDir | Select-Object Name, Length | Format-Table -AutoSize
