# 一条命令跑官方 W3C DID Resolution Test Suite（Windows / PowerShell）
#
#   .\tools\run_official_suite.ps1                # 默认端口 9443，套件克隆到 %TEMP%\wst
#   .\tools\run_official_suite.ps1 -Port 9455
#
# 与 tools/run_official_suite.sh 做的事情完全一样，只是 Windows 版。
# 不改 W3C 仓库、不提 PR、不隐藏失败；日志落 runs\<时间戳>_official\。
[CmdletBinding()]
param([int]$Port = 9443,
      [string]$Pin = '4b5a62e3019fa4f2e90c9b8c0e59d249b67eac10')
$ErrorActionPreference = 'Stop'
$Kit = Split-Path -Parent $PSScriptRoot
$suite = Join-Path $env:TEMP 'wst'
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$out = Join-Path $Kit "runs\${stamp}_official"
New-Item -ItemType Directory -Force -Path $out | Out-Null

Write-Host '[1/6] 克隆官方套件（已存在则跳过）'
if (-not (Test-Path $suite)) {
  & git clone --depth 1 https://github.com/w3c/did-resolution-test-suite.git $suite
  if ($LASTEXITCODE -ne 0) { throw '克隆失败：本机 github 时段性阻断，可换机或用 tar 包' }
}
$commit = (& git -C $suite rev-parse HEAD).Trim()
# 版本钉住：套件会更新，不钉住的话"同一条命令"下周可能跑出不同结果
if ($Pin -and $commit -ne $Pin) {
  Write-Host "      HEAD=$commit 与钉住版本不同，改为检出 $Pin"
  & git -C $suite fetch --depth 1 origin $Pin *> (Join-Path $out 'git_fetch.log')
  if ($LASTEXITCODE -ne 0) { throw "无法取到钉住版本 $Pin（可能已被上游改写），见 $out\git_fetch.log" }
  & git -C $suite checkout -q FETCH_HEAD
  if ($LASTEXITCODE -ne 0) { throw "检出 $Pin 失败" }
  $commit = (& git -C $suite rev-parse HEAD).Trim()
}
Write-Host "      commit=$commit（钉住=$Pin）"

Write-Host '[2/6] 安装套件依赖'
Push-Location $suite
& npm i --no-audit --no-fund *> (Join-Path $out 'npm_i.log')
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "依赖安装失败，见 $out\npm_i.log" }
Pop-Location

Write-Host '[3/6] 起本地 HTTPS endpoint'
# 注意：Windows 上 python 常是 App 别名/shim，Get-Command 的 .Source 可能为空，必须用 .Path 并做兜底
$pyCmd = Get-Command python -CommandType Application -ErrorAction SilentlyContinue |
         Select-Object -First 1
if (-not $pyCmd) { throw '找不到 python：请先安装 Python 3.9+ 并确保 python 在 PATH 中' }
$py = $pyCmd.Path
if (-not $py) { throw 'python 路径解析为空（可能是 App 别名），请用完整路径设置 python' }
Write-Host "      python=$py"
# 证书自举：包里不带证书（自签证书是一次性的），首次运行就地生成。
# 教训（第 11 个缺陷）：0.4.9 的 tgz 不含 _pki，新环境直接跑会 shim 崩、冒烟 000，
# 而中止提示只让人看 shim.log，看不出"缺证书"这一层。
$pkiDir = Join-Path $Kit '_pki'
$cert = Join-Path $pkiDir 'cert.pem'
$keyFile = Join-Path $pkiDir 'key.pem'
if ((-not (Test-Path $cert)) -or (-not (Test-Path $keyFile))) {
  Write-Host '      首次运行：生成自签证书到 _pki/'
  New-Item -ItemType Directory -Force -Path $pkiDir | Out-Null
  $ossl = (Get-Command openssl -CommandType Application -ErrorAction SilentlyContinue |
           Select-Object -First 1)
  # 教训（第 17 个缺陷）：Windows 上常常没有 openssl（Git for Windows 也未必加进 PATH），
  # 之前这里直接 throw，外人在 Windows 全新目录跑不起来。改为 .NET 自签兜底（不需要管理员）。
  if ($ossl) {
    & $ossl.Source req -x509 -newkey rsa:2048 -nodes `
      -keyout $keyFile -out $cert -days 3650 -subj '/CN=localhost' `
      *> (Join-Path $out 'openssl.log')
    if ($LASTEXITCODE -ne 0) { throw "生成自签证书失败，见 $out\openssl.log" }
  } else {
    Write-Host '      本机无 openssl，改用 Windows 原生 .NET 自签（tools\make_cert.ps1）'
    & (Join-Path $Kit 'tools\make_cert.ps1') -OutDir $pkiDir *> (Join-Path $out 'make_cert.log')
    if ((-not (Test-Path $cert)) -or (-not (Test-Path $keyFile))) {
      throw "生成自签证书失败（无 openssl，.NET 兜底也没成功），见 $out\make_cert.log"
    }
  }
}

