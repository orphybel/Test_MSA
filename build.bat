@echo off
REM Construction de TestMSA.exe (standalone, Windows).
REM Prerequis : Python 3.9+ installe et accessible dans le PATH.

setlocal
echo === Installation des dependances ===
python -m pip install --upgrade pip || goto :erreur
python -m pip install -r requirements.txt pyinstaller || goto :erreur

echo.
echo === Construction de l'executable ===
python -m PyInstaller --noconfirm --clean TestMSA.spec || goto :erreur

echo.
echo === Termine : dist\TestMSA.exe ===
endlocal
exit /b 0

:erreur
echo.
echo *** La construction a echoue ***
endlocal
exit /b 1
