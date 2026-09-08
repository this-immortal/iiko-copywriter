#!/usr/bin/env bash
# Обёртка: вся логика в install.py.  Пример: deploy/install.sh 1.2.3.4 -p 'пароль'
exec python3 "$(dirname "$0")/install.py" "$@"
