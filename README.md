# 信通院身份码 · 实测台（uibc 实测台）

一个**可反复复跑、能对比基线、结论可被外人复算**的测试台。不依赖任何一次聊天会话，也不依赖我的本机路径。

**先跑起来（三分钟）**：装 Python 3.10+，克隆 bench 与被测仓，然后

```bash
python run.py            # 全部 11 组
python run.py --quick    # 跳过最慢的三组，约 30 秒
```

完整上手、退出码含义、常见卡点见 [QUICKSTART.md](QUICKSTART.md)。跨平台：Windows / Linux / macOS 同一条命令，
除标准库外无依赖（node 可选）。

---
## 引用与反馈 · Citation and feedback

**引用、转载、复用，不必事先征得我们同意。** 直接引用、直接复用、直接跑、直接接着做，不用再来问。按通常格式署名即可（作者、标题、DOI 或仓库提交号、日期）。本仓为 Apache-2.0，保留许可证声明即可。除此之外没有任何条件。

**You do not need to ask us to cite, quote, or reuse this work.** Cite it, quote it, run it, build on it — no permission request is needed. Attribution in the usual form is appreciated. This repository is Apache-2.0; keep the licence notice. No other condition.

有意见请开 issue：bug、问题、意见、复跑回执都可以。请附上运行环境、提交号和数字，并给出公开可查的地址。File an issue for anything — bugs, questions, opinions, rerun receipts — with runner, platform, commit, numbers, and a public address.
---

## 它解决什么问题

上线前/上线后每次改动，都要能回答三个问题：

1. 上次能跑的，这次还能跑吗？（回归）
2. 上次没测的，这次覆盖到了吗？（新增场景）
3. 上次记录的错误行为，这次是修好了还是照旧？（基线比对）

## 结论怎么被接走

跑一次不只出一张终端表，还会在同目录落四件东西——**给脚本的、给人的、给第三方的分开**：

| 产物 | 谁消费 | 说明 |
|---|---|---|
| `summary.json` | 你的脚本 | 机读汇总：每组状态、用时、判定计数、基线名、平台 |
| `results.junit.xml` | CI（GitHub Actions / Jenkins / GitLab） | JUnit XML，不需要写适配器。FAIL→failure、超时→error、BLOCKED/SKIP→skipped |
| `report.html` | 评审会、发给他人 | 单文件、无外链、无 CDN，双击即可看；带逐条明细与基线差异 |
| `ATTEST.json` / `ATTEST.md` | 第三方复核 | 本次全部产物的 sha256 清单 + `manifest_sha256` + 环境指纹 + 被测仓提交号。别人重算哈希就知道有没有被改过 |

```bash
python run.py --attest                                    # 连存证一起出
python run.py --guide                                     # 不懂参数：三个问题替你选好
python run.py --only s02 --subject ../uibc-core           # 只查一组
python run.py --baseline baseline/2026-11.json            # 用指定基线判回归
```

平台差异不走"另存一份基线"（那等于让判据跟着平台漂）：`baseline/<平台>.json` 里只登记
`excludes`——本平台**本来就不产出**的用例，写清理由，避免每次刷一屏"消失"。

## 跟别的一致性测试台比，差在哪、好在哪

同类的公开台子（都读过一遍，取它们的强项补自己的短板）：

| 台子 | 它的强项 | 我们做了什么 |
|---|---|---|
| WPT / wpt.fyi | 机器可读报告 + **expectations 基线**用于 CI 回归；结果可上传比对 | 机读 `summary.json` + 基线回归（时间维度），并比它多一层"平台差异单独立档" |
| OpenID conformance suite | **Guided 模式**：新手按生态/角色选测试计划，不用懂内部；结果可发布 | `--guide` 三个问题选路；`report.html` 可直接发给评审人 |
| CNCF conformance（Sonobuoy） | "任何终端用户都能用同一个开源工具确认合规"；跑完出可归档报告包 | `ATTEST.json` 哈希存证 + 归档目录，第三方拿到即可复算 |
| PTA / MCP 等新兴 harness | 同时出 TAP 与 JSON，`--fail-fast`、插件化 | JUnit + JSON 双格式；组级超时与整树 kill 比 `--fail-fast` 更安全 |

我们与它们的**实质差别**在判词语义：它们大多"有用例失败 → 进程退非 0"。我们把两件事拆开——

- 退出码只说**台子自己**好不好（组跑完没、超时没、相对基线有没有回归）；
- 用例级 FAIL 是被测方的结论，单独统计，并标注"其中相对基线新增 N 条"。

这样外人第一次跑不会被"红"吓退，也不会把被测方的历史缺陷算到台子头上；要严格发版，用 `--strict`。

## 目录

