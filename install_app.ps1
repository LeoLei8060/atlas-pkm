param(
    [switch]$StartWithWindows
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$source = Join-Path $root "dist\AtlasPKM.exe"
if (-not (Test-Path $source)) {
    throw "Build output not found: $source"
}

Get-Process AtlasPKM -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 500

$installDir = Join-Path $env:LOCALAPPDATA "AtlasPKM"
New-Item -ItemType Directory -Force $installDir | Out-Null
$target = Join-Path $installDir "AtlasPKM.exe"
Copy-Item $source $target -Force

$shell = New-Object -ComObject WScript.Shell
$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$shortcut = $shell.CreateShortcut((Join-Path $startMenu "Atlas PKM.lnk"))
$shortcut.TargetPath = $target
$shortcut.WorkingDirectory = $installDir
$shortcut.IconLocation = "$target,0"
$shortcut.Description = "Atlas PKM local knowledge base"
$shortcut.Save()

$desktop = [Environment]::GetFolderPath("Desktop")
$desktopShortcut = $shell.CreateShortcut((Join-Path $desktop "Atlas PKM.lnk"))
$desktopShortcut.TargetPath = $target
$desktopShortcut.WorkingDirectory = $installDir
$desktopShortcut.IconLocation = "$target,0"
$desktopShortcut.Save()

if ($StartWithWindows) {
    $runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
    $value = "`"$target`" --background"
    New-ItemProperty -Path $runKey -Name "AtlasPKM" -Value $value -PropertyType String -Force | Out-Null
    Write-Host "Autostart enabled (background mode)."
}

Write-Host "Installed: $target"
Write-Host "Shortcuts: Desktop and Start Menu"
Write-Host "Data and vault will be created next to the executable."
