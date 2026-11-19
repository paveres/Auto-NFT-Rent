@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
title NFT Rent

where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% --version >nul 2>nul || (
  echo Python не найден. Установите Python 3.10+ с python.org и отметьте "Add python.exe to PATH".
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/2] Готовлю окружение, это один раз и займёт пару минут...
  %PY% -m venv .venv || (pause & exit /b 1)
)
echo [2/2] Проверяю библиотеки...
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt || (
  echo Не удалось установить библиотеки. Проверьте интернет и запустите снова.
  pause
  exit /b 1
)

if not "%~1"=="" (
  ".venv\Scripts\python.exe" main.py %*
  pause
  exit /b
)

:loop
".venv\Scripts\python.exe" main.py
if errorlevel 1 (
  echo.
  echo Остановлено с ошибкой. Прочитайте сообщение выше.
  pause
  exit /b 1
)
echo.
echo Перезапуск через 10 секунд. Закрыть — Ctrl+C.
timeout /t 10 >nul
goto loop