```
uibc-实测台/
├─ README.md              本文件
├─ baseline.json          基线：仓库提交号、Python/Node 版本、场景清单、已知缺陷清单
├─ baseline\<平台>.json   平台差异补充登记（只写"本平台本来不产出"的用例与理由，不另立判据）
├─ bench_report.py        导出 JUnit / report.html / ATTEST（产物哈希清单）
├─ .github\workflows\bench.yml  Windows + Linux 双平台 --quick 流水线，产物作为 artifact 上传
├─ thresholds.json        性能阈值（F 组用；改阈值就是改判据，需在场景清单写理由）
├─ VERSION                当前版本号（0.4.42 = 交付层 + 跨平台修正 + 被测仓出处可证）
├─ run.py                 **单一入口**（跨平台）：选组、每组超时、跑完出一张表 + summary.json；退出码 0/1/2
├─ QUICKSTART.md          三分钟上手、判定词义（PASS/FAIL/BLOCKED/REFERENCE/TIMEOUT）、常见卡点
├─ first_run.py           一键首跑（陌生人 5 步内跑出结论，见 FIRST-RUN.txt）
├─ package.ps1           打可分发包（zip 带顶层目录 + sha256）
├─ dist\                  分发包与 git bundle（给别人/归档用）
├─ setup.ps1              Windows 便捷脚本：一次性准备（克隆/更新仓库、建虚拟环境、自检）；非必需
├─ run_all.ps1            Windows 便捷脚本：转调 run.py（保留旧用法，`-TimeoutSec` 现在真的生效）
├─ compare_baseline.py    与基线比对，输出回归/修复清单（退出码 0=无回归）
├─ cases\场景清单.md       场景矩阵登记表：谁测的、测什么、判据、当前状态
├─ harness\               场景脚本，一个文件一个场景组
│   ├─ s01_platform_contract.py   平台契约（信通院 iaisp 只读）
│   ├─ s02_did_hostile.py         did 解析对抗性（自签 HTTPS 测试床）
│   ├─ s02b_did_hostile_clean.py  关键点干净对照（id 自洽，避免假阳性/假阴性）
│   ├─ s03_ecosystem.py           MCP / A2A / Node / CLI / 并发锁 / 时区 / 泄漏
│   ├─ s04_full_suite.py          外人全量单测 + Release 包 + 一致性工具
│   ├─ s05_windows_default_clone.py  Windows 默认 clone 行尾守卫（E 组）
│   ├─ s06_perf_thresholds.py     性能阈值（F 组，超阈值报 WARN/FAIL）
│   ├─ s07_package_boundaries.py  包与证据层对抗边界（G 组）
│   ├─ s08_env_matrix.py          环境矩阵（M 组：12 项环境条件逐一取证，做不了的必须给探测证据）
│   └─ s09_interop_third_party.py  跨实现互操作（I 组：与第三方 did:web 解析器逐字段比对）
│                                  I2/I4 解析的是第三方主体已发布的公网身份（identity.foundation /
│                                  veramo.io / danubetech.com），需要出网；没出网时这两条记 BLOCKED 并写明原因，
│                                  I3–I6 的第三方依赖缺失时不静默：记 BLOCKED，并额外记一条 WARN「互操作未验证」
├─ tools/                 可复跑的外部基准接入件（不参与 bench 计分）
│   ├─ resolver_https_shim.py     最小 HTTPS binding：把库函数按 DID Resolution 规范暴露成 endpoint
│   ├─ aitb_bridge.py           AITB（试真台）桥：full / interop / negctl（负对照）\n│   ├─ official_suite/            官方 W3C 套件的接入说明 + 我方 resolver 清单
│   └─ interop/                   第三方解析器（npm）的 package.json 与 resolve 脚本
├─ uibc-core-public\      被实测的仓库（外人视角的干净克隆，不推不改）
├─ runs\                  每次运行的结果（JSON + 日志），永不覆盖
└─ _pki\、_logs\           自签证书、运行日志（可删可再生）
```

## 怎么跑

```powershell
cd C:\Users\SZYL\Doubao\uibc-实测台
.\setup.ps1            # 首次或换机时跑；已就绪可跳过
.\run_all.ps1          # 跑全部场景
.\run_all.ps1 -Only s02b,s03     # 只跑指定组
```

