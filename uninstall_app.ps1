param(
    [switch]$RemoveData
)

$ErrorActionPreference = "Stop"
$installDir = Join-Path $env:LOCALAPPDATA "AtlasPKM"
Get-Process AtlasPKM -ErrorAction SilentlyContinue | Stop-Process -Force

$browserProfile = Join-Path $installDir "browser"
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -in @("msedge.exe", "chrome.exe") -and $_.CommandLine -like "*$browserProfile*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 800

$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Atlas PKM.lnk"
$desktop = Join-Path ([Environment]::GetFolderPath("Desktop")) "Atlas PKM.lnk"
Remove-Item $startMenu -Force -ErrorAction SilentlyContinue
Remove-Item $desktop -Force -ErrorAction SilentlyContinue

$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
Remove-ItemProperty -Path $runKey -Name "AtlasPKM" -ErrorAction SilentlyContinue

if (-not (Test-Path $installDir)) {
    Write-Host "Atlas PKM is not installed."
    return
}

if ($RemoveData) {
    Remove-Item $installDir -Recurse -Force
    Write-Host "Removed application and data: $installDir"
} else {
    $keep = Join-Path $env:TEMP "AtlasPKM-uninstall-$(Get-Date -Format yyyyMMddHHmmss)"
    New-Item -ItemType Directory -Force $keep | Out-Null
    foreach ($name in @("data", "vault")) {
        $path = Join-Path $installDir $name
        if (Test-Path $path) {
            Move-Item $path (Join-Path $keep $name) -Force
        }
    }
    Remove-Item $installDir -Recurse -Force
    Write-Host "Removed application. Data and vault kept at: $keep"
    Write-Host "Run with -RemoveData to delete everything."
}
