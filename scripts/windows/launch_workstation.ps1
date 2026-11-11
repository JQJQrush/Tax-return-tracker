param([string]$DataDir = (Join-Path $env:LOCALAPPDATA 'TaxPrepLocal'))
$ErrorActionPreference='Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$configPath = Join-Path $PSScriptRoot 'local-runtime.json'
if (!(Test-Path -LiteralPath $configPath)) { $configPath = Join-Path $repoRoot 'local-runtime.json' }
$config=Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
Set-Location -LiteralPath $repoRoot
if ([IO.Path]::GetFullPath($DataDir) -ne [IO.Path]::GetFullPath($config.DataDir)) { throw 'Data directory differs from the managed service configuration.' }
Start-ScheduledTask -TaskName $config.TaskName
$python=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python)) { $python = Join-Path $repoRoot '.venv/Scripts/python.exe' }
for($attempt=0;$attempt -lt 30;$attempt++) {
    $url=& $python -c 'import sys;from taxtracker.operations import instance;print(instance.active_url(sys.argv[1]) or str())' $DataDir
    if ($url -match '^https?://(127\.0\.0\.1|localhost):[0-9]+/?$') { Start-Process $url; exit 0 }
    Start-Sleep -Seconds 1
}
throw 'Service did not start within 30 seconds. Check TaxPrepLocal\logs\supervisor.jsonl.'