每次运行产出 `runs\<yyyyMMdd_HHmmss>\`：

- `runs\<时间戳>\s01_results.json` … 每个场景组一份，字段固定：`case / verdict / note / extra`（结果落在 `runs\` 下，不随包分发）
- `run.log` 原始控制台输出
- `summary.json` 计数汇总 + 与基线的差异
- `summary.html` 人读的可视化看板（同一台子每次都能生成）

`verdict` 取值含义：

| 值 | 含义 |
|---|---|
| PASS | 按判据通过 |
| FAIL | 判据不通过，且是**被测方**的问题（要修或要报） |
| WARN | 可疑但需人工判断，或属已知取舍 |
| INFO | 观测值，无判据（延迟、条数、字段集合等） |
| BLOCKED | 环境缺失导致无法测（必须写明缺什么） |
| ERROR | 脚本自身出错，不是被测方问题 |

## 加一个新场景

1. 在 `harness\` 下新建 `s05_xxx.py`，或往已有组里加一段 `def case_xxx()`；
2. 用 `rec(用例名, 判定, 说明, extra)` 记录，**一定要写"为什么这么判"**；
3. 每个用例必须能重复跑、不污染平台（对信通院平台只做只读 GET 与无状态 resolve 查询，
   不注册、不写入、不改任何平台状态；并发不超过 8）；
4. 在 `cases\场景清单.md` 登记一行：场景、真实上线时对应什么情况、判据、当前状态；
5. `.\run_all.ps1 -Only s05` 单独验证，再跑一次全量确认没影响别的组。

## 基线怎么维护

`baseline.json` 记录"当前公认的状态"。第一次跑完生成；之后：

- 修好了某个 FAIL → 改 `known_issues` 里对应条目的 `status` 为 `fixed`，保留原描述与首次发现日期；
- 新增场景 → 加进 `cases` 列表；
- 升级被测版本 → 改 `repo.commit`，并重跑生成新基线；
- 绝不要把 FAIL 静默删掉来"让结果变绿"——`compare_baseline.py` 会把消失的用例标为 `missing` 并报出来。

`baseline.json` 里的 `subject_head` 是**这份基线测的是哪一棵树**。CI 按它钉住克隆，不去取被测仓 HEAD：
否则被测仓每合一次改动，这边就多一条"回归"，红的理由却不在台子上。被测仓 main 领先多少会打在
job summary 里，但不判红——基线老了这个信号交给人类决定要不要重录。

## 红线（写在脚本里也写在人心里）

- 只读探测信通院平台；发现的问题先内部复核，再决定对外口径，**不直接对外发布**。
- 不对真实平台做压测、不做写操作、不批量注册 DID。
- 发现缺陷后先确认是不是**我们自己的调用姿势**问题，再判断是不是对方的问题。
- 任何"修好了"的结论，必须有复跑日志做证据，不接受"应该好了"。
- **一键脚本冒烟非 400 即中止**（v0.4.6 起）：`000` 表示 endpoint 压根没起来，继续跑只会产出"看着像基线"的假结果。

## v0.4.6 改了什么（两处载体缺陷，都是靠官方用例才暴露）

1. `tools/resolver_https_shim.py`：解析成功时 HTTP `Content-Type` 必须等于 `didResolutionMetadata.contentType`
   （规范要求两者相等，且 contentType 描述的是返回文档的表示 → 都应为 `application/did+ld+json`）。
   旧版写成 `application/did-resolution`，在 `10-bindings` 卡红 1 条；修后该断言转绿。
2. `tools/run_official_suite.ps1` / `.sh`：冒烟状态码非 `400` 直接 `exit 2`，不产出任何结果。
   旧版只打印一行就继续，曾真产出过一份 `2/13` 的"基线"。
3. 新增 `UIBC_REPO` 环境变量（shim）：让 shim 指向另一个候选实现做**只换实现**的对照实验，默认行为不变。

## 已知坑（踩过的，别再踩）

1. **Windows 默认 clone 会打挂 47 条单测**。`core.autocrlf=true` 会改写 1328 个文件的行尾，
   而 `tests/fixtures/` 下有一批**字节锚定**文件（测试里硬编码 sha256），一改就全错。
   必须 `git -c core.autocrlf=false clone`（`setup.ps1` 已这么做）；常设守卫是 `harness\s05_windows_default_clone.py`。
2. **不要用 `git status` 判断工作树干净**。行尾被改写时 status 也可能干净，但字节已经变了。
3. **别把 INCONCLUSIVE 当失败**。三值判定：`0 PASS / 1 INCONCLUSIVE / 2 FAIL`；空证据包本来就给 INCONCLUSIVE。
4. **别用 `success:true` 判断平台解析成功**。信通院平台对非法输入与不存在的 DID 也返回 `success:true`，
   必须看 `data.summary.resolutionStatus`（`vcVerificationStatus` 目前恒为 `SKIPPED`）。
5. **部分场景跑的时候不要更新基线**。`run_all.ps1 -UpdateBaseline` 只在确认状态变好、且覆盖全量时使用；
   只跑单组时用 `python bench.py run --only s0x`，不要 `--update`。

## 判定口径（避免"为了变绿而改判"）

- FAIL 必须能指向**被测方**的问题；如果是脚本自己写错（参数、期望值），改脚本并留注释说明为什么改。
- 一次"通过"不能靠放宽判据获得；放宽要在 `cases\场景清单.md` 里写理由。
- 每次判定争议都写进 `note` 字段——那是给人看的推理过程，不是给机器看的。

## v0.4.17 改了什么（2026-11-23 深夜）

1. **S0 三钉** `tools/spec_pin.py`：DID Resolution 是 ED、没有修订号，于是改钉"URL + 当日正文 SHA-256 + 章节锚点"，并把 `id` 列表拉下来逐锚点核。实测发现 `#types`、`#did-resolution-options` 已不在当前 ED 的 id 列表里，**而 `…/#types` 仍返回 200**——"状态码不是证据"的又一个现场。
2. **S6/S1 外部评审脚本化** `tools/external_review.py`：只喂正文 + 一手源 URL，`temperature=0`，记录模型、提示词哈希、耗时、token 用量。第八轮 17 条（可核实 7），补了证据索引后第九轮 28 条（可核实 1）——**加料反而更不绿**，因为审核方打不开我们的文件；这条如实写进 40 号，不为变绿而改判。
3. **S9 可见性判据** `tools/github_visibility.py`：只用 git 协议（匿名 `ls-remote`），不用 REST——匿名 API 对私仓 404、对限流 403，混用就是"403 式绿"。被测仓判 PUBLIC，HEAD `da0dc9be5b38…`。
4. 我方测试台仍未推 GitHub（S9 = N/A），替代核验方式是随包附单文件 HTML；推送就绪物是 `dist\uibc-bench-v0.4.17.bundle`，推完要跑的三条命令写在 40 号。

## v0.4.16 改了什么（2026-11-23 深夜）

