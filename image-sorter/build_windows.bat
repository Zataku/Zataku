@echo off
REM Builds ImageSorter.exe. Run this on a Windows PC that has Python installed
REM (python.org installer, with "Add python.exe to PATH" ticked).
cd /d "%~dp0"
python -m pip install --upgrade pyinstaller -r requirements.txt || goto :error
python -m PyInstaller --onefile --windowed --collect-submodules winrt --name ImageSorter image_sorter_app.py || goto :error
echo.
echo Done! Your program is at: %~dp0dist\ImageSorter.exe
pause
exit /b 0

:error
echo.
echo Build failed. Make sure Python is installed and on your PATH.
pause
exit /b 1
