param(
    [string]$DataDir = (Join-Path $env:ProgramData 'TaxReturnTrackerData'),
    [string]$ListenAddress = '127.0.0.1',
    [string]$HostName = 'localhost',
    [int]$Port = 8765,
    [string]$Certificate,
    [string]$PrivateKey,
    [switch]$InsecureTestHttp,
    [switch]$InstallStartupTask
)
$ErrorActionPreference = 'Stop'
if ($Port -lt 1 -or $Port -gt 65535) { throw 'Invalid port.' }
if ($HostName -notmatch '^[a-zA-Z0-9.-]+$') { throw 'Use a DNS hostname or IPv4 address.' }
if ($ListenAddress -notin @('127.0.0.1','localhost') -and -not $Certificate -and -not $InsecureTestHttp) {
    throw 'LAN access requires -Certificate and -PrivateKey; synthetic-data testing can use -InsecureTestHttp.'
}
if ([bool]$Certificate -ne [bool]$PrivateKey) { throw 'Supply both certificate and private key.' }
if ($Certificate) {
    $Certificate = (Resolve-Path -LiteralPath $Certificate).Path
    $PrivateKey = (Resolve-Path -LiteralPath $PrivateKey).Path
}
$DataDir = [IO.Path]::GetFullPath($DataDir)
$sourcePath = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
if ($DataDir.StartsWith('\\') -or $DataDir.TrimEnd('\') -eq $sourcePath -or $DataDir.StartsWith($sourcePath + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Use a server-local data directory outside the source checkout.'
}
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    if (Get-Command py -ErrorAction SilentlyContinue) { & py -3 -m venv .venv }
    else { & python -m venv .venv }
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.10+ is required.' }
}
& $pythonPath -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
Write-Host 'Stop any running tracker first. Create/reset the app administrator (not your Windows password).'
& $pythonPath (Join-Path $PSScriptRoot 'server.py') --data-dir $DataDir --set-user admin --role admin
if ($LASTEXITCODE -ne 0) { throw 'Administrator setup failed.' }
$configPath = Join-Path $PSScriptRoot 'server-settings.json'
@{ DataDir=$DataDir; ListenAddress=$ListenAddress; Port=$Port; AllowedHost="${HostName}:$Port";
   Certificate=$Certificate; PrivateKey=$PrivateKey; InsecureTestHttp=[bool]$InsecureTestHttp
} | ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding UTF8
if ($InstallStartupTask) {
    # Windows stores this credential for the task. Never put its password into config/source/logs.
    $credential = Get-Credential -Message 'Dedicated Windows account to run the tracker while nobody is logged in'
    if (-not $credential) { throw 'Task account was not supplied.' }
    $runner = Join-Path $PSScriptRoot 'start_server.ps1'
    if ($runner.Contains('"') -or $configPath.Contains('"')) { throw 'Paths cannot contain quotes.' }
    $action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runner`" -Config `"$configPath`"" -WorkingDirectory $PSScriptRoot
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $plain = $credential.GetNetworkCredential().Password
    try {
        Register-ScheduledTask -TaskName 'TaxReturnTracker' -Action $action -Trigger $trigger -Settings $settings -User $credential.UserName -Password $plain -RunLevel Limited -Description 'Tax Return Tracker office web server' -Force | Out-Null
    } finally { $plain = $null }
    Write-Host 'Startup task installed. Grant this Windows account access to source, data and TLS files, then run: Start-ScheduledTask -TaskName TaxReturnTracker'
}
Write-Host "Configuration saved: $configPath"
Write-Host 'To start manually: powershell -NoProfile -ExecutionPolicy Bypass -File .\start_server.ps1'
