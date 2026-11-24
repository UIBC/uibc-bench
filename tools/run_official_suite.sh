#!/usr/bin/env bash
# 一条命令跑官方 W3C DID Resolution Test Suite（Linux/macOS）
#
#   bash tools/run_official_suite.sh              # 默认：克隆到 /tmp/wst，端口 9443
#   bash tools/run_official_suite.sh --port 9455   # 换端口（同时占用的机器上跑）
#
# 干什么：克隆官方套件 → npm i → 起本地 HTTPS endpoint（我们的解析器）→
#        只在套件副本里登记我方 resolver → 隔离跑两个用例文件 → 日志落 runs/<时间戳>_official/
# 不干什么：不改 W3C 仓库、不提 PR、不碰其它解析器、不隐藏失败。
set -u
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${2:-9443}"
if [ "${1:-}" = "--port" ]; then PORT="$2"; fi
SUITE="${SUITE_DIR:-/tmp/wst}"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$KIT/runs/${STAMP}_official"
mkdir -p "$OUT"

echo "[1/6] 克隆官方套件（已存在则跳过）"
if [ ! -d "$SUITE" ]; then
  git clone --depth 1 https://github.com/w3c/did-resolution-test-suite.git "$SUITE" || exit 3
fi
SUITE_COMMIT="$(git -C "$SUITE" rev-parse HEAD)"
# 版本钉住：套件会更新，不钉住的话"同一条命令"下周可能跑出不同结果
PIN="${SUITE_COMMIT_PIN:-4b5a62e3019fa4f2e90c9b8c0e59d249b67eac10}"
if [ -n "$PIN" ] && [ "$SUITE_COMMIT" != "$PIN" ]; then
  echo "      HEAD=$SUITE_COMMIT 与钉住版本不同，改为检出 $PIN"
  git -C "$SUITE" fetch --depth 1 origin "$PIN" >"$OUT/git_fetch.log" 2>&1 || { echo "      取不到钉住版本 $PIN，见 $OUT/git_fetch.log"; exit 3; }
  git -C "$SUITE" checkout -q FETCH_HEAD || exit 3
  SUITE_COMMIT="$(git -C "$SUITE" rev-parse HEAD)"
fi
echo "      commit=$SUITE_COMMIT（钉住=$PIN）"

echo "[2/6] 安装套件依赖（需能访问 github，用于 github: 包）"
(cd "$SUITE" && npm i --no-audit --no-fund >"$OUT/npm_i.log" 2>&1) || { echo "      依赖安装失败，见 $OUT/npm_i.log"; exit 4; }

echo "[3/6] 起本地 HTTPS endpoint（自签证书，仅回环）"
# UIBC_SHIM 可指向变体载体（变异测试用：故意改坏载体，看套件是否判红）；默认是正式 shim
SHIM="${UIBC_SHIM:-$KIT/tools/resolver_https_shim.py}"
# 证书自举：包里不带证书（自签证书是一次性的），首次运行就地生成。
# 教训（第11个缺陷）：0.4.9 的 tgz 不含 _pki，新环境直接跑会 shim 崩、冒烟 000，
# 而中止提示只让人看 shim.log，看不出"缺证书"这一层。
if [ ! -f "$KIT/_pki/cert.pem" ] || [ ! -f "$KIT/_pki/key.pem" ]; then
  echo "      首次运行：生成自签证书到 _pki/"
  mkdir -p "$KIT/_pki"
  openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$KIT/_pki/key.pem" -out "$KIT/_pki/cert.pem" -days 3650 \
    -subj "/CN=localhost" >"$OUT/openssl.log" 2>&1 \
    || { echo "[中止] 生成自签证书失败（需要 openssl），见 $OUT/openssl.log"; exit 2; }
fi
echo "      shim=$SHIM"
python3 "$SHIM" --port "$PORT" >"$OUT/shim.log" 2>&1 &
SHIM=$!
trap 'kill $SHIM 2>/dev/null' EXIT
sleep 3
curl -sk --max-time 10 "https://127.0.0.1:$PORT/1.0/identifiers/not-a-did" \
     -H 'Accept: application/did-resolution' -o "$OUT/shim_smoke.json" -w "%{http_code}" >"$OUT/shim_smoke.code" || true
SMOKE_CODE=$(cat "$OUT/shim_smoke.code" 2>/dev/null)
echo "      冒烟状态码=$SMOKE_CODE（应为 400）"
if [ "$SMOKE_CODE" != "400" ]; then
  # 冒烟不过就中止：000 表示 endpoint 根本没起来，继续跑只会产出一份"看起来像基线"的假结果
  echo "      [中止] 冒烟非 400（实际 ${SMOKE_CODE:-空}），endpoint 不可用；见 $OUT/shim.log 与 shim.err（Windows 侧）。不产出任何结果。"
  exit 2
fi

echo "[4/6] 只在套件副本里登记我方 resolver（不提交、不 PR）"
python3 - "$SUITE" "$PORT" <<'PY'
import json, sys, os
suite, port = sys.argv[1], sys.argv[2]
r = {"name": "UIBC (self-test)",
     "implementation": "uibc-core resolve() behind HTTPS binding shim",
     "endpoint": "https://127.0.0.1:%s/1.0/identifiers" % port,
     "supportedDidMethods": ["did:key"]}
p = os.path.join(suite, "resolvers", "UIBC-selftest.json")
json.dump(r, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("      写入", p)
PY

echo "[5/6] 隔离跑（其它 resolver 移到一边，避免撞别人限流）"
mkdir -p "$SUITE/.others"
for f in "$SUITE"/resolvers/*.json; do
  case "$f" in */UIBC-selftest.json) ;; *) mv "$f" "$SUITE/.others/" ;; esac
done
cd "$SUITE"
NODE_TLS_REJECT_UNAUTHORIZED=0 npx mocha tests/4-did-resolution.js --timeout 15000 >"$OUT/4-did-resolution.log" 2>&1; RC1=$?
NODE_TLS_REJECT_UNAUTHORIZED=0 npx mocha tests/10-bindings.js      --timeout 15000 >"$OUT/10-bindings.log" 2>&1; RC2=$?

echo "[6/6] 汇总"
P1=$(grep -c "✓" "$OUT/4-did-resolution.log" || true); F1=$(grep -c "❌" "$OUT/4-did-resolution.log" || true)
P2=$(grep -c "✓" "$OUT/10-bindings.log" || true); F2=$(grep -c "❌" "$OUT/10-bindings.log" || true)
{
  echo "suite_commit=$SUITE_COMMIT"
  echo "node=$(node -v) npm=$(npm -v)"
  echo "port=$PORT"
  # 实现来源必须落进 summary：没有这行，"只换实现"的对照无法自证测的是哪份代码
  grep -m1 "impl=" "$OUT/shim.log" 2>/dev/null || echo "impl=<未记录>"
  echo "4-did-resolution: pass=$P1 fail=$F1 exit=$RC1"
  echo "10-bindings:      pass=$P2 fail=$F2 exit=$RC2"
} | tee "$OUT/summary.txt"

cat <<'NOTE'

读法（别误读成"通过"）：
  - 失败若集中在 did:key 成功路径，根因是"共享测试 DID 为 P-521、本实现仅 ed25519"，属已知能力边界；
  - 错误路径（坏 DID 400 / 不支持方法 501 / error 对象 / 空 metadata）通过，说明协议层是合规的；
  - 要拿"官方实现报告"，需要在 w3c 仓库提 resolver 清单 PR —— 那是对外动作，须本人批准。
NOTE
echo "日志：$OUT"