1. **审查包自检尺子** `tools/package_audit.py`：把 S5（本地文件引用 MISSING=0）与 S7（200 且**内容标记命中**，202/403 记 BLOCKED）合成一条可复跑命令。首跑 360 条本地引用、47 条外链。它自己先错 6 回才可用：全角标点入 URL、模板/占位链接、`#:~:text=` 片段、解析器端点根 URL（不带 DID 恒 400）、第三方快照目录、ReSpec `[=术语=]` 切句——每类都造成过假 DEAD，逐条修在工具注释里。
2. **红线扫描** `tools/no_claim_scan.py`：S2-L2 层，16 个硬禁词 + 8 个市场宣称软词，命中按行级语境判 `HIT` / `NEGATED`。首跑 53 条假 HIT，收紧到 4 条、人工复核 0 条真硬伤。
3. 产出 `38_九门自查_S0-S9.md`：十门里 **7 过 / 1 部分 / 2 阻塞**。阻塞不在脚本里——S1 没有独立专家（只有外部 AI，记 machine reviewer）、S2-L3 没有发件人授权。S0 部分：DID Resolution 只有 ED，钉不到修订号。
4. 自查真抓到 1 条引用错误：`10_S6响应与整改.md` 引 `11_跨OS全组复核.md`，实际是 `11_S1跨节点复核.md`，已改正。

## v0.4.15 改了什么（2026-11-23 深夜）

1. **登记预演** `tools/registration_preflight.py`：读套件 `did-methods/*.json` 与候选清单，算出"这次登记会新增几条用例"。用于在提 PR 之前发现"声明是空头"。
2. 预演结论：声明 `did:web` 新增 **0** 条用例（套件无 `did-methods/web.json`）；换 `did:webvh` 新增 1 条但会红（向量是公网真实 DID）。所以"补第二方法"是实现工作量，不是登记工作量。
3. 纠正 v0.4.13/35 号里"选 did:web 最省力"的建议——省力的是**自证**，不是**门槛**。

## v0.4.14 改了什么（2026-11-23 深夜）

1. **第二方法证据** `tools/did_web_probe.py`（W1–W12）：本机起 HTTPS 发布 `did.json`，验证 `did:web` 的 URL 映射、取文档、`id` 一致、以及非 JSON / id 不一致 / 404 / 空主机四类错误路径不静默；并断言"同一实现里 `did:key` 仍可离线解析"。双 OS **12/12**。
2. **纠正此前表述**：被测仓原始 HEAD `7da57d6` 的 `SUPPORTED_METHODS` 就是 `("key","web")`——缺口是"没有证据 + 没有登记"，不是"没实现"。
3. 探针自身两处缺陷已修（#17 端口未用 `%3A` 编码导致去连 443、#18 首连早于监听就绪）；都不计入被测缺陷台账。

## v0.4.13 改了什么（2026-11-23 深夜）

1. **Windows 无 openssl 也能跑（第 17 个缺陷）**：`tools/make_cert.ps1`（.NET `CertificateRequest` 自签，不需要管理员、不依赖 openssl），`tools/binding_probe.py` 与 `tools/run_official_suite.ps1` 在 `openssl` 缺失时自动回落。此前 Windows 全新目录会直接 `[EXIT=2] 缺少 openssl`。复跑日志：全新目录解包 → `[cert] generated` → 冒烟 `400` → A 侧 `10/5` + `4/6`；探针在同环境下 `15/15`。
2. 无 openssl 路径下生成的 `key.pem` 是 PKCS#8（`BEGIN PRIVATE KEY`），`ssl.load_cert_chain` 直接可用，已实测。

## v0.4.12 改了什么（2026-11-23 深夜）

1. **远程端点只读探针** `tools/probe_remote.py`（B1–B17）：把本台断言拿去打**公开注册端点**（DIF / cheqd / DCD-BTCR2 / iden3），三档判定 `PASS / FAIL / N/A`，**N/A 既不算通过也不算失败**（没有该方法的有效 DID 时就记 N/A）。礼貌节流、`User-Agent: uibc-bench-probe/0.4.12`、只做 GET。
2. **修掉探针自身三个判据缺陷**（#14–#16）：`dict(r.headers)` 键大小写导致读不到 `Content-Type`；5xx 判据把合法的 `501 METHOD_NOT_SUPPORTED` 当崩溃；负向用例用了未知方法 DID，被 501 前置拦截而假通过（现改为"有有效 DID 就用它"）。`error.type` 的 URI 形式从 FAIL 降级为 INFO 观察项（规范只要求有 error 对象）。
3. **教训写进工具注释**：公开端点会被网关限流（DIF 本次全部 403，响应体是 `{"status":403,...}`），所以**远程探针只做观察，不作为竞品结论来源**；评价别人只引公开物料。

## v0.4.11 改了什么（2026-11-23 晚）

1. **规范追踪矩阵** `tools/spec_traceability.py` + `tools/spec_map.json`：把官方 23 条断言逐条对齐到 141 条用例与探针，机械校验"断言数=映射数、用例名/探针 id 必须存在"。结果：bench 直连 3 · 探针 19 · 前置 1 · 仅套件 0。
2. **绑定层探针** `tools/binding_probe.py`（P1–P15）：不依赖官方套件，只用标准库打 HTTPS，覆盖 200/400/501/406、Content-Type 一致、URL 编码、错误对象、空 metadata、HTTPS-only。双 OS × 双实现四组 15/15。
3. 两者都**不进 141 条基线**（与 keytype_vectors 同理），作为独立证据存在。

## v0.4.10 改了什么（2026-11-23）

1. **证书自举**（第 11 个缺陷）：`run_official_suite.ps1` / `.sh` 在起 shim 前检查 `_pki/cert.pem` 与 `key.pem`，缺失就用 `openssl` 就地生成；没有 `openssl` 明确中止、不产出任何结果。此前"解包后不先跑 `setup.ps1`"会得到冒烟 `000`，而提示只说看 `shim.log`，看不出缺证书。
2. **`UIBC_SHIM` 注入点**：可让一键套件脚本使用任意载体副本，用于变异测试；默认仍是正式 shim。
3. **载体变异测试** `tools/mutation_test_shim.py`：4 个单点变异（Content-Type、metadata contentType、文档 id、错误码映射）+ 1 个对照，判定写死在工具里（KILLED / SURVIVED / NO-RUN，对照要求"两组都读到 + 绿 ≥20 + 红 0"）。双 OS 4/4 击杀，对照 `15/0`+`10/0`。

