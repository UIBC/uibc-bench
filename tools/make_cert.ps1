# Generate a self-signed cert for the local HTTPS shim, without openssl.
# Windows-native fallback (.NET CertificateRequest, no admin required).
# ASCII only on purpose: this file may be run by Windows PowerShell 5.1,
# which mis-parses UTF-8-without-BOM files containing Chinese characters.
# Usage: pwsh -File tools/make_cert.ps1 -OutDir _pki
param(
    [string]$OutDir = "_pki",
    [string]$Cn = "localhost",
    [int]$Days = 3650
)

$ErrorActionPreference = "Stop"
$cert = Join-Path $OutDir "cert.pem"
$key = Join-Path $OutDir "key.pem"
if ((Test-Path $cert) -and (Test-Path $key)) {
    Write-Output "[cert] exists: $OutDir"
    exit 0
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$rsa = [System.Security.Cryptography.RSA]::Create(2048)
$req = [System.Security.Cryptography.X509Certificates.CertificateRequest]::new(
    "CN=$Cn",
    $rsa,
    [System.Security.Cryptography.HashAlgorithmName]::SHA256,
    [System.Security.Cryptography.RSASignaturePadding]::Pkcs1
)
$san = [System.Security.Cryptography.X509Certificates.SubjectAlternativeNameBuilder]::new()
$san.AddDnsName("localhost")
$san.AddIpAddress([System.Net.IPAddress]::Loopback)
$req.CertificateExtensions.Add($san.Build())

$notBefore = (Get-Date).AddDays(-1)
$x509 = $req.CreateSelfSigned($notBefore, $notBefore.AddDays($Days))

$pem = $x509.ExportCertificatePem()
$keyPem = $rsa.ExportPkcs8PrivateKeyPem()
[System.IO.File]::WriteAllText((Resolve-Path $OutDir).Path + "\cert.pem", $pem + "`n")
[System.IO.File]::WriteAllText((Resolve-Path $OutDir).Path + "\key.pem", $keyPem + "`n")
Write-Output "[cert] generated (CN=$Cn, $Days days) -> $OutDir"
