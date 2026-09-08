#!/usr/bin/env bash
# model-guard shared helpers, sourced by guard-hook.sh and recover.sh.
# Requires bash 4+ and jq. Everything is namespaced mg_*.
#
# Config: ~/.claude/model-guard.conf (KEY=VALUE per line). Recovery keys:
#   RECOVER=on|off              master switch for the hooks (default on)
#   RECOVER_MODEL=<model id>    model to switch to after an automatic downgrade
#                               (default claude-opus-5[1m])
#   RECOVER_EFFORT=<level|off>  effort applied on the recovery model (default max)
#   RECOVER_PROMPT=<text>       prompt sent to resume the interrupted task
#                               (default: "继续" for zh, "Continue." otherwise)
#   RECOVER_CHANNEL=auto|tmux|zellij|kitty|dryrun|none
#                               how keystrokes reach the session (default auto:
#                               tmux pane, then zellij pane, then kitty remote
#                               control)
#   RECOVER_MAX=<n>             automatic recoveries per session (default 3)
#   DEBUG=true                  append every hook input to <state dir>/debug.log
#
# State: one JSON file per session under $XDG_RUNTIME_DIR/model-guard
# (override with MODEL_GUARD_STATE_DIR). status is one of
#   pending    downgraded with a keystroke channel; the recovery driver is starting
#   switching  the recovery driver is typing the model switch
#   recovered  the session model changed after the downgrade (driver or by hand)
#   stopped    downgraded, no automatic switch: the turn is stopped once
#              (turn_stopped) and the hooks stay out of the way afterwards;
#              note says why (no_channel, target_flagged, too_many_recoveries,
#              downgraded_again, target_not_stronger, switch_not_observed)

MG_VERSION="1.3.0"
MG_CONF="${MODEL_GUARD_CONF:-$HOME/.claude/model-guard.conf}"
MG_SETTINGS="${MODEL_GUARD_SETTINGS:-$HOME/.claude/settings.json}"
MG_STATE_DIR="${MODEL_GUARD_STATE_DIR:-${XDG_RUNTIME_DIR:-${TMPDIR:-/tmp}}/model-guard}"
MG_SESSIONS_DIR="${MODEL_GUARD_SESSIONS_DIR:-$HOME/.claude/sessions}"

mg_conf_get() {
  [ -f "$MG_CONF" ] || return 0
  sed -n "s/^[[:space:]]*$1=//p" "$MG_CONF" | tail -n1 | tr -d '" '
}

mg_conf_or() {
  local v
  v=$(mg_conf_get "$1")
  printf '%s' "${v:-$2}"
}

mg_debug() {
  [ "$(mg_conf_get DEBUG)" = true ] || return 0
  mkdir -p "$MG_STATE_DIR"
  printf '%s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$*" >> "$MG_STATE_DIR/debug.log"
}

# ---- language (same resolution as the statusline) ----
mg_lang() {
  local lang settings_lang
  lang=$(mg_conf_get LANGUAGE)
  [ "${lang:-auto}" = auto ] && lang=""
  if [ -z "$lang" ]; then
    settings_lang=$(jq -r '.language // empty' "$MG_SETTINGS" 2>/dev/null || true)
    case "$(printf '%s' "$settings_lang" | tr '[:upper:]' '[:lower:]')" in
      *chinese*|*中文*|zh|zh[-_]*)     lang=zh;;
      *japanese*|*日本語*|ja|ja[-_]*)  lang=ja;;
      *korean*|*한국*|ko|ko[-_]*)      lang=ko;;
      *spanish*|*español*|es|es[-_]*)  lang=es;;
      *french*|*français*|fr|fr[-_]*)  lang=fr;;
      *german*|*deutsch*|de|de[-_]*)   lang=de;;
      *portug*|pt|pt[-_]*)             lang=pt;;
      *)                               lang=en;;
    esac
  fi
  printf '%s' "$lang"
}

