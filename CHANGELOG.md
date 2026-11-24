# CHANGELOG

每一行对应一个 tag，格式：版本 / 日期 / 一行改动 / 证据在哪。
**没有复跑日志的「修好了」不进这张表。**

## v0.4.40 — 2026-11-24

主题：**把"跑得出结论"升级为"结论能被别人接走"**。台子判定逻辑一字未改，新增的全是交付层与可复核层。

- 新增 `bench_report.py`：每次运行自动落 `results.junit.xml`（CI 零适配读取）、`report.html`（单文件、无外链、给人看）、`ATTEST.json` + `ATTEST.md`（全部产物 sha256 + `manifest_sha256` + 环境指纹 + 被测仓提交号，第三方可复算）
- 新增 `--attest` / `--no-junit` / `--no-html` / `--baseline <file>` / `--guide`（三个问题替新手选好要跑的组）
- 新增 `baseline/<平台>.json` 的 `excludes` 机制：把"本平台本来就不产出"的用例单独立档，避免每次刷屏"消失"。**判据仍只有 `baseline.json` 一份，excludes 不影响任何判定值，也不影响 `--strict`**
- 新增 `.github/workflows/bench.yml`：Windows + Linux 双平台 `--quick` 流水线，JUnit/HTML/存证作为 artifact 上传；可手动触发全量
- 修 `compare_baseline.py`：`--strict-missing` 之前只写在 `run.py` 的调用里、对方并不认这个参数（`--strict` 一开就 argparse 报错）；现在对方真的接收，且"消失"默认不再单独导致退 1（由 `run.py` 按 `--strict` 统一裁决）
- 订正 `QUICKSTART.md` 退出码口径（仍是 v0.4.37 定下的语义，文档还留在旧写法）；README 增补"结论怎么被接走""跟别的一致性测试台比"两节
- 复验：Windows `--quick --only s10,s02b,s06` 冒烟 → JUnit 可被 `ElementTree` 解析（23 例、3 skipped）、HTML 生成、存证生成、exit 0；`--guide` 非交互可跑
- 证据：`runs/<时间戳>/results.junit.xml`、`report.html`、`ATTEST.json`

## v0.4.39 — 2026-11-24

主题：把 v0.4.38 里**只在 Linux 验过**的那一版 D1 修到两个平台都成立。教训写在最前面：一种平台验过不等于验过。

- **真 bug**：v0.4.38 把 `fails` 从 `(类型, 名称)` 元组改成了 pytest 的 nodeid 字符串，但用例明细那里还留着 `for k, v in fails` 与 `[f"{k}:{v}" ...]`。Linux 上恰好 0 失败，这两处一次都没执行；Windows 上一旦有失败就 `ValueError: too many values to unpack`，整组被记成 ERROR。已改为直接使用 nodeid 字符串
- **顺手补的守卫**：没有被测仓时 D1 之前会在不存在的工作目录里抛 `NotADirectoryError`(WinError 267)。现在直接记 `BLOCKED`，并把三条设置口径写在结论里
- 复验（两个平台各自跑）：Linux `D1 PASS — 用例=1589 失败=0 跳过=7 用时=449s`；Windows `D1 PASS — 用例=1572 失败=0 跳过=25 用时=385s`
- 公开包全量（Windows，`python run.py --subject <main 工作树>`）：11 组全有产物、相对基线回归 0、exit 0
- 证据：`runs/<时间戳>/s04_full_suite_results.json`

## v0.4.38 — 2026-11-24

主题：**D1 改成跑被测仓 README 里那条命令**。这是上一版梳理里最后一个假失败源。

- **换了仪器**：`D1 外人全量单测` 原用 `python -m unittest discover tests -v`，而 `uibc-core` 的 README 让外人跑的是 `python -m pytest -q`。同一提交实测：unittest 收 **1157** 例、pytest 收 **1589** 例；用前者会把一个 pytest 风格用例（module 级 `importorskip`）记成 FAIL，实际照文档跑是绿的。判据是"外人照文档做能不能一次过"，仪器就该是文档里那条命令
- 解析跟着换：失败行从 `FAIL: x (mod.Cls.meth)` 改为 `FAILED path::nodeid`；汇总从 `Ran N tests / skipped=N` 改为 `N passed / N skipped`；单条复跑仍用 `pytest -k`
- 实测：Linux 干净克隆 `D1 PASS — exit=0 用例=1589 失败=0 跳过=7 用时=449s`；Windows 本机同一判据 `s04 PASS=5`
- 前一版顺带发现的真问题（被测仓 `EVIDENCE-INDEX.md` 的用例数在 Linux/Windows 上算出来不同）已在 `uibc-core` PR #424 修掉：改静态计数后两平台都是 1510，D1 不再因此报 FAIL
- 证据：`runs/<时间戳>/s04_full_suite_results.json`

