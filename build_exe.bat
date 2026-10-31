@echo off
rem Builds "DBL Data Converter.exe" in the dist folder.
rem Requirements: Windows 10 or 11 and Python 3.9 or later on the PATH.
rem PyInstaller is installed into a separate build environment (.buildenv), not the main Python.
setlocal
cd /d "%~dp0"
if not exist .buildenv python -m venv .buildenv || goto :fail
call .buildenv\Scripts\activate.bat || goto :fail
python -m pip install --quiet --upgrade pip pyinstaller pytest || goto :fail
echo Running tests...
python -m pytest -q tests || goto :fail
echo Building...
pyinstaller --noconfirm --clean --onefile --windowed --name "DBL Data Converter" --icon "dblconv\data\app.ico" --version-file version_info.txt --add-data "dblconv\data;dblconv\data" "DBL Data Converter.py" || goto :fail
echo.
echo Built: %~dp0dist\DBL Data Converter.exe
goto :eof
:fail
echo.
echo The build stopped because a step failed. See the messages above.
exit /b 1
