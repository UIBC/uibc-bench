# 官方 W3C DID Resolution Test Suite：怎么复跑

本目录只提供"接入件"，套件本体不随包分发（它是 W3C 的仓库，不能拷进我们的包）。

## 一条链路

```
官方套件 (w3c/did-resolution-test-suite, mocha)
   │  GET https://127.0.0.1:9443/1.0/identifiers/<did>
   ▼
tools/resolver_https_shim.py   ← 只做协议适配：Accept / 媒体类型 / 错误对象 / 状态码
   │  直接调库函数
   ▼
uibc-core-public/uibc_core/did.py::resolve   ← 被测对象，零改动
```

shim 不缓存、不改写、不补字段；它存在的唯一理由是官方套件只认 HTTPS endpoint，
而被测实现是库函数。任何"补"出来的字段都会让这一层变成第二个被测对象，所以不做。

## 复跑步骤（Linux/macOS，需 node ≥ 22 与 npm）

```sh
git clone --depth 1 https://github.com/w3c/did-resolution-test-suite.git /tmp/wst
cd /tmp/wst && npm i            # 依赖含 github: 包，需能访问 github

# 起我方 endpoint（另开一个终端，在测试台根目录）
python tools/resolver_https_shim.py --port 9443 --cert _pki/cert.pem --key _pki/key.pem

# 把我方登记为被测解析器（只在本机套件副本里加，不提交 PR）
cp <测试台>/tools/official_suite/UIBC-selftest.json resolvers/

# 只跑我方，避免撞别人的限流
mkdir -p /tmp/other && mv resolvers/*.json /tmp/other/ && cp /tmp/other/UIBC-selftest.json resolvers/
NODE_TLS_REJECT_UNAUTHORIZED=0 npx mocha tests/4-did-resolution.js --timeout 15000
NODE_TLS_REJECT_UNAUTHORIZED=0 npx mocha tests/10-bindings.js     --timeout 15000
```

`NODE_TLS_REJECT_UNAUTHORIZED=0` 是因为 127.0.0.1 上只有自签证书；这条只影响本机回环，
换成有正式证书的 endpoint 就不需要。

## 已知结果（2026-11-23，云主机 Ubuntu / node 22.23.4 / 套件 commit 4b5a62e）

- `4-did-resolution`：10 通过 / 5 失败
- `10-bindings`：4 通过 / 6 失败
- 11 条失败**同源**：WG 共享测试集里唯一那条 `did:key` 是 P-521 键（multicodec `0x1202`），
  而 `uibc_core.did` 的 did:key 只实现 ed25519-pub（`0xed01`）→ 一律判 NOT_FOUND。
  错误条件类用例（坏 DID 400、不支持方法 501、error 对象结构、空 metadata）全部通过。

结论口径：**不是"通过官方套件"**，是"官方套件已实跑，错误路径符合，成功路径受 did:key 键型覆盖所限"。
