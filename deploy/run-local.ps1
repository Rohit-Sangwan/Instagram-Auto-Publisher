$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $project
$config = Get-Content -Raw -LiteralPath (Join-Path $project 'data/local-settings.json') | ConvertFrom-Json
foreach ($property in $config.PSObject.Properties) {
    [Environment]::SetEnvironmentVariable($property.Name, [string]$property.Value, 'Process')
}
$env:DATA_DIR = Join-Path $project 'data'
$env:LOCAL_FRONTEND_DIR = Join-Path $project 'frontend/dist'
$env:PYTHONUNBUFFERED = '1'
$server = Start-Process -FilePath (Join-Path $project '.venv/Scripts/python.exe') -ArgumentList '-m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log' -WindowStyle Hidden -PassThru -Wait -RedirectStandardOutput (Join-Path $project 'data/local-stdout.log') -RedirectStandardError (Join-Path $project 'data/local-server.log')
exit $server.ExitCode


