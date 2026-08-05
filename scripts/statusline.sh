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
# Model strength: fable/mythos(4) > opus(3) > sonnet(2) > haiku(1) > unknown(0).
# Same rank but a different id still alarms — we can't prove it isn't weaker.
# Effort strength: xhigh(4) > high(3) > medium(2) > low(1).
#
# Colors are truecolor, with a fixed 256-color-cube fallback when COLORTERM says no.
# Plain ANSI 16-color codes get remapped by terminal themes and the contrast collapses
# (red turns pink). All three fg/bg pairs are WCAG >= 7:1 (AAA):
#   OK    #000000 on #3FB950 = 8.3:1    ALARM #FFFFFF on #B00020 = 7.3:1
#   INFO  #FFFFFF on #0D47A1 = 8.6:1
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

MG_VERSION="1.0.0"
set -u
input=$(cat 2>/dev/null || true)

CONF="$HOME/.claude/model-guard.conf"
conf_get() {
  [ -f "$CONF" ] || return 0
  sed -n "s/^[[:space:]]*$1=//p" "$CONF" | tail -n1 | tr -d '" '
}

if command -v jq >/dev/null 2>&1; then
  model_id=$(printf '%s' "$input" | jq -r '.model.id // "unknown"' 2>/dev/null || echo unknown)
  model_name=$(printf '%s' "$input" | jq -r '.model.display_name // .model.id // "unknown"' 2>/dev/null || echo unknown)
  effort_level=$(printf '%s' "$input" | jq -r '.effort.level // empty' 2>/dev/null || true)
  thinking_off=$(printf '%s' "$input" | jq -r 'if .thinking.enabled == false then "1" else "" end' 2>/dev/null || true)
  ctx_pct=$(printf '%s' "$input" | jq -r '.context_window.used_percentage // empty | if type=="number" then floor else empty end' 2>/dev/null || true)
  limit_pct=$(printf '%s' "$input" | jq -r '.rate_limits.five_hour.used_percentage // empty | if type=="number" then floor else empty end' 2>/dev/null || true)
  email=$(jq -r '.oauthAccount.emailAddress // empty' "$HOME/.claude.json" 2>/dev/null || true)
  settings_lang=$(jq -r '.language // empty' "$HOME/.claude/settings.json" 2>/dev/null || true)
  expected_effort=$(jq -r '.effortLevel // empty' "$HOME/.claude/settings.json" 2>/dev/null || true)
