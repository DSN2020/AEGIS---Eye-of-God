param([ValidateSet('read','scan','search','export')][string]$Mode = 'read', [string]$Player = '')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (!(Test-Path -LiteralPath '.venv\Scripts\python.exe')) { throw 'Run .\Setup.ps1 first.' }
if ($Player) { & .\.venv\Scripts\python.exe -m ev_assistant $Mode --player $Player }
else { & .\.venv\Scripts\python.exe -m ev_assistant $Mode }
