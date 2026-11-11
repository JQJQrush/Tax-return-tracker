param([string]$DataDir = (Join-Path $env:LOCALAPPDATA 'TaxPrepLocal'))
$ErrorActionPreference='Stop'
$config=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'local-runtime.json') -Raw | ConvertFrom-Json
if ([IO.Path]::GetFullPath($DataDir) -ne [IO.Path]::GetFullPath($config.DataDir)) { throw 'Data directory differs from the managed service configuration.' }
Start-ScheduledTask -TaskName $config.TaskName
$python=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
for($attempt=0;$attempt -lt 30;$attempt++) {
    $url=& $python -c 'import instance,sys;print(instance.active_url(sys.argv[1]) or str())' $DataDir
    if ($url -match '^https?://(127\.0\.0\.1|localhost):[0-9]+/?$') { Start-Process $url; exit 0 }
    Start-Sleep -Seconds 1
}
throw 'Service did not start within 30 seconds. Check TaxPrepLocal\logs\supervisor.jsonl.'
