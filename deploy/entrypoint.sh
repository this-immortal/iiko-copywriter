#!/usr/bin/env bash
# Супервизор внутри контейнера: venv, запуск бота, обновление по коду 75, откат.
set -u

REPO=${GIT_REPO_DIR:-/app/repo}
DATA=${DATA_DIR:-/work/data}
BRANCH=${GIT_BRANCH:-main}
STABLE_SEC=${STABLE_SEC:-90}
VENV="$DATA/venv"

export HOME="$DATA/home"
mkdir -p "$HOME" "$DATA/uploads" "$DATA/outputs"
export GIT_SSH_COMMAND="ssh -i /run/secrets/deploy_key -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$DATA/known_hosts"
git config --global --add safe.directory '*' 2>/dev/null || true

log() { echo "[entrypoint $(date +%H:%M:%S)] $*"; }

write_state() { # event commit prev error
  python3 - "$@" > "$DATA/state.json" <<'PY'
import json, sys
e, c, p, err = (sys.argv[1:] + ["", "", "", ""])[:4]
print(json.dumps({"event": e, "commit": c, "prev": p, "error": err}, ensure_ascii=False))
PY
}

ensure_venv() {
  if [ ! -x "$VENV/bin/python" ]; then
    log "создаю venv"
    python3 -m venv "$VENV" || return 1
  fi
  local want have
  want=$(sha256sum "$REPO/requirements.txt" | cut -d' ' -f1)
  have=$(cat "$VENV/.req_hash" 2>/dev/null || true)
  if [ "$want" != "$have" ]; then
    log "ставлю зависимости"
    "$VENV/bin/pip" install -q --upgrade pip \
      && "$VENV/bin/pip" install -q -r "$REPO/requirements.txt" \
      && echo "$want" > "$VENV/.req_hash" \
      || return 1
  fi
}

while true; do
  commit=$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo unknown)
  start=$(date +%s)
  if ensure_venv; then
    log "запускаю бота @ $commit"
    ( cd "$REPO" && exec "$VENV/bin/python" -m bot ); rc=$?
  else
    log "venv не собрался"; rc=1
  fi
  ran=$(( $(date +%s) - start ))
  log "бот завершился rc=$rc через ${ran}s"

  if [ "$rc" -eq 75 ]; then
    if git -C "$REPO" fetch -q origin "$BRANCH" && git -C "$REPO" reset -q --hard "origin/$BRANCH"; then
      new=$(git -C "$REPO" rev-parse --short HEAD)
      echo "$commit" > "$DATA/prev_commit"
      touch "$DATA/just_updated"
      write_state updated "$new" "$commit" ""
      log "обновился $commit → $new"
    else
      write_state update_failed "$commit" "" "git fetch/reset не прошёл"
      log "обновление не удалось"
    fi
    continue
  fi

  if [ -f "$DATA/just_updated" ]; then
    if [ "$rc" -ne 0 ] && [ "$ran" -lt "$STABLE_SEC" ]; then
      prev=$(cat "$DATA/prev_commit" 2>/dev/null || echo "")
      bad=$(git -C "$REPO" rev-parse --short HEAD)
      if [ -n "$prev" ] && git -C "$REPO" reset -q --hard "$prev"; then
        write_state rolled_back "$prev" "$bad" "код $rc через ${ran}s"
        log "откатился $bad → $prev"
      else
        write_state update_failed "$bad" "" "откат не удался"
      fi
      rm -f "$DATA/just_updated"
      sleep 3
      continue
    fi
    rm -f "$DATA/just_updated"
  fi

  [ "$rc" -eq 0 ] && exit 0
  sleep 10
done