# ---- model identity ----
mg_strip_1m() { printf '%s' "$1" | sed 's/\[1[mM]\]//g'; }

# Strength score: family rank * 1000 + major * 100 + minor.
# fable/mythos > opus > sonnet > haiku; unknown family scores 0.
# claude-opus-4-8 -> 3408, claude-opus-5 -> 3500, claude-fable-5-1[1m] -> 4501.
mg_model_score() {
  local id fam=0 rest major=0 minor=0
  id=$(mg_strip_1m "$1" | tr '[:upper:]' '[:lower:]')
  case "$id" in
    *fable*|*mythos*) fam=4;;
    *opus*)           fam=3;;
    *sonnet*)         fam=2;;
    *haiku*)          fam=1;;
    *)                printf '0'; return;;
  esac
  rest=$(printf '%s' "$id" | sed -E 's/^.*(fable|mythos|opus|sonnet|haiku)-?//')
  if [[ "$rest" =~ ^([0-9]+)(-([0-9]{1,2}))? ]]; then
    major=${BASH_REMATCH[1]}
    minor=${BASH_REMATCH[3]:-0}
  fi
  printf '%d' $((fam * 1000 + major * 100 + minor))
}

# True when TO is weaker than FROM. Unknown FROM never counts as a downgrade;
# unknown TO always does (it cannot be proven stronger).
mg_is_downgrade() {
  local sf st
  sf=$(mg_model_score "$1"); st=$(mg_model_score "$2")
  [ "$sf" -gt 0 ] || return 1
  [ "$st" -gt 0 ] || return 0
  [ "$st" -lt "$sf" ]
}

mg_same_model() {
  [ "$(mg_strip_1m "$1" | tr '[:upper:]' '[:lower:]')" = "$(mg_strip_1m "$2" | tr '[:upper:]' '[:lower:]')" ]
}

# "claude-opus-4-8" -> "Opus 4.8", "claude-opus-5[1m]" -> "Opus 5 (1M)".
mg_display_name() {
  local id base fam ver one_m=""
  id="$1"
  case "$id" in *\[1[mM]\]*) one_m=" (1M)";; esac
  base=$(mg_strip_1m "$id" | tr '[:upper:]' '[:lower:]')
  if [[ "$base" =~ (fable|mythos|opus|sonnet|haiku)-?([0-9]+(-[0-9]{1,2})?) ]]; then
    fam=${BASH_REMATCH[1]}; ver=${BASH_REMATCH[2]//-/.}
    printf '%s %s%s' "${fam^}" "$ver" "$one_m"
  else
    printf '%s' "$id"
  fi
}

mg_settings_model() { jq -r '.model // empty' "$MG_SETTINGS" 2>/dev/null || true; }

# ---- per-session state ----
mg_state_file() { printf '%s/%s.json' "$MG_STATE_DIR" "$1"; }
mg_state_read() { cat "$(mg_state_file "$1")" 2>/dev/null || printf '{}'; }
mg_state_get() { mg_state_read "$1" | jq -r --arg k "$2" 'if has($k) and .[$k] != null then .[$k] else empty end'; }

# mg_state_update SID JQ_FILTER [jq args...]: read-modify-write under a lock.
mg_state_update() {
  local sid="$1" filter="$2"; shift 2
  mkdir -p "$MG_STATE_DIR"; chmod 700 "$MG_STATE_DIR" 2>/dev/null || true
  local f lock tmp
  f=$(mg_state_file "$sid"); lock="$f.lock"; tmp="$f.tmp.$$"
  (
    flock -w 5 9 || exit 1
    mg_state_read "$sid" | jq "$@" "$filter" > "$tmp" && mv "$tmp" "$f"
  ) 9>"$lock"
}

mg_state_clear() {
  local f
  f=$(mg_state_file "$1")
  rm -f "$f" "$f.lock" "$f.tmp."* 2>/dev/null || true
}

