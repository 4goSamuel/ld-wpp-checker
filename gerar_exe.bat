@echo off
title Gerar LD_WPP_Checker.exe
cd /d "%~dp0"

set "PY=python"
where python >nul 2>&1 || set "PY=py"

echo Instalando/atualizando o PyInstaller...
%PY% -m pip install --upgrade pyinstaller
if errorlevel 1 (
    echo [ERRO] Falha ao instalar o PyInstaller.
    pause
    exit /b 1
)

echo.
echo Gerando o .exe...
%PY% -m PyInstaller --onefile --console --name LD_WPP_Checker --clean ld_wpp_checker.py
if errorlevel 1 (
    echo [ERRO] Falha ao gerar o .exe.
    pause
    exit /b 1
)

copy /y "dist\LD_WPP_Checker.exe" "%~dp0LD_WPP_Checker.exe" >nul
rd /s /q build 2>nul
rd /s /q dist 2>nul
del /q LD_WPP_Checker.spec 2>nul

echo.
echo Pronto! LD_WPP_Checker.exe criado nesta pasta.
pause
