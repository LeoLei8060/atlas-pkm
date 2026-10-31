param(
    [string]$Exe
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $Exe) {
    $Exe = Join-Path $root "dist\AtlasPKM.exe"
}
if (-not (Test-Path $Exe)) {
    throw "Executable not found: $Exe"
}
$Exe = (Resolve-Path $Exe).Path

$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$value = "`"$Exe`" --background"
New-ItemProperty -Path $runKey -Name "AtlasPKM" -Value $value -PropertyType String -Force | Out-Null

Write-Host "AtlasPKM will start automatically at Windows logon:"
Write-Host "  $value"
Write-Host ""
Write-Host "After logon, the background server runs without a window."
Write-Host "Double-clicking AtlasPKM.exe opens the UI and reuses that server."
Write-Host "Run uninstall_startup.ps1 to remove autostart."
