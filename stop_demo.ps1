# Stops the GlucoPilot backend and frontend started by run_demo.ps1
$root = $PSScriptRoot
$pidFile = Join-Path $root ".demo_pids"
if (Test-Path $pidFile) {
    $pids = (Get-Content $pidFile) -split " "
    foreach ($p in $pids) {
        if ($p -match '^\d+$') {
            try { Stop-Process -Id ([int]$p) -Force -ErrorAction Stop; Write-Host "Stopped PID $p" } catch { }
            # kill children (node spawned by npm)
            Get-CimInstance Win32_Process -Filter "ParentProcessId = $p" -ErrorAction SilentlyContinue | ForEach-Object {
                try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch { }
            }
        }
    }
    Remove-Item $pidFile -Force
}
# belt and braces: anything still listening on our ports
foreach ($port in 8000, 5173) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
        try { Stop-Process -Id $_.OwningProcess -Force -ErrorAction Stop; Write-Host "Freed port $port" } catch { }
    }
}
Write-Host "GlucoPilot stopped."
