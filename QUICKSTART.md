# QUICKSTART — uibc-bench，三分钟能跑出第一张表

需要：**Python 3.10+**（其余全是标准库，无需 pip 装任何东西）。可选：node（JS 侧校验场景，没装就记 BLOCKED）。

## 1. 拿 bench 和被测算的仓

```bash
git clone --depth 1 https://github.com/UIBC/uibc-bench.git
git clone --depth 1 https://github.com/zhaoxinghua09-cell/uibc-core.git uibc-bench/uibc-core-public
cd uibc-bench
```

> Windows 上别用 `tar` 解 tarball：非 ASCII 文件名会按本地代码页解码（`résumé.md`→`r茅sum茅.md`），
> 被测仓里几个字节锚定的用例会因此假失败。要解包请用 `python -m tarfile`。

## 2. 跑

```bash
python run.py            # 全部 11 组，约 6–8 分钟
python run.py --quick    # 跳过 s04/s05/s08，约 40 秒
python run.py --list     # 只看有哪些组
```

指定别的被测仓：`python run.py --subject /path/to/uibc-core`（Windows：`--subject "D:\wt\uibc-core"`）。

跑完你会看到：

```
==============================================================================
组                                              用时 状态         判定
------------------------------------------------------------------------------
s01_platform_contract                         6.6s ok         PASS=13 FAIL=7
...
------------------------------------------------------------------------------
合计：PASS=... FAIL=... BLOCKED=...
产物：runs/20261124_204619
```

产物：`runs/<时间戳>/<组名>_results.json`、`run.log`、`summary.json`。

## 3. 读结果

| 判定 | 含义 | 你该做什么 |
|---|---|---|
| `PASS` | 该用例成立 | 无 |
| `FAIL` | 被测仓在某条判据上不成立（**是它的结论，不是 bench 坏了**） | 看该组 `_results.json` 的 `note`，对照 `baseline.json` 判断是新增回归还是已知项 |
| `BLOCKED` | 缺前置（没装 node、仓里没这个文件、需要 Release 包） | 补前置再跑；不算失败，退出码不受影响 |
| `REFERENCE` | 结论引自第三方实跑日志，本台不复算 | 无 |
| `TIMEOUT` | 该组超时被终止，子进程树一并杀掉（默认每组 900s，`--timeout` 可调） | 先单独跑该组看它卡在哪 |

退出码：`0` 台子正常（每组都有产物、无超时、相对基线无回归）；`1` 台子坏掉（组没跑完/超时/无产物）或相对基线出现回归/用例消失；`2` 前置检查没过（**这时 1 秒内就退出**，不会让你干等）。**用例级 FAIL 是被测仓的结论，不改变退出码**——这正是它跟"一红就退 1"的台子最大的不同。

## 4. 上次跑的和这次比

```bash
python compare_baseline.py runs/<时间戳> --baseline baseline.json
```

`run.py` 默认会自动做这一步。确认状态确实变好了才用 `--update-baseline` 刷基线——**改基线等于改判据**。

发布前自查用 `python run.py --strict`：这时"基线里的用例本次没产出"也算失败（平时不开，换平台会误报）。

## 5. 常见卡点

| 现象 | 原因 | 处理 |
|---|---|---|
| `[preflight] 没过 … 没有找到被测仓` | 没给 `--subject` 也没 `UIBC_SUBJECT` 也没 `./uibc-core-public` | 三条路任选一条，提示里写全了 |
| 某组 `TIMEOUT` | 该组本身慢（s04 跑被测仓全量单测，约 5 分钟） | `--timeout` 调大，或 `--quick` 跳过 |
| 一堆 `BLOCKED` | 没装 node / 被测仓本提交里没有对应文件 | 属预期，看 `note` 里写的原因 |
| 被测仓是符号链接/联接点 | 被测仓的自审计要求验证器来自仓内真实路径 | 用真实目录克隆，别用链接 |

## 6. 把结论交出去（JUnit / HTML / 存证）

默认每次运行都会在 `runs/<时间戳>/` 里落三件交付物，不需要额外开关：

| 文件 | 给谁 | 怎么用 |
|---|---|---|
| `results.junit.xml` | CI | GitHub Actions / Jenkins / GitLab 直接解析，零适配。FAIL→failure、超时→error、BLOCKED/SKIP→skipped |
| `report.html` | 人 | 单文件、无外链、无 CDN，双击即看；含逐条明细与基线差异 |
| `ATTEST.json` + `ATTEST.md` | 第三方 | 全部产物的 sha256 + `manifest_sha256` + 环境指纹 + 被测仓提交号；只在你加 `--attest` 时生成 |

```bash
python run.py --attest                 # 连存证一起出（对外交付/存档时用）
python run.py --no-junit --no-html     # 只要 JSON 时
python run.py --guide                  # 完全不想记参数：三个问题替你选
```

第三方复算口径：拿到整个 `runs/<时间戳>/` 目录后，逐文件重算 sha256 与 `ATTEST.json` 里
`files[].sha256` 比对；再把 `"<sha256>  <path>"` 逐行拼接后算 sha256，应等于 `manifest_sha256`。
对不上说明文件被改过——这就是"可被外人复算"的具体含义。

## 7. 平台差异怎么登记（不放松判据）

有些用例本来就只在一个平台产出（Windows 默认克隆、cp936 代码页、行尾配置）。这类"在本平台没产出"
不是缺陷，也不该每次刷一屏"消失"。做法是登记进 `baseline/<平台>.json` 的 `excludes`，写明理由：

```json
{
 "platform": "linux",
 "excludes": ["M4 控制台编码 cp936 下 CLI", "D1 跳过原因归档"],
 "evidence": {"run": "runs/20261124_231016", "note": "Linux 全量实测后确认这些用例不产出"}
}
```

判据仍然只有 `baseline.json` 一份；`excludes` 只影响"消失"提示，不影响任何判定值，也不影响 `--strict`。