## v0.4.37 — 2026-11-24

主题：**从"只有我这台机器能跑"改成"别人 clone 下来就能跑"**。这一版全是可用性修复，不动任何判据。

- **单一入口 `run.py`（跨平台）**：原先只有 `run_all.ps1`，Linux/macOS 的人根本进不来。现在一条命令：
  `python run.py` / `--quick` / `--only s10,s02b` / `--subject <dir>` / `--timeout N` / `--list`
- **每组超时真的生效**：`run_all.ps1` 声明了 `-TimeoutSec` 却**从未使用**，任何一组卡住整轮就不结束——外部使用者第一次跑就会撞上。现在超时即终止并记 `TIMEOUT`，其余组继续
- **被测仓统一解析（真问题）**：`s03/s04/s05/s07` 各自硬写 `<bench根>/uibc-core-public`，无视 `UIBC_SUBJECT`/`--subject`。后果是同一次运行里一半组测 A 仓、一半组仍是 `BLOCKED`/`ERROR`。新增 `harness/_subject.py` 后实测：同样指定被测仓，这四组从 **FAIL+ERROR+BLOCKED 变成 46 个 PASS**（s03 27、s04 5、s05 2、s07 12）
- **退出码语义改对**：以前"有用例 FAIL"就退 1，外人会以为 bench 自己跑挂了。现在退 1 只表示**台子坏掉**（组非 0 退出/超时/无产物）或**相对基线回归/用例消失**；用例 FAIL 是被测仓的结论，单列统计
- **`QUICKSTART.md`**：三分钟上手、五个判定词的含义、常见卡点表；README 抬头去掉本机私有路径与联接点描述
- `run_all.ps1` 改为转调 `run.py`（旧参数保留），逻辑只留一份
- 新增 `--update-baseline`（改基线=改判据，仍只在你确认后手动用）
- 本机实跑（Windows，被测仓 main）：**11 组全有产物，PASS=90 FAIL=10 BLOCKED=10 REFERENCE=1 SKIP=5，总耗时约 6.5 分钟**；s04 最慢（313s，跑被测仓全量单测）
- 证据：`runs/<时间戳>/summary.json`、`baseline_diff.json`

## v0.4.36 — 2026-11-24

- **s10 补上"带盐可判"这一档**：新增 I15–I18（`harness/s10_identity_code_interop.py`），把校验码从"永远只能判未验证"推进到"有盐判对错"
  - I15 规范算例 + 示例盐 → `VERIFIED`，evidence 含 `acps-arc10:0JU4` 与 sha256
  - I16 段序无关：overview §5.2 的另一种段序同样 `VERIFIED`
  - I17 末位篡改 → `INVALID`
  - I18 无盐 / 短盐 → `INCONCLUSIVE`，明写 checksum NOT checked
- 修正两处过期表述：原文版本 `v02.01` → **`v02.02`**；I9 断言跟着新 detail 改（"not checked"而非"unverified"）
- 本轮实跑：**11 PASS + 1 REFERENCE**（被测对象取 `uibc-core` main `6187e96` 公开 tar.gz，来源守卫在位）
- 负向守卫复测：把 `UIBC_SUBJECT` 指到不含 `uibc_core` 的目录 → `[ABORT]` 退出码 1（不是静默退回已安装包）
- 场景清单 `cases/场景清单.md` 补 10.9–10.12
- 证据：`s10_results.json`

## v0.4.35 — 2026-11-24

