# CHANGELOG

每一行对应一个 tag，格式：版本 / 日期 / 一行改动 / 证据在哪。
**没有复跑日志的「修好了」不进这张表。**

## 未发布 — 2026-11-25（新增 J 组：did:bid 解析协议契约）

- **新组 `s11_bid_protocol.py`（J 组，54 条用例）**：从外部调用被测仓的 `uibc_core.bid_protocol`，按《星火·链网BID协议》逐条判：§4.2.5 的 11 档响应码是否分级且只有 3/7 可重试、"没找到"与"验签失败"是否被区分、§4.2.1 文档的 13 条非法形状是否真的被拒、§5 签名自签自验与三种键编码（64/66/70）、§4.2.3 子链两跳与成环检测、§4.2.2 五个字段端点的形状不对称（全部=数组 / 单键=对象）、以及官方 SDK 地址的性质夹具（50 条批量，见下条 J7 口径更正）。
- **跨语言不看运气**：J4 直接 `node tools/verify-js/bid.mjs` 跑被测仓的独立实现，要求 `signature-verified true` 且两侧规范化字节 sha256 逐字相同；没装 node 记 SKIP，不记 PASS。
- **J7 改口径：地址能校验，不能反推**。原 J7.1 断言"协议规则复算 == 官方 SDK 地址"，只有一个样本支撑。改成吃 50 条批量夹具后，Bitcoin 字母表复算只有 7/50 一致（SDK 的 base58 编解码不是 Bitcoin 那一套），于是 J7 拆成三条：J7.1 官方产出的 50 条地址是否全部被被测仓接受并判成主链/Ed25519/base58（这是解析器真正需要的性质）、J7.2 suffix 是否落在协议 `(22,42)(ALPHA/DIGIT)` 且键/地址互不重复、J7.3 复算一致数记 **INFO**（7/50）而不是 FAIL——它是官方 SDK 的性质，不是被测仓的缺陷。夹具缺失时退回单样本，并把"单样本不足以支撑复算主张"写成 INFO。
- **新增 J8 §4.2.4 可信解析（11 条）**：这一组的立场是"解析服务不可信"。J8.1 请求必须真的是 `{url}/{bid}?verify=true`；J8.3 是本组的核心——解析服务自述 `verify=true`、但文档签名后被动过，必须判**不信**；J8.4 `"true"` 字符串必须被拒（协议写的是 Bool）；J8.5 `verify=false` 是答案不是异常；J8.6–J8.8 `extension.delegateSign` 三态：取不到签名者公钥记 `unchecked` 且不冒充全信、给出公钥能验、给错公钥判 `invalid` 并整体不信任；**J8.9 直接 `python tools/demo_bid_trusted.py` 跑被测仓的 demo**（起真 HTTP 服务），退出码非 0 即 FAIL，没提供则 SKIP。
- **新增 J3.4 SM2（2 条）**：协议 §5 允许 Ed25519 与 SM2，此前只测 Ed25519。用国标 GM/T 0003.5 附录 A 的例题（dA、PA、ZA、e、k、r、s）在被测仓里构造 SM2 文档，要求**验得过**、签名后改动一处必须**被拒**，且成功理由要写明所用区分标识——否则"验过了"没有限定条件。被测仓无 `uibc_core.sm2` 记 SKIP 不记 PASS。
- **新增 J10 地址推导（5 条）**：被测仓上一版写"地址只能校验、不能反推"。这一组从外部要求它把官方 SDK 的 **50 条**地址逐字节复算出来，并要求它把两个变体分开（RFC-003 的版本字节 vs SDK 的省略），还要能自证"两张字母表只差 4 个大小写位置"。被测仓没有 `uibc_core.bid_address` 或没有夹具时记 SKIP，不记 PASS。
- **新增 J11 二进制编解码（7 条）**：被测仓上一版只能解码 §4.3，而"我们实现了二进制协议"在只有解码器时无法被反驳。J11 要求被测仓自己产出字节：单元层逐字节往返（故意给非升序，排序实现会在这里露馅）、报文层头+option+体往返、flag 位序必须真是参数（翻转后读法必须不同）、`integer_widths` 与载荷长度不符必须 raise 而不是读成错数、不存在的字段路径不许自造 unit ID、500 组随机字节只允许 ValueError、六条推断都登记了缺口与处置。被测仓无 `encode_units`/`ASSUMPTIONS` 时 SKIP 不记 PASS。
- **新增 J12 demo 与生成式图（3 条）**：测试能自洽，却可能对外人什么都没说明。J12 要求被测仓给出两件东西：一个跑得起来并自报 `ALL OK` 的 demo（`tools/demo_bid_binary.py`，退出码非 0 即 FAIL），以及一张**由模块常量生成**的布局图（`tools/render_bid_binary_layout.py --stdout` 与仓库里的 `docs/BID-BINARY-LAYOUT.svg` 必须逐字节相同——手绘的图会随代码失真，失真的图比没有图更糟）。缺 demo 记 SKIP 不记 PASS。
- **新增 J13 逐位翻转与容器归属（7 条）**：J11 只证明"能反算"，J13 追问"每一位都有反应吗"。J13.1 直接 `python tools/mutate_bid_binary.py --json` 跑被测仓探针；J13.2 拒绝+改变+盲三类之和必须等于 `message_bytes*8`（不许有漏判的位）；J13.3 盲位集合必须**恰好**等于头部保留位，期望值从被测仓的 `_FLAG_BITS`/`_OPCODE_SHIFT` 推出来而不是抄报告里的数；J13.4 报文正文一位都不许盲；J13.5 把 `publicKey`(0x2110) 换成文档包装层 0x2100 必须被拒（这类结构改写以前解出来一模一样）；J13.6 宽容读法 `strict_placement=False` 要把错位记进 `misplaced` 而不是丢字段；J13.7 文档写的 196 字节必须等于实际产出的字节数。同时把 J11.4 收紧：只要求"raise"会被容器错误冒充过关，现在必须看到 `declared … but carries …`。
- 本轮 J 组由 54 条增至 71 条（J1–J13）。
- 本地重跑：**PASS=69、INFO=2**（71 条）。