else
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
      T_ACCT="账号未知(API key?)";;
  ja) T_DOWN="🚨🚨🚨 モデルがダウングレード!現在: %s (%s) < %s"; T_BACK="今すぐ /model で戻して!"
      T_UP="⬆ デフォルトより上位: %s · %s(デフォルト %s)"
      T_EFF="⚡%s < デフォルト%s!"; T_THINK="🧠思考OFF!"; T_LIMIT="⏳5h上限 %s%%!"
      T_ACCT="アカウント不明(API key?)";;
  ko) T_DOWN="🚨🚨🚨 모델 다운그레이드! 현재: %s (%s) < %s"; T_BACK="지금 /model 로 되돌리세요!"
      T_UP="⬆ 기본보다 상위: %s · %s (기본 %s)"
      T_EFF="⚡%s < 기본 %s!"; T_THINK="🧠사고 OFF!"; T_LIMIT="⏳5h한도 %s%%!"
      T_ACCT="계정 알 수 없음 (API key?)";;
  es) T_DOWN="🚨🚨🚨 ¡MODELO DEGRADADO! ahora: %s (%s) < %s"; T_BACK="¡/model para volver YA!"
      T_UP="⬆ superior al predeterminado: %s · %s (predet.: %s)"
      T_EFF="¡⚡%s < predet. %s!"; T_THINK="🧠 ¡thinking OFF!"; T_LIMIT="¡⏳ límite 5h %s%%!"
      T_ACCT="cuenta desconocida (¿API key?)";;
  fr) T_DOWN="🚨🚨🚨 MODÈLE RÉTROGRADÉ ! actuel : %s (%s) < %s"; T_BACK="/model pour revenir !"
      T_UP="⬆ au-dessus du défaut : %s · %s (défaut : %s)"
      T_EFF="⚡%s < défaut %s !"; T_THINK="🧠 thinking OFF !"; T_LIMIT="⏳ limite 5h %s%% !"
      T_ACCT="compte inconnu (API key ?)";;
  de) T_DOWN="🚨🚨🚨 MODELL HERABGESTUFT! jetzt: %s (%s) < %s"; T_BACK="sofort /model zurückwechseln!"
      T_UP="⬆ über Standard: %s · %s (Standard: %s)"
      T_EFF="⚡%s < Standard %s!"; T_THINK="🧠 Thinking AUS!"; T_LIMIT="⏳ 5h-Limit %s%%!"
      T_ACCT="Konto unbekannt (API key?)";;
  pt) T_DOWN="🚨🚨🚨 MODELO REBAIXADO! agora: %s (%s) < %s"; T_BACK="rode /model para voltar JÁ!"
      T_UP="⬆ acima do padrão: %s · %s (padrão: %s)"
      T_EFF="⚡%s < padrão %s!"; T_THINK="🧠 thinking OFF!"; T_LIMIT="⏳ limite 5h %s%%!"
      T_ACCT="conta desconhecida (API key?)";;
  *)  T_DOWN="🚨🚨🚨 MODEL DOWNGRADED! now: %s (%s) < %s"; T_BACK="run /model to switch back NOW!"
      T_UP="⬆ above default: %s · %s (default: %s)"
      T_EFF="⚡%s < default %s!"; T_THINK="🧠 thinking OFF!"; T_LIMIT="⏳ 5h limit %s%%!"
      T_ACCT="account unknown (API key?)";;
esac

# ---- expected model ----
expected=$(conf_get EXPECTED_MODEL)
if [ -z "$expected" ] && [ -f "$HOME/.claude/statusline-expected-model" ]; then
  expected=$(head -n1 "$HOME/.claude/statusline-expected-model" | tr -d '[:space:]')
fi
if [ -z "$expected" ]; then
  cfg=$(jq -r '.model // empty' "$HOME/.claude/settings.json" 2>/dev/null || true)
  cfg=${cfg%%\[*}
  case "$cfg" in ""|default) ;; *) expected="$cfg";; esac
fi

rank_of() {
  local s="${1,,}"
  case "$s" in
    *fable*|*mythos*) echo 4;;
    *opus*)           echo 3;;
    *sonnet*)         echo 2;;
    *haiku*)          echo 1;;
    *)                echo 0;;
  esac
}
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
    ;;
  *)  # fixed 256-color-cube approximations (also theme-proof):
      # 16=#000 231=#fff 77=#5fd75f 124=#af0000 25=#005faf
    OK=$'\033[1;38;5;16;48;5;77m'
    ALARM=$'\033[1;38;5;231;48;5;124m'
    INFO=$'\033[1;38;5;231;48;5;25m'
    ;;
esac

# ---- pick the band + main text ----
is_alarm=""
if [ -z "$expected" ]; then
  band=$INFO; head_txt="● ${model_name} · ${model_id}"
elif printf '%s' "$model_id" | grep -qiE -- "$expected"; then
  band=$OK; head_txt="✔ ${model_name} · ${model_id}"
else
  ar=$(rank_of "$model_id"); er=$(rank_of "$expected")
  if [ "$ar" -gt 0 ] && [ "$er" -gt 0 ] && [ "$ar" -gt "$er" ]; then
    band=$INFO
    printf -v head_txt "$T_UP" "$model_name" "$model_id" "${expected^^}"
  else
    band=$ALARM; is_alarm=1
    printf -v head_txt "$T_DOWN" "$model_name" "$model_id" "${expected^^}"
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
if [ -n "$is_alarm" ]; then
  tail_pad=" ┃ ${T_BACK}$(printf '🚨 %.0s' $(seq 1 80))"
else
  tail_pad=$(printf '%300s' '')
fi

printf '%s' "${band} ${head_txt}${seg}${acct_seg}${tail_pad}${R}"
