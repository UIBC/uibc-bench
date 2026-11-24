<# 打成可分发包：同事/合作方拿到 zip 解压即可跑，不需要装任何第三方库（只用标准库）。
   被实测的仓库、虚拟环境、历史运行结果、证书不进包（体积与卫生考虑）。
#>
[CmdletBinding()]
param([string]$OutDir = '', [switch]$WithRepo)
$ErrorActionPreference = 'Stop'
$Kit = Split-Path -Parent $MyInvocation.MyCommand.Path
if(-not $OutDir){ $OutDir = Join-Path $Kit 'dist' }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$stamp = Get-Date -Format 'yyyyMMdd'
$ver = if(Test-Path (Join-Path $Kit 'VERSION')){ (Get-Content (Join-Path $Kit 'VERSION') -Raw).Trim() } else { '0.1' }
$name = "uibc-实测台-$ver-$stamp"
$stage = Join-Path ([IO.Path]::GetTempPath()) $name
Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $stage | Out-Null

$include = @('README.md','VERSION','bench.py','compare_baseline.py','results.schema.json','thresholds.json','setup.ps1','run_all.ps1','harness','cases','baseline.json','first_run.py','tools')
foreach($i in $include){
  $p = Join-Path $Kit $i
  if(-not (Test-Path $p)){ Write-Host "[pkg] 跳过（不存在）：$i"; continue }
  Copy-Item -Recurse -Force -LiteralPath $p -Destination $stage
}
if($WithRepo){
  Write-Host '[pkg] 连同被测仓库一起打包（较大）'
  Copy-Item -Recurse -Force -LiteralPath (Join-Path $Kit 'uibc-core-public') -Destination $stage
}
# 不带仓库时给出获取方式
@"
# 本包不含被测仓库。首次使用请执行：
#   .\setup.ps1                 # 自动 clone 到 uibc-core-public（已用 -c core.autocrlf=false）
# 然后： .\run_all.ps1
#
# 注意：在 Windows 上必须用 core.autocrlf=false 克隆，否则字节锚定的向量文件会被
# 换成 CRLF，导致 47 条单测失败（详见 README「已知坑」）。
"@ | Set-Content -LiteralPath (Join-Path $stage 'FIRST-RUN.txt') -Encoding utf8

$zip = Join-Path $OutDir ($name + '.zip')
Remove-Item -Force $zip -ErrorAction SilentlyContinue
# 用 -Path $stage（而不是 $stage\*）让 zip 内保留顶层目录，解压后不会散落一地
Compress-Archive -Path $stage -DestinationPath $zip -CompressionLevel Optimal
$sha = (Get-FileHash -Algorithm SHA256 $zip).Hash.ToLower()
# 再出一个 tar.gz：Linux/macOS 用 tar 解压能正确还原中文文件名
# （Windows 的 Compress-Archive 不带 UTF-8 标志，老版 unzip 会显示乱码目录名）
$tgz = Join-Path $OutDir ($name + '.tar.gz')
Remove-Item -Force $tgz -ErrorAction SilentlyContinue
& tar.exe -czf $tgz -C ([IO.Path]::GetTempPath()) $name 2>&1 | Out-Null
$size = (Get-Item $zip).Length
$shaTgz = (Get-FileHash -Algorithm SHA256 $tgz).Hash.ToLower()
Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue

"$sha  $([IO.Path]::GetFileName($zip))" | Set-Content -LiteralPath ($zip + '.sha256') -Encoding utf8
"$shaTgz  $([IO.Path]::GetFileName($tgz))" | Set-Content -LiteralPath ($tgz + '.sha256') -Encoding utf8
Write-Host ("[pkg] 产出 {0}  {1:N0} KB" -f $zip, ($size/1KB))
Write-Host ("[pkg] 产出 {0}  {1:N0} KB（Linux 优先用这个）" -f $tgz, ((Get-Item $tgz).Length/1KB))
Write-Host "[pkg] sha256 zip=$sha tgz=$shaTgz"