- **J9 向量集外部复跑**：被测仓自带 22 条向量，这一组不读那些用例的代码，只跑它的核对器（`tools/check_bid_vectors.py`），要求退出码 0 且输出 `22/22 passed`——把"我们自己说全过"换成"外人照命令跑也全过"。
- 全组口径随之 11 → 12（README、QUICKSTART 同步）。

## v0.4.44 — 2026-11-25

主题：**把 I 组最后两条 BLOCKED 换成实测**。v0.4.43 把这两条记成 BLOCKED，理由是"缺一个公网
did:web 目标"。这一版把那个前置真的找到并接上——不是补一条用例，是补上被测对象本身。

- **前置换成第三方已发布的公网身份**：`did:web:identity.foundation`、`did:web:veramo.io`、
  `did:web:danubetech.com`。三条都由别的主体发布、不由我们托管，因此不存在"自己出题自己判"；
  真实 HTTPS 抓取，**不注入 fetcher、不用回环伪造**。自建一条公网 did:web 也能让这两条变绿，
  但那测的是"我们能不能解析自己刚发的文件"，没有互操作含义。
- **判定口径**：`I2 我方取公钥` 要同时满足两条——文档 `id` 与请求的 DID 逐字相同、至少一个
  `verificationMethod` 带公钥材料；`I4 两实现逐字段比对` 比 `id` / `verificationMethod` 清单
  （id、type、controller、公钥规范化值）/ `authentication`。两边各自当次抓取；**出现不一致时先让两边
  重抓一次再判**，避免发布方在两次抓取之间轮换密钥把台子打成假红。
- **公钥规范化必须两边逐字同构**：`mb:` / `jwk:` / `hex:` / `b58:` / `pem:` 前缀 + 稳定序列化
  （JWK 按键排序、紧凑分隔符）。不做这一步，"同一把钥匙写成 JWK 和写成 multibase"会被读成"不一致"。
  Python 侧 `_keyref()`、JS 侧 `keyref()` 同构，改动任何一侧都要同步另一侧。
- **代价写在明处**：I2/I4 需要出网（443）。没有出网的环境下这两条记 `BLOCKED` 并写明
  "三条公网 did:web 一条也没取到"，**不改成 PASS 也不改成 FAIL**——缺的是连通性，不是被测仓的能力。
  台子其余组仍不需要网络。单条目标偶发读超时（本机实测 identity.foundation 出现过一次）时，
  该条计入"未取到"，其余目标照常判定。
- **复验（本机，被测仓 0.5.3）**：I 组 `8 PASS + 1 INFO`、BLOCKED 归零；`I2` 取到 3 条、4.5s；
  `I4` 三条逐字段一致。此前 I 组是 `PASS=6 BLOCKED=2`。

