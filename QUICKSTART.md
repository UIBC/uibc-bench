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

退出码：`0` 全部有产物且无 FAIL；`1` 有 FAIL/超时；`2` 前置检查没过（**这时 1 秒内就退出**，不会让你干等）。

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
