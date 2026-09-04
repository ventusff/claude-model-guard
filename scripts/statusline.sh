#!/usr/bin/env bash
# model-guard — a Claude Code statusline that catches silent model downgrades.
# https://github.com/ventusff/claude-model-guard
#
# One full-width, theme-proof color band: model + reasoning effort + context + account.
#   green ✔   actual model matches what this machine expects
#   blue  ⬆   actual model is ABOVE your default (gentle FYI, no alarm)
#   red   🚨  actual model is BELOW your default (silent downgrade) — full-width alarm
#   blue  ●   no expectation configured — neutral display
# Red inline patches for the other silent downgrades: reasoning effort lowered below
# settings.json "effortLevel", extended thinking switched off, and a heads-up when the
# 5-hour rate-limit window fills up (which is exactly when forced fallbacks happen).
#
# Expected-model resolution (first hit wins):
#   1. EXPECTED_MODEL in ~/.claude/model-guard.conf   (grep -Ei pattern, manual override)
#   2. ~/.claude/statusline-expected-model            (legacy override file)
#   3. "model" in ~/.claude/settings.json             ("[1m]"-style suffix stripped;
#                                                      "default" counts as no expectation)
# Model strength: family fable/mythos > opus > sonnet > haiku, then version
# (claude-opus-5 > claude-opus-4-8). Unknown ids score 0 and always alarm.
# Effort strength: xhigh(4) > high(3) > medium(2) > low(1).
#
# Colors are truecolor, with a fixed 256-color-cube fallback when COLORTERM says no.
# Plain ANSI 16-color codes get remapped by terminal themes and the contrast collapses
# (red turns pink). All three fg/bg pairs are WCAG >= 7:1 (AAA):
#   OK    #000000 on #3FB950 = 8.3:1    ALARM #FFFFFF on #B00020 = 7.3:1
#   INFO  #FFFFFF on #0D47A1 = 8.6:1    RECOV #000000 on #FFB300 = 11.4:1
#
# Recovery episodes (plugin hooks, see lib.sh) are read from the per-session state
# file under $XDG_RUNTIME_DIR/model-guard and get their own band:
#   red    🚨 downgraded by a flag: stopped, or switching to the recovery model
#   amber  🔁 recovered: running on the recovery model after a flag
#
# Config (~/.claude/model-guard.conf, KEY=VALUE per line, everything optional):
#   LANGUAGE=auto|en|zh|ja|ko|es|fr|de|pt   band language; auto follows the "language"
#                                           key in ~/.claude/settings.json, else English
#   EXPECTED_MODEL=<grep -Ei pattern>       override expected-model auto-detection
#   SHOW_ACCOUNT=true|false                 show logged-in account email (default true)
#   SHOW_CONTEXT=true|false                 show context-window usage % (default true)
#   LIMIT_WARN_AT=<0-100|off>               red patch when 5h rate-limit usage >= N
#                                           (default 80; "off" disables)
#
# Debug: add   printf '%s' "$input" > ~/.claude/model-guard-last-input.json
# right after the `input=$(cat ...)` line to inspect the full stdin payload
# (model / effort / thinking / context_window / rate_limits / fast_mode / ...).

MG_VERSION="1.1.1"
set -u
input=$(cat 2>/dev/null || true)

CONF="${MODEL_GUARD_CONF:-$HOME/.claude/model-guard.conf}"
SETTINGS="${MODEL_GUARD_SETTINGS:-$HOME/.claude/settings.json}"
STATE_DIR="${MODEL_GUARD_STATE_DIR:-${XDG_RUNTIME_DIR:-${TMPDIR:-/tmp}}/model-guard}"
conf_get() {
  [ -f "$CONF" ] || return 0
  sed -n "s/^[[:space:]]*$1=//p" "$CONF" | tail -n1 | tr -d '" '
}

