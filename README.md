# mini Teto

Рядом с этим файлом нужна папка `sprites/` (спрайты Тето) — в архив она не входит.

## Linux
    ./install.sh              # установить (с автозапуском); --no-autostart, --uninstall
    mini-teto                 # запустить;  mini-teto feed | say привет | sing | quit

## Windows
Установщик: запушить папку на GitHub, сборка пойдёт сама (.github/workflows/windows.yml),
готовый mini-teto-setup.exe будет в Actions -> Artifacts.
Локально на Windows:  windows\build.bat   (нужен Python с python.org; для установщика ещё Inno Setup 6)
Под Wine на Linux:    bash wine-build.sh  -> dist/mini-teto.exe (один файл)

Чтобы шрифт на Windows совпал с Linux: положить свой шрифт в fonts/bold.ttf (и regular.ttf).
