#!/usr/bin/env bash
# Положи рядом со скачанными файлами и запусти:  bash wine-build.sh
set -e
[ -f app.py ] || [ -d mini_teto ] || { echo "Запусти меня в папке, где лежит app.py"; exit 1; }

# пакет Python обязан лежать в папке mini_teto, windows/ нужна сборке
if [ ! -d mini_teto ]; then
    mkdir mini_teto windows
    mv __init__.py __main__.py app.py lines.py sound.py winplat.py mini_teto/
    mv build.bat make_icon.py mini_teto_win.py mini-teto.iss windows/
fi
[ -d sprites ] || cp -r ~/.local/share/mini-teto/sprites . || { echo "Нет спрайтов: положи сюда папку sprites"; exit 1; }

PYV=python-3.12.8-amd64.exe
PYDIR="C:\\users\\$USER\\AppData\\Local\\Programs\\Python\\Python312"
export WINEPATH="$PYDIR;$PYDIR\\Scripts"

if ! wine python --version >/dev/null 2>&1; then
    wget -q --show-progress -O "$PYV" "https://www.python.org/ftp/python/3.12.8/$PYV"
    wine "$PYV" /quiet InstallAllUsers=0 Include_tcltk=1 || true
    wineserver -k || true
    if ! wine python --version; then
        echo "Python не встал в Wine. Установщик оставил здесь: $PYV (запусти его вручную: wine $PYV)"
        exit 1
    fi
    rm -f "$PYV"
fi

wine cmd /c 'windows\build.bat'
echo
echo "Готово: dist/mini-teto.exe. Запускаю..."
wine dist/mini-teto.exe
