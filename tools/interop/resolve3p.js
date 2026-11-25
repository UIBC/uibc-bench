// 第三方 did:web 解析器对照（不同方实现：uport/Veramo 生态的 did-resolver + web-did-resolver）
// 目的：W3C 对"独立实现"的定义要求代码由不同方开发。这一支是第三方代码，用来和我们自己的解析结果比对。
//
// 输出两段：单点摘要（I3 用）+ 逐条 verificationMethod 清单（I4 逐字段比对用）。
// 公钥规范化必须与 Python 侧 s09 的 _keyref() 逐字一致，否则比对会把"编码写法不同"误判成"不一致"。
const { Resolver } = require('did-resolver');
const web = require('web-did-resolver');

const did = process.argv[2];
const resolver = new Resolver(web.getResolver());

function stable(v) {
  if (Array.isArray(v)) return '[' + v.map(stable).join(',') + ']';
  if (v && typeof v === 'object') {
    return '{' + Object.keys(v).sort().map(k => JSON.stringify(k) + ':' + stable(v[k])).join(',') + '}';
  }
  return JSON.stringify(v);
}

function keyref(vm) {
  if (vm.publicKeyMultibase) return 'mb:' + vm.publicKeyMultibase;
  if (vm.publicKeyJwk) return 'jwk:' + stable(vm.publicKeyJwk);
  if (vm.publicKeyHex) return 'hex:' + vm.publicKeyHex;
  if (vm.publicKeyBase58) return 'b58:' + vm.publicKeyBase58;
  if (vm.publicKeyPem) return 'pem:' + vm.publicKeyPem;
  return 'none';
}

function vmlist(doc) {
  return (doc.verificationMethod || []).map(vm => ({
    id: vm.id || null,
    type: vm.type || null,
    controller: vm.controller || null,
    key: keyref(vm),
  })).sort((a, b) => String(a.id).localeCompare(String(b.id)));
}

resolver.resolve(did).then(r => {
  if (r.didResolutionMetadata && r.didResolutionMetadata.error) {
    console.log(JSON.stringify({ ok: false, error: r.didResolutionMetadata.error, message: r.didResolutionMetadata.message || '' }));
    process.exit(3);
  }
  const doc = r.didDocument || {};
  const vm = (doc.verificationMethod || [])[0] || {};
  const out = {
    ok: true,
    didDocumentId: doc.id || null,
    vmId: vm.id || null,
    vmType: vm.type || null,
    controller: vm.controller || null,
    publicKeyMultibase: vm.publicKeyMultibase || null,
    publicKeyJwk: vm.publicKeyJwk || null,
    vms: (doc.verificationMethod || []).length,
    vmList: vmlist(doc),
    authentication: (doc.authentication || []).map(a => (typeof a === 'string' ? a : (a && a.id) || null)).sort(),
  };
  console.log(JSON.stringify(out, null, 1));
});