if command -v jq >/dev/null 2>&1; then
  session_id=$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null || true)
  model_id=$(printf '%s' "$input" | jq -r '.model.id // "unknown"' 2>/dev/null || echo unknown)
  model_name=$(printf '%s' "$input" | jq -r '.model.display_name // .model.id // "unknown"' 2>/dev/null || echo unknown)
  effort_level=$(printf '%s' "$input" | jq -r '.effort.level // empty' 2>/dev/null || true)
  thinking_off=$(printf '%s' "$input" | jq -r 'if .thinking.enabled == false then "1" else "" end' 2>/dev/null || true)
  ctx_pct=$(printf '%s' "$input" | jq -r '.context_window.used_percentage // empty | if type=="number" then floor else empty end' 2>/dev/null || true)
  limit_pct=$(printf '%s' "$input" | jq -r '.rate_limits.five_hour.used_percentage // empty | if type=="number" then floor else empty end' 2>/dev/null || true)
  email=$(jq -r '.oauthAccount.emailAddress // empty' "$HOME/.claude.json" 2>/dev/null || true)
  settings_lang=$(jq -r '.language // empty' "$SETTINGS" 2>/dev/null || true)
  expected_effort=$(jq -r '.effortLevel // empty' "$SETTINGS" 2>/dev/null || true)
  state=""
  [ -n "$session_id" ] && state=$(cat "$STATE_DIR/$session_id.json" 2>/dev/null || true)
else
  session_id=""; state=""
  model_id=unknown; model_name=unknown; effort_level=""; thinking_off=""
  ctx_pct=""; limit_pct=""; email=""; settings_lang=""; expected_effort=""
fi

# ---- language: conf override > Claude Code "language" setting > English ----
lang=$(conf_get LANGUAGE)
[ "${lang:-auto}" = auto ] && lang=""
if [ -z "$lang" ]; then
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

