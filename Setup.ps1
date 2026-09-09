$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& py -3.10 -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Python 3.10 is required.' }
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
if (!(Test-Path -LiteralPath 'config.json')) {
    Copy-Item -LiteralPath 'config.example.json' -Destination 'config.json'
}
if (!(Test-Path -LiteralPath 'desktop-runtime.json')) {
    @{ pythonPath = (Resolve-Path -LiteralPath '.venv\Scripts\python.exe').Path } |
        ConvertTo-Json | Set-Content -LiteralPath 'desktop-runtime.json' -Encoding UTF8
}
Write-Host 'Setup complete. Install Google Chrome and the .NET 8 SDK, then build DesktopApp/EyeOfGod.csproj. Add accounts inside EOG before resuming a scan.'
