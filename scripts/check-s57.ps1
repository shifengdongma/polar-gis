param(
    [Parameter(Mandatory = $true)]
    [string]$FilePath
)

$resolved = Resolve-Path -LiteralPath $FilePath -ErrorAction Stop
$formatOutput = & ogrinfo --formats 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "ogrinfo不可用，请安装GDAL并加入PATH。"
}
if ($formatOutput -notmatch 'S-57') {
    throw "当前GDAL未启用S-57驱动。"
}
& ogrinfo -ro -so -al -json $resolved.Path
if ($LASTEXITCODE -ne 0) {
    throw "S-57样本检查失败。"
}

