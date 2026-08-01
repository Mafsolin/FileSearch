[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $projectRoot

$bootstrapCommand = Get-Command python.exe -ErrorAction SilentlyContinue
$bootstrapPython = if ($bootstrapCommand) { $bootstrapCommand.Source } else { $null }
if (-not $bootstrapPython) {
    $existingPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $existingPython) {
        $bootstrapPython = $existingPython
    }
}
if (-not $bootstrapPython) {
    throw "Python was not found. Install 64-bit Python 3.11.15 and retry."
}

$releaseVenv = Join-Path $projectRoot ".venv-release"
if (Test-Path -LiteralPath $releaseVenv) {
    Remove-Item -LiteralPath $releaseVenv -Recurse -Force
}
& $bootstrapPython -m venv $releaseVenv
if ($LASTEXITCODE -ne 0) { throw "Could not create the clean release environment." }
$python = Join-Path $releaseVenv "Scripts\python.exe"

$pythonTarget = (& $python -c 'import platform,struct,sys; print(sys.version_info.major,sys.version_info.minor,sys.version_info.micro,platform.machine().lower(),struct.calcsize(chr(80))*8,sep=chr(124))').Trim()
if ($pythonTarget -notin @("3|11|15|amd64|64", "3|11|15|x86_64|64")) {
    throw "Release builds require x64 Python 3.11.15; found $pythonTarget."
}

$pyproject = Get-Content -LiteralPath (Join-Path $projectRoot "pyproject.toml") -Raw
$versionMatch = [regex]::Match($pyproject, '(?ms)^\[project\].*?^version\s*=\s*"([^"]+)"')
if (-not $versionMatch.Success) {
    throw "Could not read the version from pyproject.toml."
}
$version = $versionMatch.Groups[1].Value

Write-Host "[1/3] Preparing build dependencies..."
& $python -m pip install --require-hashes -r (Join-Path $projectRoot "requirements-release.lock")
if ($LASTEXITCODE -ne 0) { throw "Could not install build dependencies." }

Write-Host "[2/3] Building FileSearch.exe..."
$frozenOutput = Join-Path $projectRoot "dist\FileSearch"
$lockedBuilds = Get-Process -Name "FileSearch" -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -and $_.Path.StartsWith($frozenOutput, [System.StringComparison]::OrdinalIgnoreCase)
}
if ($lockedBuilds) {
    Write-Host "Closing FileSearch from the previous build..."
    $lockedBuilds | Stop-Process -Force
    $lockedBuilds | Wait-Process -Timeout 10 -ErrorAction SilentlyContinue
}
& $python -m PyInstaller --noconfirm --clean (Join-Path $projectRoot "FileSearch.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }
$frozenExe = Join-Path $frozenOutput "FileSearch.exe"
& $python -c 'import pefile, sys; image = pefile.PE(sys.argv[1], fast_load=True); sys.exit(0 if image.FILE_HEADER.Machine == 0x8664 else 1)' $frozenExe
if ($LASTEXITCODE -ne 0) { throw "The frozen FileSearch executable is not x64." }

$isccCandidates = @(
    $env:ISCC_EXE,
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
) | Where-Object { $_ }
$iscc = $isccCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $iscc) {
    $isccCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($isccCommand) { $iscc = $isccCommand.Source }
}
if (-not $iscc) {
    throw "Inno Setup 6 was not found. Install it with: winget install --id JRSoftware.InnoSetup --exact"
}
$innoUninstaller = Join-Path (Split-Path -Parent $iscc) "unins000.exe"
if (-not (Test-Path -LiteralPath $innoUninstaller)) {
    throw "Could not determine the installed Inno Setup version."
}
$isccVersion = [version](Get-Item -LiteralPath $innoUninstaller).VersionInfo.ProductVersion
$requiredIsccVersion = [version]"6.7.3"
if ($isccVersion -ne $requiredIsccVersion) {
    throw "Release builds require Inno Setup $requiredIsccVersion; found $isccVersion."
}

$installerOutput = Join-Path $projectRoot "dist\installer"
New-Item -ItemType Directory -Path $installerOutput -Force | Out-Null
Write-Host "[3/3] Building the installer..."
& $iscc "/DAppVersion=$version" (Join-Path $projectRoot "installer\FileSearch.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed." }

$installer = Join-Path $installerOutput "FileSearch-Setup-$version.exe"
if (-not (Test-Path -LiteralPath $installer)) {
    throw "The installer was not found after the build: $installer"
}
Write-Host "Created: $installer" -ForegroundColor Green
