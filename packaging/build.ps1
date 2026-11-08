# Builds the Windows exe into dist\azahar-mouse-camera, and zips that folder.
# Needs the dev requirements: pip install -r requirements-dev.txt

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$name = 'azahar-mouse-camera'
$output = Join-Path $root "dist\$name"
$zip = Join-Path $root "dist\$name-windows-x64.zip"

Set-Location $root

# vgamepad loads its driver DLL from beside its own code, which PyInstaller can't
# detect, so --collect-all is what brings it along. That also brings the ViGEmBus
# installer. A folder, not --onefile: it starts faster and config.toml has to sit
# beside the exe anyway. "--python-option u" keeps output live when it's redirected.
& $python -m PyInstaller --noconfirm --clean --log-level WARN `
    --name $name --console `
    --paths $root `
    --collect-all vgamepad `
    --python-option u `
    --distpath (Join-Path $root 'dist') `
    --workpath (Join-Path $root 'build') `
    --specpath (Join-Path $root 'build') `
    (Join-Path $PSScriptRoot 'launcher.py')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

Copy-Item (Join-Path $root 'config.toml'), (Join-Path $root 'README.md'), (Join-Path $root 'LICENSE') $output
Copy-Item (Join-Path $PSScriptRoot 'bind.bat'), (Join-Path $PSScriptRoot 'calibrate.bat') $output

if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $output -DestinationPath $zip

Write-Host "Built $output"
Write-Host "Zipped $zip"
