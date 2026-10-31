$ErrorActionPreference = "Stop"
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$existing = Get-ItemProperty -Path $runKey -Name "AtlasPKM" -ErrorAction SilentlyContinue
if ($null -eq $existing) {
    Write-Host "AtlasPKM autostart entry is not present."
    exit 0
}
Remove-ItemProperty -Path $runKey -Name "AtlasPKM"
Write-Host "AtlasPKM autostart entry removed."
Write-Host "Any running background process is left alone; end AtlasPKM.exe in Task Manager if needed."