## v0.4.43 — 2026-11-25

主题：**把"被测仓变了"这件事从红变回可读**。v0.4.42 修了出处（测的是哪棵树），这一版修的是
前提（那棵树还认不认同这些用例）——并顺手把"跨实现"三个字从 BLOCKED 变成实测。

- **I 组重设（改判据，逐条说明）**：被测仓把 `did:web` 主机策略搬进解析契约（回环/私网一律拒）。
  旧 `I1 我方解析 did:web` 拿**注入 fetcher** 去解析 `127.0.0.1`、判 PASS —— 那个期望本身是错的：
  它等于要求实现允许指向内网的解析。这一版拆成：
  `I1 注入 fetcher 也拒回环`（PASS 条件=抛 `not a public address`，正好把 11-25 的修复钉住）、
  `I1b 真实传输同样拒`、`I2 我方取公钥`→BLOCKED（缺前置：公网 did:web 目标，不拿注入 fetcher 绕策略伪造）、
  `I4 两实现逐字段比对`→BLOCKED（我方无文档可比）、`I4b 策略分歧按设计发生`（机器证明"我方拒、第三方解"）。
- **跨实现终于真跑了**：`tools/interop` 里钉死的 uport/Veramo 生态 `did-resolver 6.0.0 + web-did-resolver 3.2.0`
  以前只在文档里"准备跑"，CI 与本地都是 BLOCKED。现在 `npm i` 进流水线并导出 `UIBC_INTEROP_DIR`；
  本机实测 `I3 第三方解析 did:web` PASS（127ms，id/vm/公钥与本地宿主一致）、`I5`/`I6` 两边都拒、
  `I4b` 分歧按设计发生。BLOCKED 从 4 条降到 2 条，且剩下的 2 条各自写明了缺什么。
- **同一类缺陷清底**：`s06`/`s08`/`s09`/`s10` 还在硬写/半硬写 `uibc-core-public`，`UIBC_SUBJECT` 对它们无效
  —— 与 v0.4.42 修的 `s02/s02b` 是同一个病。四组统一改走 `_subject.resolve()`。
- **跨盘 Windows 的假失败**：本机 bench 在 `F:`、系统 TEMP 在 `C:` 时，被测仓 `test_crosswalk_probe.py`
  用 `tempfile` 造文件再与被测仓算相对路径，`ntpath.relpath` 跨盘直接 `ValueError: path is on mount`，
  7 条用例全红。实测修法：子进程的 `TEMP/TMP/TMPDIR` 钉到被测仓所在盘。同一台机器同一提交：
  **7 FAIL → 2 FAIL**，剩下的 2 条是本机沙箱无法 fork `git`（`WinError 2`），CI 上不出现。
- **基线按被测仓 `dcaa37c` 重录**：这次不是"让结果变绿"，是三条前提作废后必须重设期望——
  哪些用例换了名字、哪些从 PASS 变 BLOCKED、哪些是新出现的，全部在本次提交的 `retired` 段与上面逐条写明。
- 复验：本机全量 `--only s04` 见上；`--only s09` 见上；CI 见 PR（双平台 `--quick` 对照新基线）。
- **基线随后重钉到被测仓当前 main `72b14f3`**：`dcaa37c` 录完之后被测仓又进了 8 个提交
  （conformance 0.5.1–0.5.3、verify-js 两条修正、版本门），台子再钉着 `dcaa37c` 就是在测一个没人发布的提交。
  重钉后双平台全量（run `45519960667`）：linux `149 条 · 一致 149 · 回归 0 · 变化 0`，Windows
  `153 条 · 一致 147 · 新增 6 · 消失 0`（6 条是 Windows 专属，已登记在 `baseline/windows.json` 的 `windows_only`）——
  **8 个提交之后判定逐条不变**，所以用例不必重录，只把 `subject_head` 与 `source_run` 指到这次实测。

## v0.4.42 — 2026-11-25

主题：**被测仓出处必须是可证的，不是我口头的**。起因是 s02 组在三台机器上给出三种结论，
而代码一行没差——查下去发现差的是"`import uibc_core` 到底导进来哪棵树"。

