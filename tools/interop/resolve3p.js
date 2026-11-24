// 第三方 did:web 解析器对照（不同方实现：uport/Veramo 生态的 did-resolver + web-did-resolver）
// 目的：W3C 对"独立实现"的定义要求代码由不同方开发。这一支是第三方代码，用来和我们自己的解析结果比对。
const { Resolver } = require('did-resolver');
const web = require('web-did-resolver');

const did = process.argv[2];
const resolver = new Resolver(web.getResolver());
resolver.resolve(did).then(r => {
  if (r.didResolutionMetadata && r.didResolutionMetadata.error) {
    console.log(JSON.stringify({ ok: false, error: r.didResolutionMetadata.error, message: r.didResolutionMetadata.message || '' }));
    process.exit(3);
  }
  const doc = r.didDocument || {};
  const vm = (doc.verificationMethod || [])[0] || {};
  const out = {
    ok: true,
    didDocumentId: doc.id,
    vmId: vm.id,
    vmType: vm.type,
    controller: vm.controller,
    publicKeyMultibase: vm.publicKeyMultibase || null,
    publicKeyJwk: vm.publicKeyJwk || null,
    vms: (doc.verificationMethod || []).length,
  };
  console.log(JSON.stringify(out, null, 1));
});
