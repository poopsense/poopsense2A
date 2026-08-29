param([switch]$TestModel)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root "backend\.venv-runtime\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = Join-Path $root "backend\.venv-win\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $python)) {
    throw "找不到后端 Python 环境，请先安装 backend 依赖。"
}

$arguments = @((Join-Path $root "backend\scripts\demo_smoke.py"))
if ($TestModel) { $arguments += "--test-model" }
& $python @arguments
exit $LASTEXITCODE