- **真缺陷**：`s02` / `s02b` 自己硬写 `sys.path.insert(0, ../uibc-core-public)`，没有走 `_subject`。
  当那个目录不存在时，这一行等于没写，`import uibc_core` 就落到解释器里已安装的那份——
  这台机器上是一个 editable 安装，指向 `D:\wt-acps-subj\x\uibc-core-main`。于是
  `python harness/s02b...py` 会对着**没被要求测的那棵树**出结论，且不吭声：同一组用例、
  两台机器、两棵不同的树、两种判定。现场证据：仓根 `s02b_results.json`（22:34）三条全 FAIL，
  同时 `runs/20261125_000450/` 同样的用例 PASS/INFO——差别只在导进来的那份 `uibc_core`。
- **修法**：两组改走 `_subject.load()`。它先按 `UIBC_SUBJECT` → 仓内 `uibc-core-public` 定位，
  定位不到就 `BLOCKED` 并给三条设置路径，**不再回落到解释器里已安装的包**；定位到了还会核对
  `uibc_core.__file__` 是否落在该树内，对不上直接拒绝出结论（`WrongSubjectImported`）。
- **存证层**：每组结果旁多一份 `<组名>_results.subject.json`（被测仓路径、实际的 `uibc_core` 文件、
  解释器、`UIBC_SUBJECT` 取值），并写进 `ATTEST.json` 的 `subject_provenance`。
  旁证指向的仓与 `run.py` 指定的仓不一致时，`subject_provenance_mismatch` 单独列出——
  这条就是为了让"测错树"变成一份能被第三方看见的产物，而不是一句解释。
  旁证写成旁挂文件而不塞进 results 列表：用例清单必须正好等于本组断言的东西，baseline 才有意义。
- **复验**（Windows，`python run.py --only s02,s02b --no-baseline --attest --subject D:\wt-acps-subj\x\uibc-core-main`）：
  `PASS=14`、exit 0、`ATTEST.md` 打出 `s02←…\uibc_core\did.py, s02b←…\uibc_core\did.py`、出处告警"无"；
  无被测仓时两组均记 `BLOCKED`（含三条设置指引），不再静默导入；人为把旁证改到别的树，
  `mismatch` 立刻报 `s02b：import 到 …\uibc-core-OTHER\…，不在指定仓 …`。
- **证据**：`runs/20261125_smoke/`（`*.subject.json`、`ATTEST.json` 的 `subject_provenance` 段）
- **顺手堵的一个更贵的坑**：流水线原来是 `git clone --depth 1 …/uibc-core` 取 HEAD，等于拿"今天的被测仓"
  去比"昨天的基线"，被测仓一合改动这边就多一条"回归"。本次就当场发生了：被测仓合入
  `did:web` 主机策略（拒绝回环）后，`I1 我方解析 did:web` 从 PASS 翻 FAIL、`B1'`/`B3'`/`B5'` 反向翻好，
  台子被判 exit 1——红的理由完全不在台子上。现在 `baseline.json` 记 `subject_head`（完整 40 位提交号，
  不是缩写——缩写 git 拉不到，第一版就是这么红的；也就是上一轮双平台全绿时测的那棵树 `25962f1`），
  流水线按它钉住克隆；被测仓 main 领先多少单独打一行进
  job summary，**不判红**。基线老了是"该重录基线"的信号，重录等于改判据，必须单独一次提交并在本表写明。
  顺带说明：`I1` 翻 FAIL 不是被测仓的 bug，是这条用例的前提（本地回环可解析）被它自己的策略作废了，
  重录基线时要连用例一起重设，不能把它记成"已知回归"糊过去。

## v0.4.41 — 2026-11-25

第一次真的把这条流水线交给 GitHub 的双平台 runner，就抓出三个"只在我这台机器上成立"的假设：

- **编码**：windows-latest 的控制台是 cp1252，`run.py` 打的一行 `◀` 直接 `UnicodeEncodeError`，job exit 1。
  本机 cp936 编得出来，所以从来没暴露。现在 `run.py` 起手把 stdout/stderr 重设为 UTF-8（`errors="replace"`），
  子进程也注入 `PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8`，workflow 再钉一层同名环境变量。
- **备料**：被测仓的验证路径要 `cryptography`（`[verify]` extra），CI 没装，B0 组全 BLOCKED、
  s01 平白多出 7 条 FAIL。workflow 增加 `pip install "./uibc-core-public[verify]"`；QUICKSTART 增 §1.5 写清这一步。
- **性能判据不能跨宿主**：`F1` 的 300ms 阈值在家宽成立、在共享 runner 上必然误报（实测 P50≈950ms）。
  设了 `CI` 且没给 `UIB_PROFILE` 时，`F1` 三项只测量、记 `REFERENCE`，不参与判据；要判性能就在目标网络里指定档位。

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