# UIBC_SHIM 可指向一个变体载体（变异测试用：故意把载体改坏，看套件是否判红）；默认就是正式 shim
$shimPath = if ($env:UIBC_SHIM) { $env:UIBC_SHIM } else { Join-Path $Kit 'tools\resolver_https_shim.py' }
Write-Host "      shim=$shimPath"
$shimProc = Start-Process -FilePath $py -ArgumentList @(
  $shimPath, '--port', "$Port"
) -PassThru -RedirectStandardOutput (Join-Path $out 'shim.log') `
  -RedirectStandardError (Join-Path $out 'shim.err') -NoNewWindow
Start-Sleep -Seconds 3
try {
  $code = & curl.exe -sk --max-time 10 "https://127.0.0.1:$Port/1.0/identifiers/not-a-did" `
    -H 'Accept: application/did-resolution' -o (Join-Path $out 'shim_smoke.json') -w '%{http_code}'
  Write-Host "      冒烟状态码=$code（应为 400）"
} catch { Write-Host "      冒烟失败：$_" }
if ("$code" -ne '400') {
  # 冒烟不过就中止：曾因仓不完整导致 000 却继续跑，产出一份 2/13 的"基线"，差点被当成真结果
  Write-Host "      [中止] 冒烟非 400（实际 $code），endpoint 不可用；见 shim.log / shim.err。不产出任何结果。"
  if ($shimProc -and -not $shimProc.HasExited) { $shimProc.Kill() }
  exit 2
}

Write-Host '[4/6] 登记我方 resolver（只写套件副本）'
$rj = [ordered]@{
  name = 'UIBC (self-test)'
  implementation = 'uibc-core resolve() behind HTTPS binding shim'
  endpoint = "https://127.0.0.1:$Port/1.0/identifiers"
  supportedDidMethods = @('did:key')
}
$rj | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $suite 'resolvers\UIBC-selftest.json') -Encoding utf8

Write-Host '[5/6] 隔离跑'
$others = Join-Path $suite '.others'
New-Item -ItemType Directory -Force -Path $others | Out-Null
Get-ChildItem (Join-Path $suite 'resolvers\*.json') |
  Where-Object { $_.Name -ne 'UIBC-selftest.json' } |
  ForEach-Object { Move-Item -Force $_.FullName $others }
Push-Location $suite
$env:NODE_TLS_REJECT_UNAUTHORIZED = '0'
& npx mocha tests/4-did-resolution.js --timeout 15000 *> (Join-Path $out '4-did-resolution.log'); $rc1 = $LASTEXITCODE
& npx mocha tests/10-bindings.js --timeout 15000 *> (Join-Path $out '10-bindings.log'); $rc2 = $LASTEXITCODE
Pop-Location
Remove-Item Env:\NODE_TLS_REJECT_UNAUTHORIZED -ErrorAction SilentlyContinue
if ($shimProc -and -not $shimProc.HasExited) { Stop-Process -Id $shimProc.Id -Force }

Write-Host '[6/6] 汇总'
$l1 = Get-Content (Join-Path $out '4-did-resolution.log') -Raw
$l2 = Get-Content (Join-Path $out '10-bindings.log') -Raw
$p1 = ([regex]::Matches($l1, '✓')).Count; $f1 = ([regex]::Matches($l1, '❌')).Count
$p2 = ([regex]::Matches($l2, '✓')).Count; $f2 = ([regex]::Matches($l2, '❌')).Count
# 实现来源写进 summary：没有这一行，"只换实现"的对照无法自证测的是哪份代码
$impl = (Get-Content (Join-Path $out 'shim.log') -ErrorAction SilentlyContinue |
         Where-Object { $_ -like '*impl=*' } | Select-Object -First 1)
@(
  "suite_commit=$commit"
  "node=$(& node -v) npm=$(& npm -v)"
  "port=$Port"
  "${impl}"
  "4-did-resolution: pass=$p1 fail=$f1 exit=$rc1"
  "10-bindings:      pass=$p2 fail=$f2 exit=$rc2"
) | Tee-Object -FilePath (Join-Path $out 'summary.txt')

Write-Host @'

读法（别误读成"通过"）：
  - 失败若集中在 did:key 成功路径，根因是共享测试 DID 为 P-521、本实现仅 ed25519，属已知边界；
  - 错误路径通过说明协议层合规；
  - 要拿"官方实现报告"需在 w3c 仓库提 resolver 清单 PR —— 对外动作，须本人批准。
'@
Write-Host "日志：$out"
