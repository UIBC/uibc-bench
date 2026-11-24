# CHANGELOG

每一行对应一个 tag，格式：版本 / 日期 / 一行改动 / 证据在哪。
**没有复跑日志的「修好了」不进这张表。**

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
