@echo off
REM Builds "Store Lookup.exe" on Windows.
REM Needs Python 3 from python.org (tick "Add python.exe to PATH" when installing).
REM Keep this file in the same folder as store_lookup.py and the two CSVs, then double-click it.

cd /d "%~dp0"

python -m venv build_env || goto :error
build_env\Scripts\python -m pip install --quiet pyinstaller certifi || goto :error

build_env\Scripts\pyinstaller --noconfirm --onefile --windowed --name "Store Lookup" ^
  --hidden-import certifi ^
  --add-data "Chase TH Active Accounts - Canada 2(Data).csv;." ^
  --add-data "Tim Hortons - Gift Card MIDs(Sheet 1).csv;." ^
  store_lookup.py || goto :error

echo.
echo Done! The program is at: %~dp0dist\Store Lookup.exe
pause
exit /b 0

:error
echo.
echo Build failed - see the messages above.
pause
exit /b 1
