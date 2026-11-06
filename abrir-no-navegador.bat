@echo off
rem Abre o Tierlist IA no navegador, sem a janela propria (o atalho do Menu Iniciar usa a janela).
cd /d "%~dp0"
start "" /b python iniciar.py
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:4362/
echo Tierlist IA rodando em http://127.0.0.1:4362/
echo Feche esta janela para desligar.
pause >nul
