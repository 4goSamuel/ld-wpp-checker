@echo off
title LD WhatsApp Checker
cd /d "%~dp0"

where python >nul 2>&1 && (
    python ld_wpp_checker.py
    exit /b
)
where py >nul 2>&1 && (
    py ld_wpp_checker.py
    exit /b
)

echo [ERRO] Python nao encontrado.
echo Instale em https://www.python.org/downloads/ e marque "Add Python to PATH".
pause
