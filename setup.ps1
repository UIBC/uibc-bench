<# 一次性准备：检查运行时、克隆/更新被测仓库、建虚拟环境、生成自签证书、写入基线骨架。
   可反复执行，已存在的步骤会跳过。#>
[CmdletBinding()]
param(
  [string]$RepoUrl = 'https://github.com/zhaoxinghua09-cell/uibc-core',
  [string]$Commit   = '',          # 空则用远端默认分支最新
  [switch]$SkipVenv
)
$ErrorActionPreference = 'Stop'
$Kit = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Kit
function Say($m){ Write-Host "[setup] $m" }

# 1. 运行时
$py = (Get-Command python -ErrorAction SilentlyContinue)
if(-not $py){ throw '没有找到 python，先装 Python 3.10+ 并确保在 PATH 里' }
$pyv = (& python -c "import sys;print('%d.%d.%d'%sys.version_info[:3])").Trim()
Say "python $pyv  ($($py.Source))"
$node = (Get-Command node -ErrorAction SilentlyContinue)
if($node){ Say "node $(& node --version)" } else { Say 'node 缺失：JS 侧校验场景会记为 BLOCKED' }

# 2. 被测仓库（外人视角干净克隆，depth=1）
$repo = Join-Path $Kit 'uibc-core-public'
if(Test-Path $repo){
  $item = Get-Item -LiteralPath $repo -Force
  if($item.Attributes -band [IO.FileAttributes]::ReparsePoint){
    throw 'uibc-core-public 是符号链接/联接点，被测仓库的自审计会拒绝运行（它要求验证器来自仓内真实路径）。请删除该链接后重新执行 setup.ps1。'
  }
}
if(-not (Test-Path $repo)){
  Say "克隆 $RepoUrl"
  & git clone --depth 1 $RepoUrl $repo
} else {
  Say '仓库已存在，跳过克隆（需要更新请手动 git fetch 后 checkout，避免覆盖实测现场）'
}
$head = (& git -C $repo rev-parse HEAD).Trim()
Say "被测 HEAD $head"
if($Commit -and $Commit -ne $head){
  & git -C $repo fetch --depth 1 origin $Commit
  & git -C $repo checkout $Commit
  $head = (& git -C $repo rev-parse HEAD).Trim()
  Say "切到指定提交 $head"
}

# 3. 虚拟环境（可选，但推荐：与系统 Python 隔离，避免"机器上装过什么"影响结论）
$venv = Join-Path $Kit '.venv'
if(-not $SkipVenv){
  if(-not (Test-Path $venv)){
    Say '建虚拟环境 .venv'
    & python -m venv $venv
  }
  $vpy = Join-Path $venv 'Scripts\python.exe'
  Say '装 verify 与 test 附加依赖（cryptography / asn1crypto / pytest）'
  & $vpy -m pip install --quiet --upgrade pip
  & $vpy -m pip install --quiet -e "$repo[verify,test]"
  Say "venv python $(& $vpy -c 'import sys;print(sys.version.split()[0])')"
} else { Say '跳过虚拟环境' }

# 4. 自签证书（本地 HTTPS 测试床用，3650 天，只在 _pki 内）
$pki = Join-Path $Kit '_pki'
New-Item -ItemType Directory -Force -Path $pki | Out-Null
if(-not (Test-Path (Join-Path $pki 'cert.pem'))){
  Say '生成自签证书（SAN: localhost / 127.0.0.1）'
  & python (Join-Path $Kit 'harness\s02_did_hostile.py') --gen-cert-only 2>$null
  if(-not (Test-Path (Join-Path $pki 'cert.pem'))){ Say '证书未生成：s02 首次运行时会自动补' }
}

# 5. 基线骨架
$baseline = Join-Path $Kit 'baseline.json'
if(-not (Test-Path $baseline)){
  @{
    created      = (Get-Date).ToString('s')
    machine      = "$env:COMPUTERNAME / $env:USERNAME"
    python       = $pyv
    node         = if($node){ (& node --version).Trim() } else { $null }
    repo         = @{ url = $RepoUrl; commit = $head; cloned_at = (Get-Date).ToString('s') }
    cases        = @()
    known_issues = @()
    note         = '基线由首次通跑生成；新增用例请登记 cases，修好的缺陷改 known_issues.status=fixed，禁止删除 FAIL 条目'
  } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $baseline -Encoding utf8
  Say '写入 baseline.json 骨架'
} else { Say 'baseline.json 已存在，保留' }

Say '准备完成。下一步：.\run_all.ps1'
