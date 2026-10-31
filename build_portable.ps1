param(
    [string]$Name = "AtlasPKM",
    [switch]$NoClean
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host "Building $Name.exe ..."
$args = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--name", $Name,
    "--onefile",
    "--windowed",
    "--collect-submodules", "app",
    "--hidden-import", "app.main",
    "--hidden-import", "win32gui",
    "--hidden-import", "win32con",
    "--hidden-import", "pywintypes",
    "--hidden-import", "webview.platforms.edgechromium",
    "--hidden-import", "clr",
    "--hidden-import", "pythonnet",
    "--collect-all", "webview",
    "--add-data", "app/static;app/static",
    "--add-data", "app/templates;app/templates",
    "--add-data", "assets;assets",
    "--icon", "assets/atlas.ico",
    "desktop.py"
)
if (-not $NoClean) { $args = @("-m", "PyInstaller", "--clean") + $args[2..($args.Count - 1)] }

& python @args
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

$exe = Join-Path $root "dist\$Name.exe"
if (-not (Test-Path $exe)) { throw "Build output not found: $exe" }
Write-Host ""
Write-Host "Built: $exe"
Write-Host "First run creates data\\ and vault\\ next to the executable."
Write-Host "Run with --background for headless mode."
