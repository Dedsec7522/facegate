# Start the load-testing environment: the isolated test API (port 8010), a Locust master with the web UI and the
# FaceGate dashboard (port 8089), and the Locust workers. Nothing here touches the application's own database.
#
#   ./start.ps1                 start everything, then open http://localhost:8089/facegate
#   ./start.ps1 -Workers 6      more load-generator processes
#   ./start.ps1 -Stop           stop Locust and the test API
#
# Then either use the Locust form at http://localhost:8089 for a single run, or run the whole plan:
#   .venv\Scripts\python tools\run_suite.py
param([int]$Workers = 4, [switch]$Stop)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
$locust = Join-Path $root ".venv\Scripts\locust.exe"
$out = Join-Path $root "test_results"
New-Item -ItemType Directory -Force $out | Out-Null

# Stop any previous Locust processes of this harness.
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='locust.exe'" |
  Where-Object { $_.CommandLine -like "*attendance-load-testing*locustfile.py*" -or $_.CommandLine -like "*attendance-load-testing*health_probe.py*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

if ($Stop) {
  & $py (Join-Path $root "tools\env.py") stop
  Write-Host "Load-testing environment stopped."
  exit 0
}

& $py (Join-Path $root "tools\env.py") start
$env:LT_WORKERS = "$Workers"
$file = Join-Path $root "locustfile.py"
Start-Process -FilePath $locust -WorkingDirectory $root -WindowStyle Hidden `
  -ArgumentList "-f `"$file`" --master --web-host 127.0.0.1 --web-port 8089 --expect-workers $Workers" `
  -RedirectStandardOutput (Join-Path $out "locust_master.log") -RedirectStandardError (Join-Path $out "locust_master.err.log")
for ($i = 0; $i -lt $Workers; $i++) {
  Start-Process -FilePath $locust -WorkingDirectory $root -WindowStyle Hidden `
    -ArgumentList "-f `"$file`" --worker" `
    -RedirectStandardOutput (Join-Path $out "locust_worker$i.log") -RedirectStandardError (Join-Path $out "locust_worker$i.err.log")
}
# Responsiveness watchdog: one health request a second, joined to each stage by the report.
Start-Process -FilePath $py -WorkingDirectory $root -WindowStyle Hidden -ArgumentList "`"$(Join-Path $root 'tools\health_probe.py')`""
Write-Host "Dashboard:      http://localhost:8089/facegate"
Write-Host "Locust control: http://localhost:8089"
Write-Host "Test API:       http://127.0.0.1:8010 (isolated database on port 5544)"