case "$lang" in
  zh) T_DOWN="🚨🚨🚨 模型被降级!当前: %s (%s) < %s"; T_BACK="立刻 /model 切回!"
      T_UP="⬆ 强于默认:当前 %s · %s(默认 %s)"
      T_EFF="⚡%s < 默认%s!"; T_THINK="🧠思考OFF!"; T_LIMIT="⏳5h额度 %s%%!"
      T_ACCT="账号未知(API key?)"
      T_SWITCH="🚨 被 flag:%s → %s · 自动切回 %s 中…"; T_MANUAL="🚨 被 flag:%s → %s · 已停 · /model 切到 %s"
      T_HALTED="🚨 被 flag 降到 %s · 已停 · /model 自选"
      T_RECOV="🔁 %s 被 flag → 已切到 %s";;
  ja) T_DOWN="🚨🚨🚨 モデルがダウングレード!現在: %s (%s) < %s"; T_BACK="今すぐ /model で戻して!"
      T_UP="⬆ デフォルトより上位: %s · %s(デフォルト %s)"
      T_EFF="⚡%s < デフォルト%s!"; T_THINK="🧠思考OFF!"; T_LIMIT="⏳5h上限 %s%%!"
      T_ACCT="アカウント不明(API key?)"
      T_SWITCH="🚨 フラグ:%s → %s · %s へ自動切替中…"; T_MANUAL="🚨 フラグ:%s → %s · 停止 · /model で %s へ"
      T_HALTED="🚨 フラグで %s に格下げ · 停止 · /model で選択"
      T_RECOV="🔁 %s がフラグ → %s に切替済み";;
  ko) T_DOWN="🚨🚨🚨 모델 다운그레이드! 현재: %s (%s) < %s"; T_BACK="지금 /model 로 되돌리세요!"
      T_UP="⬆ 기본보다 상위: %s · %s (기본 %s)"
      T_EFF="⚡%s < 기본 %s!"; T_THINK="🧠사고 OFF!"; T_LIMIT="⏳5h한도 %s%%!"
      T_ACCT="계정 알 수 없음 (API key?)"
      T_SWITCH="🚨 플래그: %s → %s · %s (으)로 자동 전환 중…"; T_MANUAL="🚨 플래그: %s → %s · 중지 · /model 로 %s"
      T_HALTED="🚨 플래그로 %s 강등 · 중지 · /model 로 선택"
      T_RECOV="🔁 %s 플래그 → %s 로 전환됨";;
  es) T_DOWN="🚨🚨🚨 ¡MODELO DEGRADADO! ahora: %s (%s) < %s"; T_BACK="¡/model para volver YA!"
      T_UP="⬆ superior al predeterminado: %s · %s (predet.: %s)"
      T_EFF="¡⚡%s < predet. %s!"; T_THINK="🧠 ¡thinking OFF!"; T_LIMIT="¡⏳ límite 5h %s%%!"
      T_ACCT="cuenta desconocida (¿API key?)"
      T_SWITCH="🚨 marcado: %s → %s · cambiando a %s…"; T_MANUAL="🚨 marcado: %s → %s · detenido · /model a %s"
      T_HALTED="🚨 marcado, bajado a %s · detenido · elige con /model"
      T_RECOV="🔁 %s marcado → ahora en %s";;
  fr) T_DOWN="🚨🚨🚨 MODÈLE RÉTROGRADÉ ! actuel : %s (%s) < %s"; T_BACK="/model pour revenir !"
      T_UP="⬆ au-dessus du défaut : %s · %s (défaut : %s)"
      T_EFF="⚡%s < défaut %s !"; T_THINK="🧠 thinking OFF !"; T_LIMIT="⏳ limite 5h %s%% !"
      T_ACCT="compte inconnu (API key ?)"
      T_SWITCH="🚨 signalé : %s → %s · bascule vers %s…"; T_MANUAL="🚨 signalé : %s → %s · arrêté · /model vers %s"
      T_HALTED="🚨 signalé, rétrogradé à %s · arrêté · choisis avec /model"
      T_RECOV="🔁 %s signalé → passé à %s";;
  de) T_DOWN="🚨🚨🚨 MODELL HERABGESTUFT! jetzt: %s (%s) < %s"; T_BACK="sofort /model zurückwechseln!"
      T_UP="⬆ über Standard: %s · %s (Standard: %s)"
      T_EFF="⚡%s < Standard %s!"; T_THINK="🧠 Thinking AUS!"; T_LIMIT="⏳ 5h-Limit %s%%!"
      T_ACCT="Konto unbekannt (API key?)"
      T_SWITCH="🚨 markiert: %s → %s · Wechsel zu %s…"; T_MANUAL="🚨 markiert: %s → %s · gestoppt · /model zu %s"
      T_HALTED="🚨 markiert, herabgestuft auf %s · gestoppt · mit /model wählen"
      T_RECOV="🔁 %s markiert → gewechselt zu %s";;
  pt) T_DOWN="🚨🚨🚨 MODELO REBAIXADO! agora: %s (%s) < %s"; T_BACK="rode /model para voltar JÁ!"
      T_UP="⬆ acima do padrão: %s · %s (padrão: %s)"
      T_EFF="⚡%s < padrão %s!"; T_THINK="🧠 thinking OFF!"; T_LIMIT="⏳ limite 5h %s%%!"
      T_ACCT="conta desconhecida (API key?)"
      T_SWITCH="🚨 sinalizado: %s → %s · trocando para %s…"; T_MANUAL="🚨 sinalizado: %s → %s · parado · /model para %s"
      T_HALTED="🚨 sinalizado, rebaixado para %s · parado · escolha com /model"
      T_RECOV="🔁 %s sinalizado → agora em %s";;
  *)  T_DOWN="🚨🚨🚨 MODEL DOWNGRADED! now: %s (%s) < %s"; T_BACK="run /model to switch back NOW!"
      T_UP="⬆ above default: %s · %s (default: %s)"
      T_EFF="⚡%s < default %s!"; T_THINK="🧠 thinking OFF!"; T_LIMIT="⏳ 5h limit %s%%!"
      T_ACCT="account unknown (API key?)"
      T_SWITCH="🚨 FLAGGED: %s → %s · switching to %s…"; T_MANUAL="🚨 FLAGGED: %s → %s · stopped · /model to %s"
      T_HALTED="🚨 FLAGGED, downgraded to %s · stopped · pick one with /model"
      T_RECOV="🔁 %s flagged → switched to %s";;
esac