# ---- session registry (Claude Code's own ~/.claude/sessions/<pid>.json) ----
mg_session_registry_file() {
  local sid="$1" f
  for f in "$MG_SESSIONS_DIR"/*.json; do
    [ -f "$f" ] || continue
    if [ "$(jq -r '.sessionId // empty' "$f" 2>/dev/null)" = "$sid" ]; then
      printf '%s' "$f"; return 0
    fi
  done
  return 1
}

mg_session_status() {
  local f
  f=$(mg_session_registry_file "$1") || return 1
  jq -r '.status // empty' "$f" 2>/dev/null
}

# ---- keystroke channel ----
mg_kitten() {
  local k
  if k=$(command -v kitten 2>/dev/null); then printf '%s' "$k"; return 0; fi
  k=$(command -v kitty 2>/dev/null) || return 1
  k=$(readlink -f "$k")
  [ -x "$(dirname "$k")/kitten" ] || return 1
  printf '%s' "$(dirname "$k")/kitten"
}

# The zellij pane this process runs in, as an "action --pane-id" target.
# Fails when the id is absent or not numeric: without a proven target the
# channel must stay unavailable rather than type into someone else's pane.
mg_zellij_pane() {
  case "${ZELLIJ_PANE_ID:-}" in
    ""|*[!0-9]*) return 1;;
    *)           printf 'terminal_%s' "$ZELLIJ_PANE_ID";;
  esac
}

# The keystroke channel for the session this hook runs in. Inner multiplexers
# win over the outer terminal: they address one pane by id, while kitty remote
# control reaches a window whose focused pane may be a different session.
mg_channel() {
  local want
  want=$(mg_conf_or RECOVER_CHANNEL auto)
  case "$want" in
    none|off|false) printf 'none'; return;;
    dryrun)         printf 'dryrun'; return;;
  esac
  if [ "$want" = auto ] || [ "$want" = tmux ]; then
    if [ -n "${TMUX:-}" ] && [ -n "${TMUX_PANE:-}" ] && command -v tmux >/dev/null 2>&1; then
      printf 'tmux'; return
    fi
  fi
  if [ "$want" = auto ] || [ "$want" = zellij ]; then
    if [ -n "${ZELLIJ_SESSION_NAME:-}" ] && mg_zellij_pane >/dev/null 2>&1 && \
       command -v zellij >/dev/null 2>&1; then
      printf 'zellij'; return
    fi
  fi
  if [ "$want" = auto ] || [ "$want" = kitty ]; then
    if [ -n "${KITTY_LISTEN_ON:-}" ] && [ -n "${KITTY_WINDOW_ID:-}" ] && mg_kitten >/dev/null 2>&1; then
      printf 'kitty'; return
    fi
  fi
  printf 'none'
}

# ---- user-facing text ----
# mg_text KEY [printf args...]
mg_text() {
  local key="$1"; shift
  local lang fmt
  lang=$(mg_lang)
  case "$lang:$key" in
    zh:stop)        fmt="🚨 model-guard：%s 被 flag，会话被降到 %s，已停止。";;
    zh:tail_switch) fmt="正在自动切到 %s…";;
    zh:tail_manual) fmt="请 /model 切到 %s 后重发。";;
    zh:tail_halted) fmt="%s 也会被 flag，不再自动切换，请 /model 自选。";;
    zh:block_wait)  fmt="🚨 model-guard：正在从 %s 自动切到 %s，请稍等；若 30 秒内没切成功，/model 手动切。";;
    zh:band_switch) fmt="🚨 被 flag：%s → %s · 自动切回 %s 中…";;
    zh:band_manual) fmt="🚨 被 flag：%s → %s · 已停 · /model 切到 %s";;
    zh:band_halted) fmt="🚨 被 flag 降到 %s · 已停 · /model 自选";;
    zh:band_recov)  fmt="🔁 %s 被 flag → 已切到 %s";;
    zh:notify_t)    fmt="model-guard：模型被 flag 降级";;
    zh:notify_go)   fmt="%s → %s，已停止，正在切到 %s 并继续";;
    zh:notify_done) fmt="已切到 %s，任务已继续";;
    zh:notify_fail) fmt="切到 %s 没有成功（%s），会话保持停止";;
    zh:notify_stop) fmt="%s → %s，已停止；%s";;
    zh:prompt)      fmt="继续";;
    ja:stop)        fmt="🚨 model-guard：%s がフラグされ、セッションは %s に格下げされました。停止しました。";;
    ja:tail_switch) fmt="%s へ自動で切り替え中…";;
    ja:tail_manual) fmt="/model で %s に切り替えてから再送してください。";;
    ja:tail_halted) fmt="%s もフラグ対象のため自動切替しません。/model で選んでください。";;
    ja:block_wait)  fmt="🚨 model-guard：%s から %s へ自動切替中です。30 秒で切り替わらなければ /model で手動切替。";;
    ja:band_switch) fmt="🚨 フラグ：%s → %s · %s へ自動切替中…";;
    ja:band_manual) fmt="🚨 フラグ：%s → %s · 停止 · /model で %s へ";;
    ja:band_halted) fmt="🚨 フラグで %s に格下げ · 停止 · /model で選択";;
    ja:band_recov)  fmt="🔁 %s がフラグ → %s に切替済み";;
    ja:notify_t)    fmt="model-guard：モデルが格下げ";;
    ja:notify_go)   fmt="%s → %s、停止。%s へ切替して続行します";;
    ja:notify_done) fmt="%s に切替、タスク再開";;
    ja:notify_fail) fmt="%s への切替失敗（%s）、停止のまま";;
    ja:notify_stop) fmt="%s → %s、停止；%s";;
    ja:prompt)      fmt="続けて";;
    ko:stop)        fmt="🚨 model-guard: %s 이(가) 플래그되어 세션이 %s (으)로 강등되었습니다. 중지됨.";;
    ko:tail_switch) fmt="%s (으)로 자동 전환 중…";;
    ko:tail_manual) fmt="/model 로 %s (으)로 바꾼 뒤 다시 보내세요.";;
    ko:tail_halted) fmt="%s 도 플래그 대상이라 자동 전환하지 않습니다. /model 로 고르세요.";;
    ko:block_wait)  fmt="🚨 model-guard: %s → %s 자동 전환 중입니다. 30초 안에 안 되면 /model 로 수동 전환.";;
    ko:band_switch) fmt="🚨 플래그: %s → %s · %s (으)로 자동 전환 중…";;
    ko:band_manual) fmt="🚨 플래그: %s → %s · 중지 · /model 로 %s";;
    ko:band_halted) fmt="🚨 플래그로 %s 강등 · 중지 · /model 로 선택";;
    ko:band_recov)  fmt="🔁 %s 플래그 → %s 로 전환됨";;
    ko:notify_t)    fmt="model-guard: 모델 강등";;
    ko:notify_go)   fmt="%s → %s, 중지. %s 로 전환 후 계속";;
    ko:notify_done) fmt="%s 로 전환, 작업 재개";;
    ko:notify_fail) fmt="%s 전환 실패 (%s), 중지 유지";;
    ko:notify_stop) fmt="%s → %s, 중지; %s";;
    ko:prompt)      fmt="계속";;
    es:stop)        fmt="🚨 model-guard: %s fue marcado y la sesión bajó a %s. Detenido.";;
    es:tail_switch) fmt="Cambiando automáticamente a %s…";;
    es:tail_manual) fmt="Cambia a %s con /model y reenvía.";;
    es:tail_halted) fmt="%s también sería marcado; sin cambio automático: elige con /model.";;
    es:block_wait)  fmt="🚨 model-guard: cambiando de %s a %s; espera. Si no cambia en 30 s, usa /model.";;
    es:band_switch) fmt="🚨 marcado: %s → %s · cambiando a %s…";;
    es:band_manual) fmt="🚨 marcado: %s → %s · detenido · /model a %s";;
    es:band_halted) fmt="🚨 marcado, bajado a %s · detenido · elige con /model";;
    es:band_recov)  fmt="🔁 %s marcado → ahora en %s";;
    es:notify_t)    fmt="model-guard: modelo degradado";;
    es:notify_go)   fmt="%s → %s, detenido. Cambiando a %s y continuando";;
    es:notify_done) fmt="Cambiado a %s, tarea reanudada";;
    es:notify_fail) fmt="No se pudo cambiar a %s (%s); sigue detenido";;
    es:notify_stop) fmt="%s → %s, detenido; %s";;
    es:prompt)      fmt="Continúa.";;
    fr:stop)        fmt="🚨 model-guard : %s a été signalé, la session est passée à %s. Arrêt.";;
    fr:tail_switch) fmt="Bascule automatique vers %s…";;
    fr:tail_manual) fmt="Passe à %s avec /model puis renvoie.";;
    fr:tail_halted) fmt="%s serait aussi signalé ; pas de bascule automatique : choisis avec /model.";;
    fr:block_wait)  fmt="🚨 model-guard : bascule de %s vers %s en cours ; patiente. Sans succès en 30 s, utilise /model.";;
    fr:band_switch) fmt="🚨 signalé : %s → %s · bascule vers %s…";;
    fr:band_manual) fmt="🚨 signalé : %s → %s · arrêté · /model vers %s";;
    fr:band_halted) fmt="🚨 signalé, rétrogradé à %s · arrêté · choisis avec /model";;
    fr:band_recov)  fmt="🔁 %s signalé → passé à %s";;
    fr:notify_t)    fmt="model-guard : modèle rétrogradé";;
    fr:notify_go)   fmt="%s → %s, arrêté. Bascule vers %s puis reprise";;
    fr:notify_done) fmt="Passé à %s, tâche reprise";;
    fr:notify_fail) fmt="Bascule vers %s échouée (%s) ; toujours arrêté";;
    fr:notify_stop) fmt="%s → %s, arrêté ; %s";;
    fr:prompt)      fmt="Continue.";;
    de:stop)        fmt="🚨 model-guard: %s wurde markiert, die Sitzung ist auf %s herabgestuft. Gestoppt.";;
    de:tail_switch) fmt="Wechsle automatisch zu %s…";;
    de:tail_manual) fmt="Mit /model zu %s wechseln und erneut senden.";;
    de:tail_halted) fmt="%s würde ebenfalls markiert; kein automatischer Wechsel: mit /model wählen.";;
    de:block_wait)  fmt="🚨 model-guard: Wechsel von %s zu %s läuft; bitte warten. Klappt es nicht in 30 s, /model verwenden.";;
    de:band_switch) fmt="🚨 markiert: %s → %s · Wechsel zu %s…";;
    de:band_manual) fmt="🚨 markiert: %s → %s · gestoppt · /model zu %s";;
    de:band_halted) fmt="🚨 markiert, herabgestuft auf %s · gestoppt · mit /model wählen";;
    de:band_recov)  fmt="🔁 %s markiert → gewechselt zu %s";;
    de:notify_t)    fmt="model-guard: Modell herabgestuft";;
    de:notify_go)   fmt="%s → %s, gestoppt. Wechsel zu %s, dann weiter";;
    de:notify_done) fmt="Gewechselt zu %s, Aufgabe fortgesetzt";;
    de:notify_fail) fmt="Wechsel zu %s fehlgeschlagen (%s); bleibt gestoppt";;
    de:notify_stop) fmt="%s → %s, gestoppt; %s";;
    de:prompt)      fmt="Weiter.";;
    pt:stop)        fmt="🚨 model-guard: %s foi sinalizado e a sessão caiu para %s. Parado.";;
    pt:tail_switch) fmt="Trocando automaticamente para %s…";;
    pt:tail_manual) fmt="Troque para %s com /model e reenvie.";;
    pt:tail_halted) fmt="%s também seria sinalizado; sem troca automática: escolha com /model.";;
    pt:block_wait)  fmt="🚨 model-guard: trocando de %s para %s; aguarde. Se não trocar em 30 s, use /model.";;
    pt:band_switch) fmt="🚨 sinalizado: %s → %s · trocando para %s…";;
    pt:band_manual) fmt="🚨 sinalizado: %s → %s · parado · /model para %s";;
    pt:band_halted) fmt="🚨 sinalizado, rebaixado para %s · parado · escolha com /model";;
    pt:band_recov)  fmt="🔁 %s sinalizado → agora em %s";;
    pt:notify_t)    fmt="model-guard: modelo rebaixado";;
    pt:notify_go)   fmt="%s → %s, parado. Trocando para %s e continuando";;
    pt:notify_done) fmt="Trocado para %s, tarefa retomada";;
    pt:notify_fail) fmt="Troca para %s falhou (%s); segue parado";;
    pt:notify_stop) fmt="%s → %s, parado; %s";;
    pt:prompt)      fmt="Continue.";;
    *:stop)         fmt="🚨 model-guard: %s was flagged and the session was downgraded to %s. Stopped.";;
    *:tail_switch)  fmt="Switching to %s automatically…";;
    *:tail_manual)  fmt="Switch to %s with /model and resend.";;
    *:tail_halted)  fmt="%s would be flagged too, so no automatic switch: pick one with /model.";;
    *:block_wait)   fmt="🚨 model-guard: switching from %s to %s, hold on. If it has not switched within 30 s, use /model.";;
    *:band_switch)  fmt="🚨 FLAGGED: %s → %s · switching to %s…";;
    *:band_manual)  fmt="🚨 FLAGGED: %s → %s · stopped · /model to %s";;
    *:band_halted)  fmt="🚨 FLAGGED, downgraded to %s · stopped · pick one with /model";;
    *:band_recov)   fmt="🔁 %s flagged → switched to %s";;
    *:notify_t)     fmt="model-guard: model downgraded";;
    *:notify_go)    fmt="%s → %s, stopped. Switching to %s and continuing";;
    *:notify_done)  fmt="Switched to %s, task resumed";;
    *:notify_fail)  fmt="Switch to %s failed (%s); still stopped";;
    *:notify_stop)  fmt="%s → %s, stopped; %s";;
    *:prompt)       fmt="Continue.";;
  esac
  # shellcheck disable=SC2059
  printf "$fmt" "$@"
}

# mg_notify TITLE BODY [urgency]: desktop notice when notify-send exists.
mg_notify() {
  command -v notify-send >/dev/null 2>&1 || return 0
  notify-send -a model-guard -u "${3:-normal}" "$1" "$2" >/dev/null 2>&1 || true
}

# ---- default-model restore ----
# "/model <id>" in an interactive session also saves <id> as the user's default
# model in settings.json. When the switch was typed by the recovery driver that
# side effect is unwanted: this puts the previously saved default back once
# Claude Code's asynchronous settings write has landed.
mg_restore_default_model() {
  local sid="$1" state want target cur="" i tmp
  state=$(mg_state_read "$sid")
  want=$(jq -r '.default_model // empty' <<<"$state")
  target=$(jq -r '.target_model // empty' <<<"$state")
  [ -n "$want" ] && [ -n "$target" ] || return 0
  [ "$(jq -r '.recovered_by // empty' <<<"$state")" = auto ] || return 0
  mg_same_model "$want" "$target" && return 0
  for i in $(seq 1 30); do
    cur=$(mg_settings_model)
    mg_same_model "$cur" "$target" && break
    sleep 0.1
  done
  mg_same_model "$cur" "$target" || return 0
  tmp="$MG_SETTINGS.mg-tmp.$$"
  if jq --arg m "$want" '.model=$m' "$MG_SETTINGS" > "$tmp" && mv "$tmp" "$MG_SETTINGS"; then
    mg_state_update "$sid" '.default_restored=true'
    mg_debug "restored settings model $cur -> $want"
  else
    rm -f "$tmp"
  fi
}
