# 被测对象（本测试台所测的仓）

| 项 | 值 |
|---|---|
| 仓 | `https://github.com/zhaoxinghua09-cell/uibc-core` |
| 冻结基线 | `baseline.json` 141 条（82 PASS / 13 FAIL / 5 WARN / 36 INCOMPLETE / 5 SKIP） |
| 基线 SHA256 | `C93A25F545E148B9D6E5688D5D83C66BE9D864818E18459E1E768DE9D6F08272` |
| 本轮复查时的远端 HEAD | `990c96a9d520`（2026-11-23 23:00，#398） |

## 为什么被测仓仍在个人账号下

被测仓 `uibc-core` 目前挂在 `zhaoxinghua09-cell/uibc-core`。把它转进 UIBC 组织属于**所有权变更**，会改 URL，
已有文档与外部复现记录都按旧 URL 引用，改了会让引用失效。所以这一步等所有者拍板，本仓不擅自做。

本仓（`UIBC/uibc-bench`）是测试台本身，与"被测对象"分开：**仪器和被测物不放在同一个账号名下**，
是本项目的独立评测前提。

## 复跑要准备什么

```
python bench.py --repo <uibc-core 的本地克隆>        # 跑一遍
python compare_baseline.py --baseline baseline.json  # 与冻结基线对比
```

被测仓的 `evidence/` 目录不在本公开仓内——它属于被测仓，缺它时对应检查项会记 INCOMPLETE，不会判 PASS。