- **来源守卫**：`harness/s10_identity_code_interop.py` 在导入后检查 `uibc_core.__file__` 是否真在被测路径之下；指错目录或目录不存在一律 `[ABORT]` 退出码 1，不再退回机器上已安装的同名包照样出结论
- 场景清单补登记：`cases/场景清单.md` 新增第十一节，把 I 组 s10 的 8 条（10.1–10.8）与三条边界写进矩阵
- `cases/身份码两套体系_20261124.md` 增记**换机复跑**：Linux 云主机 + 公开 tar.gz（bench 与被测仓都取 main），7 PASS + 1 REFERENCE，与本机逐项一致
- 证据：`s10_results.json`（Windows 复跑，守卫版）；云主机逐行输出见场景文档

## v0.4.34 — 2026-11-24

- 新增 I 组 **s10 身份码两套体系互操作**：`harness/s10_identity_code_interop.py`（八段国标 vs 十段 ACPs 两个读取器互为对方拒收；校验码不判；无 `VERIFIED` 出口）
- 新增场景文档 `cases/身份码两套体系_20261124.md`，含 7 PASS / 1 REFERENCE 的逐项结果与本组边界
- 第三方 Rust 实现（`aipmc-basic` 0.0.2）记 **REFERENCE**：引用 `uibc-core` 2026-11-24 实跑日志，本台不复算，不把它算成 PASS
- 证据：`s10_results.json`（本机 Windows、Python 3.12 实跑，被测对象 `uibc-core` main `a3b4a82`）

## v0.4.33 — 2026-11-24

- 新增 `AGENTS.md`（任何账号/会话/机器的接手入口）、`SECURITY_AND_ROLES.md`（三身份权限边界）、本 `CHANGELOG.md`
- 公开仓 `UIBC/uibc-bench` 建立，供其他账号与会话接手；`main` 分支禁强推禁删
- 证据：本仓以 roots 跑 `gate_all.py` → `GREEN 5/5`、硬伤 0

## v0.4.32 — 2026-11-24

- 移除误跟踪的 `.venv312/`（724 文件），`.gitignore` 补该条（缺陷 #59）；历史不改写，保住 `7338bca/238fad3/0eb58bc` 的引用有效
- 生成公开快照（剔 3 份不宜公开的 cases 文稿）
- 证据：`git ls-files` = 76；快照 74 文件

## v0.4.31 — 2026-11-24

- 件位判定从「一个 MISSING」拆成六类：`PATTERN`（通配/裸扩展名）、`SELF`（包自身）、`TRIMMED`（裁剪目录）、`EXTERNAL`（盘符绝对路径，须文档标「未随包」）、`HASHDECL`（按清单存证）、`OK`；只有 `MISSING` 计硬伤
- `evidence_grades.py` 增 `--hash-manifest` 与 `selfref`，不再把「哈希可核」误判为不可核
- 三读者同判：作者机 `GREEN 5/5`（缺失 9 / 存证 777 本地引用）、精简包 `GREEN 5/5`（缺失 19 / 存证 125）、全量归档 `GREEN 5/5`（缺失 19 / 存证 102），硬伤均 0
- 证据：`53_件位判定与三读者同判_v0430-0431.md`、`53_三读者证据\{author,slim,full}\gate_stdout.log`

## v0.4.30 — 2026-11-24

- 新工具 `tools/hash_manifest.py`：扫根目录产 `handoff_hash_manifest.json`（files/trees/dirs + SHA256）
- `package_audit.py` 接 `--hash-manifest`，命中清单 → `HASHDECL`；`gate_all.py` 透传
- 思路转变：**件不随包、哈希随包**（不再为「件在不在包里」改 31 篇文档）

## v0.4.29 — 2026-11-24

- 把口径 A/B 量成数字：B 口径须改 **31 篇 / 98 处**，改动成本高且不解决根问题
- 修补件按根归档（`files/<盘符_根名>/` + `ROOTS.txt`）
- 二轮干净目录复跑仍 `RED 129/112` → 证明剩余项与「补件摆法」无关，与解析根集合有关

## v0.4.28 — 2026-11-24

- 52 号最大发现：干净目录从零解包复跑 `RED`，根因是**审计解析根集合只在作者机上成立**
- 新工具 `handoff_bundle.py`，把交付物分五类（代码 / 文档 / 证据 / 分发物 / 运行时产物）

## v0.4.27 — 2026-11-23

- 51 号收尾（十节），生成 `manifest.json`（逐文件 SHA256）与两份归档