# ---- expected model ----
expected=$(conf_get EXPECTED_MODEL)
if [ -z "$expected" ] && [ -f "$HOME/.claude/statusline-expected-model" ]; then
  expected=$(head -n1 "$HOME/.claude/statusline-expected-model" | tr -d '[:space:]')
fi
if [ -z "$expected" ]; then
  cfg=$(jq -r '.model // empty' "$SETTINGS" 2>/dev/null || true)
  cfg=${cfg%%\[*}
  case "$cfg" in ""|default) ;; *) expected="$cfg";; esac
fi

strip_1m() { printf '%s' "$1" | sed 's/\[1[mM]\]//g'; }
# family rank * 1000 + major * 100 + minor; unknown family = 0
score_of() {
  local id fam=0 rest major=0 minor=0
  id=$(strip_1m "$1" | tr '[:upper:]' '[:lower:]')
  case "$id" in
    *fable*|*mythos*) fam=4;;
    *opus*)           fam=3;;
    *sonnet*)         fam=2;;
    *haiku*)          fam=1;;
    *)                printf '0'; return;;
  esac
  rest=$(printf '%s' "$id" | sed -E 's/^.*(fable|mythos|opus|sonnet|haiku)-?//')
  if [[ "$rest" =~ ^([0-9]+)(-([0-9]{1,2}))? ]]; then
    major=${BASH_REMATCH[1]}; minor=${BASH_REMATCH[3]:-0}
  fi
  printf '%d' $((fam * 1000 + major * 100 + minor))
}
# "claude-opus-4-8" -> "Opus 4.8", "claude-opus-5[1m]" -> "Opus 5 (1M)"
pretty() {
  local base fam ver one_m=""
  case "$1" in *\[1[mM]\]*) one_m=" (1M)";; esac
  base=$(strip_1m "$1" | tr '[:upper:]' '[:lower:]')
  if [[ "$base" =~ (fable|mythos|opus|sonnet|haiku)-?([0-9]+(-[0-9]{1,2})?) ]]; then
    fam=${BASH_REMATCH[1]}; ver=${BASH_REMATCH[2]//-/.}
    printf '%s %s%s' "${fam^}" "$ver" "$one_m"
  else
    printf '%s' "$1"
  fi
}
same_model() { [ "$(strip_1m "$1" | tr '[:upper:]' '[:lower:]')" = "$(strip_1m "$2" | tr '[:upper:]' '[:lower:]')" ]; }
eff_rank() {
  case "${1,,}" in
    xhigh) echo 4;; high) echo 3;; medium) echo 2;; low) echo 1;; *) echo 0;;
  esac
}

R=$'\033[0m'
case "${COLORTERM:-}" in
  truecolor|24bit)
    OK=$'\033[1;38;2;0;0;0;48;2;63;185;80m'         # black on #3FB950
    ALARM=$'\033[1;38;2;255;255;255;48;2;176;0;32m' # white on #B00020
    INFO=$'\033[1;38;2;255;255;255;48;2;13;71;161m' # white on #0D47A1
    RECOV=$'\033[1;38;2;0;0;0;48;2;255;179;0m'      # black on #FFB300
    ;;
  *)  # fixed 256-color-cube approximations (also theme-proof):
      # 16=#000 231=#fff 77=#5fd75f 124=#af0000 25=#005faf
    OK=$'\033[1;38;5;16;48;5;77m'
    ALARM=$'\033[1;38;5;231;48;5;124m'
    INFO=$'\033[1;38;5;231;48;5;25m'
    RECOV=$'\033[1;38;5;16;48;5;214m'
    ;;
esac

