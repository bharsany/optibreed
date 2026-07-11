# Activate virtual environment
if (Test-Path ".\venv\Scripts\Activate.ps1") {
    . .\venv\Scripts\Activate.ps1
}

# Install PyInstaller
Write-Host "Installing PyInstaller..."
pip install pyinstaller

# Run PyInstaller build
Write-Host "Building standalone executable..."
pyinstaller --onefile `
    --add-data "app/templates;app/templates" `
    --add-data "app/static;app/static" `
    --collect-submodules reportlab `
    --name optibreed `
    main.py

Write-Host "Build complete. Executable is located in the 'dist' folder."
