param(
    [ValidatePattern('^\d+\.\d+\.\d+([-.][A-Za-z0-9.]+)?$')][string]$Version = '0.1.0',
    [switch]$SkipArchive
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$buildRoot = Join-Path $projectRoot '.build'
$cacheRoot = Join-Path $buildRoot 'cache'
$distRoot = Join-Path $projectRoot 'dist'
$packageRoot = Join-Path $distRoot "EOG-$Version-windows-x64"
New-Item -ItemType Directory -Force $cacheRoot,$distRoot | Out-Null
if (Test-Path -LiteralPath $packageRoot) { throw "Build output already exists: $packageRoot. Use a new version or move that output before rebuilding." }
New-Item -ItemType Directory $packageRoot | Out-Null

function Get-VerifiedDownload([string]$Url, [string]$Path, [string]$Sha256) {
    if (!(Test-Path -LiteralPath $Path)) { Invoke-WebRequest -Uri $Url -OutFile $Path }
    if ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -ne $Sha256) { throw "Download checksum mismatch: $Path" }
}
function Assert-Exit([string]$Step) { if ($LASTEXITCODE -ne 0) { throw "$Step failed (exit $LASTEXITCODE)." } }

Write-Host 'Building the self-contained Windows desktop app...'
& dotnet publish (Join-Path $projectRoot 'DesktopApp/EyeOfGod.csproj') -c Release -r win-x64 --self-contained true -o $packageRoot -p:DebugType=None -p:DebugSymbols=false -p:RuntimeFrameworkVersion=8.0.31 -p:Version=$Version
Assert-Exit 'Desktop publish'

# Explicit allowlist: never copy a working directory, local data or credentials.
foreach ($name in @('app_bridge.py','sweep_supervisor.py','isolated_supervisor.py','shared_browser_host.cjs','config.example.json')) {
    Copy-Item -LiteralPath (Join-Path $projectRoot $name) -Destination $packageRoot
}
foreach ($name in @('ev_assistant','eog_automation')) {
    $destination = Join-Path $packageRoot $name
    New-Item -ItemType Directory $destination | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $projectRoot $name) -File -Filter '*.py' | Copy-Item -Destination $destination
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'START-HERE.txt') -Destination $packageRoot
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'THIRD-PARTY-NOTICES.txt') -Destination (Join-Path $packageRoot 'EOG-THIRD-PARTY-NOTICES.txt')

Write-Host 'Bundling Python and Python dependencies...'
$pythonVersion = '3.12.14'
$pythonArchive = Join-Path $cacheRoot "python-$pythonVersion.tar.gz"
Get-VerifiedDownload 'https://github.com/astral-sh/python-build-standalone/releases/download/20260901/cpython-3.12.14%2B20260901-x86_64-pc-windows-msvc-install_only_stripped.tar.gz' $pythonArchive '7C45C9622400D578709A9B2CDDBE8124CC21D382409D9F13406D706D28E31B14'
$pythonRoot = Join-Path $packageRoot 'runtime/python'
New-Item -ItemType Directory -Force (Join-Path $packageRoot 'runtime') | Out-Null
& tar -xf $pythonArchive -C (Join-Path $packageRoot 'runtime')
Assert-Exit 'Python extraction'
# Isolated relative import paths keep subprocesses portable and ignore user Python installs.
@('.', 'DLLs', 'Lib', 'Lib\site-packages','..\..','import site') | Set-Content -LiteralPath (Join-Path $pythonRoot 'python312._pth') -Encoding ascii
$python = Join-Path $pythonRoot 'python.exe'
# ONNX Runtime needs the MSVC runtime even on machines with no developer tools.
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
if (!(Test-Path -LiteralPath $vswhere)) { throw 'Build machine needs Visual Studio C++ Build Tools for its redistributable runtime.' }
$visualStudio = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
Assert-Exit 'Locate C++ runtime'
if (!$visualStudio) { throw 'Visual Studio C++ Build Tools were not found.' }
$redistVersion = Get-ChildItem -LiteralPath (Join-Path $visualStudio 'VC/Redist/MSVC') -Directory | Where-Object { $_.Name -match '^\d+\.\d+\.\d+$' } | Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1
$crt = Get-ChildItem -LiteralPath (Join-Path $redistVersion.FullName 'x64') -Directory -Filter 'Microsoft.VC*.CRT' | Select-Object -First 1
if (!$crt) { throw 'The x64 Microsoft C++ redistributable DLLs were not found.' }
Get-ChildItem -LiteralPath $crt.FullName -Filter '*.dll' | Copy-Item -Destination $pythonRoot
$requirements = Join-Path $PSScriptRoot 'requirements-windows.lock'
if (!(Test-Path -LiteralPath $requirements)) { $requirements = Join-Path $projectRoot 'requirements.txt' }
& $python -m pip install --disable-pip-version-check --no-warn-script-location --only-binary=:all: -r $requirements
Assert-Exit 'Python dependencies'
& $python -m pip list --format=freeze --disable-pip-version-check | Set-Content -LiteralPath (Join-Path $packageRoot 'python-packages.txt') -Encoding ascii
Assert-Exit 'Dependency inventory'

Write-Host 'Bundling the matching Chromium browser...'
$oldBrowserPath = $env:PLAYWRIGHT_BROWSERS_PATH
try {
    $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $packageRoot 'runtime/browsers'
    & $python -m playwright install chromium
    Assert-Exit 'Browser download'
} finally { $env:PLAYWRIGHT_BROWSERS_PATH = $oldBrowserPath }

$commit = & git -C $projectRoot rev-parse HEAD
@{version=$Version; platform='windows-x64'; python=$pythonVersion; sourceCommit=$commit} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $packageRoot 'eog-release.json') -Encoding ascii

Write-Host 'Checking the packaged backend, browser, OCR and fresh desktop startup...'
& (Join-Path $PSScriptRoot 'Test-WindowsPackage.ps1') -PackageRoot $packageRoot
& $python (Join-Path $PSScriptRoot 'clean_package.py') $packageRoot
Assert-Exit 'Release cleanup'

if (!$SkipArchive) {
    $archive = "$packageRoot.zip"
    # ZipFile includes Chromium's dotfiles and large files and preserves the top-level folder.
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory($packageRoot, $archive, [System.IO.Compression.CompressionLevel]::Optimal, $true)
    "$((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLower())  $([IO.Path]::GetFileName($archive))" | Set-Content -LiteralPath "$archive.sha256" -Encoding ascii
    Write-Host "Ready: $archive"
}