# ---- pick the band + main text ----
# A recovery episode (plugin hooks) overrides the plain model comparison.
is_alarm=""; band=""; head_txt=""
if [ -n "$state" ]; then
  st_status=$(printf '%s' "$state" | jq -r '.status // empty' 2>/dev/null || true)
  st_from=$(pretty "$(printf '%s' "$state" | jq -r '.from_model // empty')")
  st_to=$(pretty "$(printf '%s' "$state" | jq -r '.to_model // empty')")
  st_target=$(pretty "$(printf '%s' "$state" | jq -r '.target_model // empty')")
  st_note=$(printf '%s' "$state" | jq -r '.note // empty')
  st_recovered_to=$(printf '%s' "$state" | jq -r '.recovered_to // empty')
  case "$st_status" in
    pending|switching) band=$ALARM; is_alarm=1; printf -v head_txt "$T_SWITCH" "$st_from" "$st_to" "$st_target";;
    stopped)   band=$ALARM; is_alarm=1
               case "$st_note" in
                 target_flagged|downgraded_again|too_many_recoveries|target_not_stronger)
                   printf -v head_txt "$T_HALTED" "$st_to";;
                 *) printf -v head_txt "$T_MANUAL" "$st_from" "$st_to" "$st_target";;
               esac;;
    recovered) if same_model "$model_id" "$st_recovered_to"; then
                 band=$RECOV; printf -v head_txt "$T_RECOV" "$st_from" "$(pretty "$st_recovered_to")"
               fi;;
  esac
fi
if [ -z "$band" ]; then
  if [ -z "$expected" ]; then
    band=$INFO; head_txt="● ${model_name} · ${model_id}"
  elif printf '%s' "$model_id" | grep -qiE -- "$expected"; then
    band=$OK; head_txt="✔ ${model_name} · ${model_id}"
  else
    as=$(score_of "$model_id"); es=$(score_of "$expected")
    if [ "$as" -gt 0 ] && [ "$es" -gt 0 ] && [ "$as" -gt "$es" ]; then
      band=$INFO
      printf -v head_txt "$T_UP" "$model_name" "$model_id" "${expected^^}"
    else
      band=$ALARM; is_alarm=1
      printf -v head_txt "$T_DOWN" "$model_name" "$model_id" "${expected^^}"
    fi
  fi
fi

# ---- effort / thinking / context / rate-limit segments ----
seg=""
if [ -n "$effort_level" ]; then
  if [ -n "$expected_effort" ] && [ "$(eff_rank "$effort_level")" -gt 0 ] && \
     [ "$(eff_rank "$effort_level")" -lt "$(eff_rank "$expected_effort")" ]; then
    printf -v t "$T_EFF" "$effort_level" "$expected_effort"
    seg+=" ${ALARM} ${t} ${band}"
  else
    seg+=" ┃ ⚡${effort_level}"
  fi
fi
if [ -n "$thinking_off" ]; then
  seg+=" ${ALARM} ${T_THINK} ${band}"
fi

if [ "$(conf_get SHOW_CONTEXT)" != false ] && [ -n "$ctx_pct" ]; then
  seg+=" ┃ ◔ ${ctx_pct}%"
fi

warn_at=$(conf_get LIMIT_WARN_AT)
case "${warn_at:-80}" in
  off|OFF|Off) warn_at="";;
  *[!0-9]*|"") warn_at=80;;
  *)           warn_at=${warn_at:-80};;
esac
if [ -n "$warn_at" ] && [ -n "$limit_pct" ] && [ "$limit_pct" -ge "$warn_at" ] 2>/dev/null; then
  printf -v t "$T_LIMIT" "$limit_pct"
  seg+=" ${ALARM} ${t} ${band}"
fi

acct_seg=""
if [ "$(conf_get SHOW_ACCOUNT)" != false ]; then
  [ -n "${email:-}" ] || email="$T_ACCT"
  acct_seg=" ┃ 👤 ${email}"
fi

# Over-wide padding: anything past the terminal width gets clipped by the TUI,
# so the band spans the full row at any terminal size.
if [ -n "$is_alarm" ] && [ -z "$state" ]; then
  tail_pad=" ┃ ${T_BACK}$(printf '🚨 %.0s' $(seq 1 80))"
elif [ -n "$is_alarm" ]; then
  tail_pad="$(printf ' 🚨%.0s' $(seq 1 80))"
else
  tail_pad=$(printf '%300s' '')
fi

printf '%s' "${band} ${head_txt}${seg}${acct_seg}${tail_pad}${R}"
