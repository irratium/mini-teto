@echo off
rem Builds dist\mini-teto.exe, one single file (PyInstaller) and dist\mini-teto-setup.exe (Inno Setup).
rem Needs: Python 3.10+ from python.org (with tcl/tk), and Inno Setup 6 for the installer step.
rem Run it from anywhere: windows\build.bat
setlocal
cd /d "%~dp0.."

if not exist sprites\idle.png (
    echo sprites\idle.png not found: put the sprites\ folder next to mini_teto\ and windows\.
    exit /b 1
)

python -m venv .venv-win || goto :err
call .venv-win\Scripts\activate.bat || goto :err
python -m pip install --upgrade pip || goto :err
python -m pip install pyinstaller pycairo pillow sounddevice || goto :err
python -m pip install winrt-runtime winrt-Windows.Media.Control winrt-Windows.Foundation winrt-Windows.Foundation.Collections winrt-Windows.Storage.Streams || echo Music reactions will be off: the winrt packages did not install.
set FONTS=
if exist fonts\bold.ttf set FONTS=--add-data "fonts;fonts"

python windows\make_icon.py || goto :err

pyinstaller --noconfirm --clean --onefile --noconsole --name mini-teto ^
    --icon windows\mini-teto.ico --paths . ^
    --add-data "sprites;sprites" %FONTS% ^
    --hidden-import mini_teto.winplat --hidden-import PIL._tkinter_finder ^
    --hidden-import winrt.windows.media.control --hidden-import winrt.windows.foundation --hidden-import winrt.windows.foundation.collections --hidden-import winrt.windows.storage.streams ^
    --collect-all _sounddevice_data --collect-all cairo ^
    windows\mini_teto_win.py || goto :err

if /i "%~1"=="exe" goto :noinno
set "ISCC="
where iscc >nul 2>nul && set "ISCC=iscc"
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC goto :noinno
"%ISCC%" windows\mini-teto.iss || goto :err
echo.
echo.
echo Done: dist\mini-teto-setup.exe
exit /b 0

:noinno
echo.
echo The program is built: dist\mini-teto.exe
echo No installer step here (called with 'exe', or Inno Setup 6 is missing: https://jrsoftware.org/isdl.php).
exit /b 0

:err
echo.
echo BUILD FAILED
exit /b 1
