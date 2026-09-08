#!/usr/bin/env bash
# Разовая подготовка VPS под root: podman, пользователь бота, linger, ssh-ключ с ноутбука.
# Запускается из install.py под root по паролю. Ubuntu 22.04+ / Debian 12+.
set -euo pipefail

BOT_USER=${BOT_USER:-iiko_copywriter}
PUBKEY=${PUBKEY:-}   # публичный ключ ноутбука, чтобы можно было зайти ssh $BOT_USER@host; необязательно

export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a
apt-get update -q
apt-get install -y -q podman git uidmap slirp4netns fuse-overlayfs dbus-user-session

if ! id -u "$BOT_USER" >/dev/null 2>&1; then
  useradd -m -s /bin/bash "$BOT_USER"
fi
if ! grep -q "^$BOT_USER:" /etc/subuid 2>/dev/null; then
  usermod --add-subuids 200000-265535 --add-subgids 200000-265535 "$BOT_USER"
fi
loginctl enable-linger "$BOT_USER"

if [ -n "$PUBKEY" ]; then
  HOME_DIR=$(getent passwd "$BOT_USER" | cut -d: -f6)
  install -d -m 700 -o "$BOT_USER" -g "$BOT_USER" "$HOME_DIR/.ssh"
  touch "$HOME_DIR/.ssh/authorized_keys"
  grep -qxF "$PUBKEY" "$HOME_DIR/.ssh/authorized_keys" || echo "$PUBKEY" >> "$HOME_DIR/.ssh/authorized_keys"
  chmod 600 "$HOME_DIR/.ssh/authorized_keys"
  chown "$BOT_USER:$BOT_USER" "$HOME_DIR/.ssh/authorized_keys"
fi

echo "bootstrap готов: пользователь $BOT_USER, podman $(podman --version | awk '{print $3}')"
