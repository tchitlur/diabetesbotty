# GlucoPilot: one-time Gemini API key setup
$root = Split-Path -Parent $PSScriptRoot
Write-Host ""
Write-Host "Go to https://aistudio.google.com/apikey, click Create API key, copy it, and paste it here."
$key = Read-Host "GEMINI_API_KEY"
if ([string]::IsNullOrWhiteSpace($key)) {
    Write-Host "No key entered. Nothing saved. The demo still runs with the local fallback parser."
    exit 0
}
$envPath = Join-Path $root ".env"
"GEMINI_API_KEY=$key" | Out-File -FilePath $envPath -Encoding ascii
Write-Host "Saved. You never need to do this again."