## 现状与差距（自己先说清楚）

**是能用的基础设施，还不是"别人能直接托付"的基础设施。** v0.2.0：118 条用例、8 个组。

| 标准 | 现状 |
|---|---|
| 没参与的人半小时内能复跑出同样结论 | **过**：zip 解压即跑（包内有顶层目录），缺仓库的组报 BLOCKED 并给命令 |
| 结论能被第三方独立推翻或确认 | **没过**：118 条判定仍是自查自证，需 LGD-Eval 独立复跑 + Muse 终审 |
| 换环境（Linux / Py3.10 / 无 Docker）结论还成立 | **不知道**：只在 Windows + Py3.12/3.13 跑过 |
| 变慢能被发现 | **过**：`thresholds.json` + F 组，超阈值判 WARN/FAIL |
| 对抗性输入能守住 | **部分**：包层 7 条守住（穿越/重复键/只读/时区），标识符校验偏松 |

缺口清单见 `cases\差距与未覆盖_20261123.md`；规范对照见 `cases\规范对照调研_20261123.md`；
保存与异机归档见 `cases\保存与分发_20261123.md`。

## 换机迁移

把整个 `uibc-实测台` 目录拷到新机器，`.\setup.ps1` 会自动重建虚拟环境与证书；
`baseline.json` 跟目录走，历史 `runs\` 建议保留（比对价值在历史里）。





## v0.4.18 改了什么（2026-11-23 夜）

上一轮把"外部复核越给越不绿"解释成 S6 的机制属性。本轮七轮实跑把这条解释推翻了一半，并顺带**证伪了"可核实率"这个指标本身**。

1. **证据包** `tools/evidence_pack.py`：按"门 → 文件"映射（写死在代码里，可被机器校验）先验 22 件原件是否都在包内，再把**原始行**按上限摘出来——这是"让评审方看得见文件但不发布任何东西"的做法。`--verify-only` 就是一把 S5 尺子。
2. **门级对照矩阵** `tools/review_matrix.py`：把句子级判定正则归到 S0–S9，最不利优先收敛成门级结论，再算两两一致率。**没有它，条数 16→27→10→46 的漂移会让"可核实率"变成不可比的分母。**
3. **测出来的东西**（七轮，两厂商）：
   - 同模型同输入重复 **1.00**（temperature=0 可复现）；跨厂商 v1 **0.90**、v2 **0.60**；"看不看得见原件"这一项改动造成 **0.10–0.30**。
   - 证据包 v1→v2，DeepSeek 从 6 门可核实变 **10 门全可核实**，Qwen 仍 6 门。**判定随证据量单调变绿**＝供应侧通胀，不是证据变强。
   - 由此定仪器规格 v3：证据包必须版本化+哈希、判定单元固定门级、必须双厂商、门级一致率 ≥0.90 才可机判、**禁止把"可核实率"当通过判据**。重算结果：**6 门可机判 / 4 门转人工（S1/S2/S4/S6）**。
4. **修掉仪器 3 个缺陷**（编号接 33 号台账）：#19 非法 JSON 转义（`\evidence`、`\*` 让整轮 11 条判定白扔）、#20 `max_tokens` 截断数组（Qwen 写到一半就断）、#21 **判定单元漂移**。`_fix_escapes` 第一版还错了一次（没成对吞 `\\`），已修并写进注释——"修工具的工具也会错"。
5. `external_review.py` 新增 `--model` / `--evidence`，记录里多挂 `evidence_pack` 与 `item_count_before_repair`：**换个模型、换个证据包，读数就不可比，必须能从记录里看出来。**


## v0.4.29 改了什么

- **补件包按根归档（修 #54）**：`handoff_bundle.py --copy-to` 不再吐出 `files/upper/upper/upper/...`，改为 `files/<盘符_根名>/<相对路径>`（如 `files/C_uibc-实测台`、`files/D_Workbuddy`、`files/misc`），`ROOTS.txt` 直接列出复跑要传的每一条 root。**补件包从此可以照着 ROOTS.txt 抄一遍就跑，不用猜。**
- **目录型引用一律整树存证**：不再把 `uibc-实测台\` 整棵 145 MB / `dist\` 99 MB 算进 required，改为 `hash_only` 并在清单里写明实际体量。required 稳定在 **63 条 / 2.38 MB**。
- **实测第二轮（新补件包）**：干净目录 `RED`，`缺少 129 / 硬伤 112`——与旧布局同值，**说明剩下的 112 不是补件布局问题，是 hash_only（旧分发物 + 目录树）没随包**，这一条只能靠口径决定。

## v0.4.28 改了什么

- **拿两个交付包在干净目录里从零解包复跑**（外人视角）：`verdict=RED`，`refs=568 / 缺失 174 / 硬伤 150`。**这不是包坏了，是审计的解析根集合一直只在作者机上**（审查目录 + 测试台 + `D:\Workbuddy`），交付物没声明它。
- **新工具 `tools/handoff_bundle.py`**：吃 `package_audit.py` 的 JSON，把每条本地引用按「有没有随包」重新分类——`covered_docs 436 / covered_kit 71 / required 107（75.50 MB）/ hash_only 54 / nonexistent 15`，并可 `--copy-to` 物化成补件目录。**首版把整棵树算进体积（22 GB）、把 `.git` 对象也跟着拷**，已修：目录统计跳过 `.git`、复制时按 `ignore_patterns` 排掉 `.git/*.pack/*.idx/*.rev`。
- **结论（写进 52 号）**：要让外人跑到同色绿，必须「两包 + required 补件（75.5 MB）」同时到位；只给两包，必红。历史分发物（旧 bundle/zip）按 `hash_only` 存证、不随包——**这一条是取舍，需要拍板，不是我能替定的。**
- 缺陷 **#51**（51 号"外人复跑两条命令"隐含作者机根集合，说过头，已在 51 号划掉并更正）／**#52**（handoff 工具首版目录边界与 `.git` 复制失控）／**#53**（`os.path.relpath` 跨盘符抛 `ValueError`、`copytree` 撞 `Errno 13`，已各自兜住）。

## v0.4.27 改了什么

- **九门×机器可判成分矩阵**：`tools/nine_gates_matrix.py` 逐门输出「机器判据+读数」与「必须人判的部分」，`nine_gates_matrix.json/.md`。本轮 **PASS 3（S4/S7/S8）/ 部分 6 / BLOCKED 1（S1）**。
- **核心结论写进文档**：十门里**没有一门是机器全判**；机器判不了五类信息（修订号 / 授权 / 漏检判断 / 专家 / 外人认可）。硬凑成 PASS 就是九种伪绿里的"自演式绿"。
- **证据债清理**：外链 DEAD 1 = `identity.foundation/universal-resolver/`（2026-11-24 复验 404），三处引用就地标"仅作历史引用"，改用现行端点。
- 缺陷 **#48**（工具把中文引号混进 Python 字符串连挂三次；**纪律：Python 字符串内一律用「」**）／**#49**（死链当网络抖动、未当证据债）。

## v0.4.26 改了什么

- **总闸 `tools/gate_all.py`**：一条命令跑 G1 分档 / G2 标注门禁 / G3 包内审计 / G4 不主张 / G5 版本一致，输出 scorecard，**退出码 0=可发、1=有红**；判据与颜色写死在代码里，不许临场放宽。
- **首跑 2 红 1 黄，三处全是我判据错**：读不存在的字段（`hard_errors`→-1）、把 `HIT/SOFT` 混进 HARD（43 vs 25）、把标准草案副本算成我方主张。**先查闸，再查包。**
- **修完 GREEN**：`refs=519 / 可核实 118 / 可追溯 211 / 多义 112 / 真缺件 11`；`checked=21 违规 0`；包审计 625 条 / 缺失 13 / **硬伤 0**。
- **G4 载体分类 + 人工裁定留痕**：corpus 19 / quote 3 / 待判 0；`g4_verdicts.json` 须写 verdict/why/date/裁定人，**不写理由不生效**。
- 缺陷 **#44**（字段名错）/ **#45**（SOFT 算进 HARD）/ **#46**（草案副本纳入范围错）。

## v0.4.25 改了什么

- **不可核标注门禁落地**：新增 `tools/unverifiable_label.py`——missing / otherhost / extpath 三类引用必须在**前后各 120 字**内写原因，否则违规；判绿= `violations=0`，**判红只许改文档，不许放宽门禁**。
- **门禁首跑 15 条红，12 条是我判据错**：`/.well-known/did.json` 被当"他机文件"，其实是本机 URL 路径 → 分档器加 `urlpath` 类（只认 `/home /root /tmp /var /etc /usr /opt /mnt /srv`）。**先怀疑判据，再怀疑文档。**
- **改完 0 违规**：`refs=493 / verified 115 / traceable 205 / glob 17 / ambiguous 111 / otherhost 2 / urlpath 6 / extpath 4 / quote 26 / missing 7`；门禁 `checked=13 violations=0`。
- **标准 v2.1 草案副本**（`00_发布前审查标准_v2.1草案_20261124.md`）：S5 的 `MISSING=0` 作废 → 改"引用错误=0 + 不可核须标原因 + 门禁违规=0"；新增 S6·补·证据可核性门禁；附录 A 七类。**原件 6,472 B 未动，改标准待批。**
- 缺陷 **#41**（门禁首跑把 URL 路径判成他机，已修规则）／**#42**（门禁窗口只看引用之后，标注写在前面被判红，已改对称）／**#43**（otherhost 8→2 被误读成整改成果，实为分类修正，已在文档写明）。

## v0.4.24 改了什么

- **先更正自己**：46 号"39 条补路径即可"说过头了（缺陷 #38）。实测只有 12 处能靠改写法升级，其余是运行时产物 / 远端清单 / 命令引文。**46 号原文划掉并注明更正，不删旧句。**
- **分档器 v2（七类）**：`tools/evidence_grades.py` 拆成 可核实 / 可追溯 / 通配命中 / 多义待消歧 / 他机 / 外仓 / 引文跳过 / 真缺件。全包 **486 条 → 可核实 114 / 可追溯 200 / 通配 16 / 多义 111 / 他机 8 / 外仓 6 / 引文 24 / 真缺件 7**。
- **12 处引用改成能核的写法**（`dist\_fix_refs_v0424.py`，逐条校验次数 12/12）：AITB 四件补全路径；36 号 `preflight_*` 实名带日期前缀（**原文真写错**）；10/12 号环境指纹"待做"实为已做（**状态过时**）；00/30 号 resolvers 补 `34_竞品证据\` 前缀。
- **真缺件 7 条只标注不美化**：「did.json」×2 / 「s0x_results.json」×3 / 「weknora_sync_state.json」×2——运行时产物或本机不存在的台账，**写成可追溯就是造假**。
- **两个结构性约定**：通配必须带目录约束（否则 `tools/*.json` 假命中 19,659 个）；**举名讨论不加反引号**（否则文档讨论缺件会把自己算成缺件，47 号自身一度让 missing 从 9 涨到 16）。
- 缺陷 **#38**（说过头已更正）／**#39**（分类粗已拆七类）／**#40**（自指膨胀已立写法约定）。S5 据此改判"部分"（6 过 / 2 部分 / 2 阻塞）。

## v0.4.23 改了什么

- **全组基线当场重跑**：`bench.py run --tag v0423_full`，11 组 → 与基线比对 **141/141 一致、0 回归、0 变化、0 新增、0 消失**；`run.log` 进 `defect_logs` 带 sha256。
- **三档工具落地**：`tools/evidence_grades.py`；全包 **422 条 → 93 可核实 / 280 可追溯 / 39 待补路径 / 8 他机 / 2 片段**。
- **S4 四轮双厂商 + 仲裁原则**：DS 3 轮"部分核实"、1 轮"夸大"；QW 3 轮"夸大"。日志在包内 verified → 立 **物证优先**：机器能核到件以机器为准，模型"未提供"降级为读取提示。S4 判"合格（部分可复跑 3/6）"。
- 缺陷 **#35**（自我贬低反被当缺口，已改）／**#36**（分档器误抓 URL 与日志引文，已修）／**#37**（读不到件被记成文档缺陷，已立原则）。

## v0.4.22 改了什么

- **逐条复跑日志**：`tools/defect_relog.py`，6 条检查 3 条真跑（端口自愈 / 版本漂移 / 清单强制覆盖）、3 条 `NOT_RERUN` 带理由；每条 `.log` 与 `index.json` 均带 sha256。
- **S4 八轮来首次松动**：pack v6 含日志后 DS 判"部分核实"，**QW 仍判"夸大"** → 按取交集规则 S4 仍红，不判合格。
- **十处跨厂商分歧归因**：9 处同一根因（原件在包内 vs 文档指认），1 处反向；引用文件逐个核对存在。
- **判据三档草案**（可核实 / 可追溯 / 夸大）+ 标准 S6 行补丁 diff：只写草案，标准原文未动。
- 仪器缺陷 #32（跨厂商非对称）/ #33（`NOT_RERUN` 口径）/ #34（分档缺失）。

## v0.4.21 改了什么

- **缺陷台账独立成件**：`tools/defects_ledger.py` 从看板抽出 `defects_ledger.md`（7 条主台账 A–G 逐字搬运 + 7 条编号缺陷），**未逐字核到的 11 个编号如实列出、不编条目**。
- **措辞扰动机器化**：`tools/phrase_perturb.py`，14 条保守同义规则，含数字/哈希/文件名/门标签/判定词的行整行不动；本轮 38 号扰动 17/167 行、27 处，守卫跳过 23 行，两份 sha256 留痕。结果 **门级 1.00、条级 0.97**（门级口径会掩盖 3 条翻转）。
- **跨厂商全文级补齐**：`external_review.py` 新增 `--max-tokens`；Qwen 8k 只出 72/94（作废），16k 下 **94/94 全覆盖**，判 **9 门可核实**（DS 6 门）。**门级一致率 0.70、条级 0.89**；唯一两家同判红色仍是 **S4=夸大**。
- **S4 补台账后仍判"夸大"**：机器要的是逐条复跑日志，台账不够。**证据形式换了、结论没动。**
- 规格 v4 补**第 7 条**（门级 + 条级两级一致率并列、条级 <0.90 门级不得单报、同结论至少两轮取交集、跨厂商 <0.90 的门不得机判 → pack v5 下可机判 7 门）；仪器缺陷 **#28–#30**。

## v0.4.20 改了什么

- **全文级复核跑通**：`claim_inventory.py` 不再只切表格，给每条断言带 `section`（所在小节）与 `gate`（`S[0-9]`），一级标题不作小节；38 号切出 **94 条**（表 48 / 正文 46，可归门 56）。新增 `claim_gates.py` 把断言级判定归到门级（最不利优先），出每门覆盖率、判定分布、跨轮/跨厂商一致率。
- **同包同措辞重复一致率 1.00，措辞一改就回退**：换证据包（`evidence_pack.py` 新增 `path::关键词` 切片，HTML 切片先剥标签，把看板缺陷台账变成纯文本）后 S2/S5 各升一门（一致率 0.80）；**仅改一句措辞，S2/S5 双跌回，10 门读数与旧包完全相同**（一致率又 0.80）。→ 规格 v4 补第 6 条"措辞扰动"：同义改写后一致率 ≥0.90 才可机判，否则该门不得机判；多轮读数必须全部列出，禁挑绿读数。
- **修掉两处真错误**：① 38 号"变异 M0–M4 4/4"实为 **M1–M4 4/4（M0 是对照，本就不该被杀）**；② §十 S4 证据行原指 `33_规范追踪矩阵与绑定层探针.md`（该文件并无缺陷台账）→ 改指看板 `defects` 视图。
- **S4 仍判"夸大"，不硬翻绿**：四轮 DS + 一轮 QW 同判，理由始终是"未提供逐条缺陷复跑日志"。台账每条写了验证动作但不附独立日志文件，这是真缺口 → 转人工复核项。
- 仪器缺陷 **#25 判定对措辞敏感且未度量（入规格）／#26 HTML 切片带标签（已修）／#27 解析条数多于清单（`coverage.extra` 单列）**。

## v0.4.19 改了什么（2026-11-23 24:0x）

上一轮说"6 门可机判"。这一轮先问了一句更狠的：**它到底在审全文，还是只审那张表？**

1. **断言清单** `tools/claim_inventory.py`：把正文切成 90–120 条编号断言（表格行、正文句、标题里的主张都算），`--must <关键串…>` 用来保证"该测的那句真的在清单里，缺一即 FAIL"。不这么干，"逐句质疑"在提示词里写了等于没写。
2. **灵敏度变异** `tools/review_mutation.py`：M0（不动）作对照，M5/M6/M7 分别注入"已由外部专家签字""已由信通院复核确认""两家模型确认十门全过 + 断崖式领先"。产物只落 `runs/`，首行写死 MUTANT，**不进审查包**；原件 SHA-256 跑前跑后比对。
3. **测出来**：
   - 旧问法（无清单）：**0/3** 判"不实/夸大"——M6/M7 两句**根本没进视野**（清单 60 条截断、标题整类跳过），M5 被按"无法核实"放过。
   - 强制覆盖（96/96、97/97 覆盖率）：**3/3 判"夸大"**，理由正是"缺少签字报告/复核函/模型确认证据"。
   - 对照 M0：96 条里 4 条夸大；注入一条后 5 条，第 5 条是注入句 → **增量可归因**。
4. **结论**：过去七轮的"可核实率"分母是十门表，不是全文。**规格 v4**在此基础上加两条：必须回 id、覆盖率 <95% 视为"没审完"；每份外发文档都要过 M0 对照。
5. **修掉仪器 #22–#24**：清单静默截断（默认 `--max 0`，并报 `candidates`/`truncated`）、标题里的主张被跳过（含断言词的标题当断言收）、超时 180 s 不够（96 条断言 150–220 s，改 300 s）。

## v0.4.30 改了什么

本轮不改任何文档文案，把「交付件要不要随包」这件事从人工口径变成机器规则。

- 新增 `tools/hash_manifest.py`：扫 `--roots` 下 `dist;runs` 两个子目录，产出 `handoff_hash_manifest.json`（逐文件 sha256 + 每棵子树 tree_sha256）。实测 3200 个文件 / 124.43 MB。
- `tools/package_audit.py` 增 `--hash-manifest`：缺失引用若 basename 命中清单，或路径尾部命中子树名，状态记 `HASHDECL`（按哈希存证），单列不入 MISSING；summary 增 `local_hashdecl`。
- `tools/gate_all.py` 增 `--hash-manifest`，默认读 `<dir>/51_收尾证据/handoff_hash_manifest.json`；G3 明细多一列「哈希存证」。
- 作者机上该值恒为 0（本地本来就不缺件），它的作用面是「拿到包、但没有 dist/runs 的读者」：这些人能凭清单核对字节，而不再得到一片红。

## v0.4.31 改了什么

把「件不在包内」的六种情形全部机器化，让外人侧与作者侧用同一条命令得到同一结论。

- 哈希存证扩容：清单覆盖面从 `dist;runs` 扩到「测试台整根 + 发布前审查原件目录 + AITB 台」，7098 件 / 161.01 MB；并新增 `dirs[]`，目录引用也能对号。
- `tools/package_audit.py` 增五类：`PATTERN`（`*`/`?`/裸扩展名等占位写法）、`SELF`（包自身文件名）、`TRIMMED`（精简包剔除、全量包内含）、`EXTERNAL`（包外工作区/绝对路径，须文档标未随包）、`HASHDECL`（按哈希存证）。
- `tools/evidence_grades.py` 增 `--hash-manifest`：件不随包但可按 SHA256 核对的引用记 `hashdecl`，不再算「不可核」；包自身文件名记 `selfref`。
- `tools/gate_all.py`：G1/G3 透传清单；`--external` 默认带五条包外清单；G1 明细多一列「按哈希存证」。
- 实测三种读者的读数（同一批交付物）：作者机 GREEN 5/5；干净目录（只有含清单的包，没有 dist/runs）GREEN 5/5，G1 按哈希存证 162 条；此前同一干净目录为 RED、硬伤 150 条。

## v0.4.32 改了什么

- 把误提交进仓库的 `.venv312/`（724 个文件）从跟踪里移除，`.gitignore` 补 `.venv312/`（缺陷 #59：`.gitignore` 只写了 `.venv/`，漏了带版本号的那个）。
- 历史里仍能看到这批 venv 文件，**不做改写**：一旦重写历史，文档里引用的 `7338bca / 238fad3 / 0eb58bc` 全部失效，那才是真把证据链弄断。

## v0.4.33 改了什么

- 给「下一个接手的人或 Agent」补了三块料：`AGENTS.md`（三十秒定位 + 先读哪几件 + 怎么积累 + 硬约束）、`SECURITY_AND_ROLES.md`（三身份权限边界，评测号不进 UIBC 组织）、`CHANGELOG.md`（从 0.4.27 起的版本线）
- 公开仓 `UIBC/uibc-bench` 上线，可被其他账号与会话直接克隆使用；公开的是快照，完整历史仍在本地 bundle
