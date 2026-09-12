# GlucoPilot one-command demo launcher (Windows PowerShell)
# Starts FastAPI on :8000 and Vite on :5173, then opens the browser.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Creating Python 3.11 virtual environment..."
    py -3.11 -m venv .venv
    & $py -m pip install --upgrade pip --quiet
    & $py -m pip install -r requirements.txt --quiet
}
try { & (Join-Path $root ".venv\Scripts\Activate.ps1") } catch { }

# 1. synthetic cohort (30 virtual people; new profiles are matched to them) + demo patient
if (-not (Test-Path (Join-Path $root "backend\data\cohort\p01\cgm.csv"))) {
    Write-Host "Generating the synthetic cohort (first run only, about 40 s)..."
    & $py -m backend.data.cohort
}
# 2. personalised fit for the demo patient
if (-not (Test-Path (Join-Path $root "backend\data\demo_patient\fit.json"))) {
    Write-Host "Fitting the demo patient's twin (first run only, < 60 s)..."
    & $py -m backend.inference.fitter --patient demo
}
# 3. frontend deps
if (-not (Test-Path (Join-Path $root "frontend\node_modules"))) {
    Write-Host "Installing frontend dependencies (first run only)..."
    Push-Location (Join-Path $root "frontend")
    npm install --silent
    Pop-Location
}

# 4. backend server (background)
$backend = Start-Process -FilePath $py -ArgumentList "-m","uvicorn","backend.api.app:app","--port","8000","--host","127.0.0.1" -WorkingDirectory $root -PassThru -WindowStyle Hidden
# 5. frontend server (background)
$npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue)
if ($null -eq $npm) { $npmPath = "npm" } else { $npmPath = $npm.Source }
$frontend = Start-Process -FilePath $npmPath -ArgumentList "run","dev","--","--port","5173","--strictPort" -WorkingDirectory (Join-Path $root "frontend") -PassThru -WindowStyle Hidden

"$($backend.Id) $($frontend.Id)" | Out-File -FilePath (Join-Path $root ".demo_pids") -Encoding ascii

# wait for backend
$ok = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch { Start-Sleep -Seconds 1 }
}
if (-not $ok) { Write-Host "Backend did not answer on :8000 in time; check backend.log" }
Start-Sleep -Seconds 3
Start-Process "http://localhost:5173"
Write-Host ""
Write-Host "GlucoPilot is running."
Write-Host "  Backend : http://127.0.0.1:8000  (docs at /docs)"
Write-Host "  Frontend: http://localhost:5173"
Write-Host "Run .\stop_demo.ps1 to stop both servers."
