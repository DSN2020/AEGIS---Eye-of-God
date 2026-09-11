param([Parameter(Mandatory=$true)][string]$PackageRoot)
$ErrorActionPreference = 'Stop'
$PackageRoot = (Resolve-Path -LiteralPath $PackageRoot).Path
$projectRoot = Split-Path -Parent $PSScriptRoot
$checkRoot = Join-Path $projectRoot ('.build/check-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $checkRoot | Out-Null
$savedData = $env:EOG_DATA_ROOT
$savedOutput = $env:EOG_TEST_OUTPUT
$savedPath = $env:PATH
$savedDotnet = $env:DOTNET_ROOT
$savedMultilevel = $env:DOTNET_MULTILEVEL_LOOKUP
try {
    $env:EOG_DATA_ROOT = Join-Path $checkRoot 'Fresh user with spaces'
    $env:EOG_TEST_OUTPUT = $checkRoot
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $env:DOTNET_ROOT = Join-Path $checkRoot 'no-system-dotnet'
    $env:DOTNET_MULTILEVEL_LOOKUP = '0'
    & (Join-Path $PackageRoot 'runtime/python/python.exe') (Join-Path $PSScriptRoot 'check_package.py') $PackageRoot
    if ($LASTEXITCODE -ne 0) { throw 'Packaged backend checks failed.' }
    $desktop = Start-Process -FilePath (Join-Path $PackageRoot 'EOG.exe') -ArgumentList '--smoke-test' -WorkingDirectory $checkRoot -WindowStyle Hidden -PassThru
    if (!$desktop.WaitForExit(60000)) { $desktop.Kill(); throw 'Desktop startup timed out.' }
    if ($desktop.ExitCode -ne 0 -or !(Test-Path -LiteralPath (Join-Path $checkRoot 'smoke-test.json'))) {
        throw "Desktop startup failed. See $checkRoot"
    }
    $report = Get-Content -LiteralPath (Join-Path $checkRoot 'smoke-test.json') -Raw | ConvertFrom-Json
    if (!$report.passed -or !$report.accountsPage) { throw 'The welcome screen check failed.' }
    Write-Host "Package checks passed. First-run screenshot and results: $checkRoot"
} finally {
    $env:EOG_DATA_ROOT=$savedData
    $env:EOG_TEST_OUTPUT=$savedOutput
    $env:PATH=$savedPath
    $env:DOTNET_ROOT=$savedDotnet
    $env:DOTNET_MULTILEVEL_LOOKUP=$savedMultilevel
}
