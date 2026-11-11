param([string]$Config = (Join-Path $PSScriptRoot 'server-settings.json'))
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
if (!$PSBoundParameters.ContainsKey('Config') -and !(Test-Path -LiteralPath $Config)) {
    $Config = Join-Path $repoRoot 'server-settings.json'
}
$settings = Get-Content -LiteralPath $Config -Raw | ConvertFrom-Json
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath (Join-Path $repoRoot '.venv/Scripts/python.exe')) { $pythonPath = Join-Path $repoRoot '.venv/Scripts/python.exe' }
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run setup_server.ps1 first.' }
$serverArgs = @('-u', '-m', 'taxtracker.runtime.server', '--data-dir', $settings.DataDir,
    '--host', $settings.ListenAddress, '--port', [string]$settings.Port, '--allowed-host', $settings.AllowedHost)
if ($settings.Certificate) { $serverArgs += @('--cert', $settings.Certificate, '--key', $settings.PrivateKey) }
if ($settings.InsecureTestHttp) { $serverArgs += '--insecure-test-http' }
$logDirectory = Join-Path $settings.DataDir 'logs'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$logFile = Join-Path $logDirectory ('server-' + (Get-Date -Format 'yyyy-MM-dd') + '.log')
Set-Location -LiteralPath $repoRoot
$ErrorActionPreference = 'Continue'
& $pythonPath @serverArgs >> $logFile 2>&1
exit $LASTEXITCODE
