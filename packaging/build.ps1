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
# The excluded modules are what pull in OpenSSL, which this tool never uses.
& $python -m PyInstaller --noconfirm --clean --log-level WARN `
    --name $name --console `
    --paths $root `
    --collect-all vgamepad `
    --exclude-module ssl --exclude-module _ssl --exclude-module _hashlib `
    --python-option u `
    --distpath (Join-Path $root 'dist') `
    --workpath (Join-Path $root 'build') `
    --specpath (Join-Path $root 'build') `
    (Join-Path $PSScriptRoot 'launcher.py')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

Copy-Item (Join-Path $root 'config.toml'), (Join-Path $root 'README.md'), (Join-Path $root 'LICENSE') $output
Copy-Item (Join-Path $PSScriptRoot 'bind.bat'), (Join-Path $PSScriptRoot 'calibrate.bat') $output

# Notices for the third-party software included in the folder.
$licenses = Join-Path $output 'licenses'
New-Item -ItemType Directory -Force $licenses | Out-Null
Copy-Item (Join-Path $PSScriptRoot 'licenses\*') $licenses
$pythonHome = & $python -c "import sys; print(sys.base_prefix)"
Copy-Item (Join-Path $pythonHome 'LICENSE.txt') (Join-Path $licenses 'Python.txt')
Copy-Item (Join-Path $root '.venv\Lib\site-packages\vgamepad-*.dist-info\licenses\LICENSE') (Join-Path $licenses 'vgamepad.txt')

if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $output -DestinationPath $zip

Write-Host "Built $output"
Write-Host "Zipped $zip"
