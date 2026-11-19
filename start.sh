#!/usr/bin/env sh
cd "$(dirname "$0")" || exit 1
export PYTHONUTF8=1

PY=$(command -v python3 || command -v python)
if [ -z "$PY" ]; then
  echo "Python не найден. Установите: sudo apt install -y python3 python3-venv"
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "[1/2] Готовлю окружение, это один раз..."
  "$PY" -m venv .venv || { echo "Нужен пакет venv: sudo apt install -y python3-venv"; exit 1; }
fi
echo "[2/2] Проверяю библиотеки..."
.venv/bin/python -m pip install -q --disable-pip-version-check -r requirements.txt || exit 1

if [ -n "$1" ]; then
  exec .venv/bin/python main.py "$@"
fi
while true; do
  .venv/bin/python main.py || exit 1
  echo "Перезапуск через 10 секунд. Выйти — Ctrl+C."
  sleep 10
done
