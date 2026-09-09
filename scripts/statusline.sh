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
# settings.json per-model effort (falling back to "effortLevel"), thinking switched
# off, and a heads-up when the
# 5-hour rate-limit window fills up (which is exactly when forced fallbacks happen).
# The usage numbers are the logged-in account's own, asked from Claude Code's usage
# endpoint (see "usage of the logged-in account" below), not the session's last header.
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
#   SHOW_LIMIT=true|false                   show the account's 5-hour and 7-day usage,
#                                           e.g. "⏳ 5h 37% · 7d 18%" (default true)
#   LIMIT_WARN_AT=<0-100|off>               red patch when 5h rate-limit usage >= N
#                                           (default 80; "off" disables)
#
# Debug: add   printf '%s' "$input" > ~/.claude/model-guard-last-input.json
# right after the `input=$(cat ...)` line to inspect the full stdin payload
# (model / effort / thinking / context_window / rate_limits / fast_mode / ...).

MG_VERSION="1.4.0"
set -u
input=$(cat 2>/dev/null || true)

CONF="${MODEL_GUARD_CONF:-$HOME/.claude/model-guard.conf}"
SETTINGS="${MODEL_GUARD_SETTINGS:-$HOME/.claude/settings.json}"
STATE_DIR="${MODEL_GUARD_STATE_DIR:-${XDG_RUNTIME_DIR:-${TMPDIR:-/tmp}}/model-guard}"
# Claude Code keeps .claude.json next to its config dir's parent and the credentials
# inside the config dir; both move with CLAUDE_CONFIG_DIR.
CLAUDE_JSON="${CLAUDE_CONFIG_DIR:-$HOME}/.claude.json"
CREDENTIALS="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/.credentials.json"
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
  seen_5h=$(printf '%s' "$input" | jq -r '.rate_limits.five_hour.used_percentage // empty | if type=="number" then floor else empty end' 2>/dev/null || true)
  seen_7d=$(printf '%s' "$input" | jq -r '.rate_limits.seven_day.used_percentage // empty | if type=="number" then floor else empty end' 2>/dev/null || true)
  email=$(jq -r '.oauthAccount.emailAddress // empty' "$CLAUDE_JSON" 2>/dev/null || true)
  settings_lang=$(jq -r '.language // empty' "$SETTINGS" 2>/dev/null || true)
  # /model and /effort save the current model's default in modelSettings. The old
  # global effortLevel can remain unchanged. Context variants share a canonical
  # model key; prefer that key over a manually written [1m] variant, as Claude does.
  expected_effort=$(jq -r --arg model "$model_id" '
    def saved_effort: select(. == "low" or . == "medium" or . == "high" or . == "xhigh");
    (.modelSettings | if type == "object" then . else {} end) as $models |
    ($model | sub("\\[1[mM]\\]$"; "")) as $key |
    ($models[$key].effortLevel? | saved_effort) //
    ($models[$model].effortLevel? | saved_effort) //
    (.effortLevel | saved_effort) // empty
  ' "$SETTINGS" 2>/dev/null || true)
  state=""
  [ -n "$session_id" ] && state=$(cat "$STATE_DIR/$session_id.json" 2>/dev/null || true)
else
  session_id=""; state=""
  model_id=unknown; model_name=unknown; effort_level=""; thinking_off=""
  ctx_pct=""; seen_5h=""; seen_7d=""; email=""; settings_lang=""; expected_effort=""
fi

# ---- usage of the logged-in account ----
# Asked from Claude Code's own usage endpoint (the one behind /usage) with the login
# token Claude Code will use for its next request, so the number always belongs to the
# account that request bills. The payload's rate_limits is not that: it is what this
# one process last read from a response header, so it stands still until this session
# gets another response, and it survives /login — after an account switch it keeps
# reporting the previous account.
# One cache per machine, shared by every session and keyed by the token (a truncated
# hash, never the token itself): a new login is a new key, so the next refresh asks
# again at once, and until the answer is in the segment stays empty rather than showing
# another account's number. The token is read where Claude Code stores it and is never
# refreshed here: refresh tokens rotate, and racing Claude Code for one logs it out.
USAGE_URL="https://api.anthropic.com/api/oauth/usage"
USAGE_CACHE="$STATE_DIR/usage.json"
USAGE_TTL=30    # seconds a reading is shared before it is asked again
USAGE_WAIT=3    # seconds one fetch may hold up the statusline

sha256_16() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum; else shasum -a 256; fi | cut -c1-16
}

# The login token for the next request: MODEL_GUARD_CREDENTIALS (tests), else the
# environment, the macOS keychain item Claude Code writes, the credentials file.
oauth_token() {
  local blob=""
  if [ -n "${MODEL_GUARD_CREDENTIALS:-}" ]; then
    blob=$(cat "$MODEL_GUARD_CREDENTIALS" 2>/dev/null || true)
  elif [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
    printf '%s' "$CLAUDE_CODE_OAUTH_TOKEN"; return 0
  else
    if [ "$(uname -s)" = Darwin ] && command -v security >/dev/null 2>&1; then
      local service="Claude Code-credentials"
      [ -n "${CLAUDE_CONFIG_DIR:-}" ] && service+="-$(printf '%s' "$CLAUDE_CONFIG_DIR" | sha256_16 | cut -c1-8)"
      blob=$(security find-generic-password -a "${USER:-claude-code-user}" -w -s "$service" 2>/dev/null || true)
    fi
    [ -n "$blob" ] || blob=$(cat "$CREDENTIALS" 2>/dev/null || true)
  fi
  [ -n "$blob" ] && printf '%s' "$blob" | jq -r '.claudeAiOauth.accessToken // empty' 2>/dev/null
  return 0
}

# Writes the cache for one login: both utilisations on HTTP 200, only the status
# otherwise (a failure is not asked again before the TTL runs out either).
usage_fetch() {  # <token> <key> <now>
  local body="$USAGE_CACHE.$$.body" tmp="$USAGE_CACHE.$$" code
  code=$(printf 'header = "Authorization: Bearer %s"\n' "$1" | curl -sS -K - --max-time "$USAGE_WAIT" \
           -A "model-guard/$MG_VERSION" -o "$body" -w '%{http_code}' "$USAGE_URL" 2>/dev/null) || code=000
  if [ "$code" = 200 ] && jq -e '.five_hour.utilization != null' "$body" >/dev/null 2>&1; then
    jq -c --arg key "$2" --argjson at "$3" \
      '{key: $key, at: $at, http: 200, five_hour: (.five_hour.utilization | floor),
        seven_day: (.seven_day.utilization | if . == null then null else floor end),
        resets_at: .five_hour.resets_at}' "$body" > "$tmp" 2>/dev/null
  else
    jq -nc --arg key "$2" --argjson at "$3" --arg http "$code" \
      '{key: $key, at: $at, http: (($http | tonumber?) // 0)}' > "$tmp" 2>/dev/null
  fi
  mv -f "$tmp" "$USAGE_CACHE" 2>/dev/null; rm -f "$body" "$tmp"
}

# Prints the cached reading of the current login (JSON), asking first when the cache is
# missing, belongs to another login, or is older than USAGE_TTL. Prints nothing while
# another session is asking for a new login. Returns 1 when there is no login token
# (API key, third-party providers).
usage_reading() {
  local tok key now cached at lock lock_at
  tok=$(oauth_token); [ -n "$tok" ] || return 1
  key=$(printf '%s' "$tok" | sha256_16)
  now=$(date +%s)
  cached=$(cat "$USAGE_CACHE" 2>/dev/null || true)
  at=$(printf '%s' "$cached" | jq -r '.at // 0' 2>/dev/null)
  if [ "$(printf '%s' "$cached" | jq -r '.key // empty' 2>/dev/null)" != "$key" ] || \
     [ $(( now - ${at:-0} )) -ge "$USAGE_TTL" ]; then
    lock="$USAGE_CACHE.lock"
    mkdir -p "$STATE_DIR" 2>/dev/null && chmod 700 "$STATE_DIR" 2>/dev/null
    # a fetch killed half-way leaves its lock behind; older than a fetch can take = stale
    lock_at=$(cat "$lock/at" 2>/dev/null || true)
    if [ -d "$lock" ] && [ $(( now - ${lock_at:-0} )) -gt $(( USAGE_WAIT + 2 )) ]; then
      rm -rf "$lock"
    fi
    if mkdir "$lock" 2>/dev/null; then
      printf '%s' "$now" > "$lock/at"
      usage_fetch "$tok" "$key" "$now"
      rm -rf "$lock"
      cached=$(cat "$USAGE_CACHE" 2>/dev/null || true)
    fi
  fi
  printf '%s' "$cached" | jq -c --arg key "$key" 'select(.key == $key)' 2>/dev/null
  return 0
}

# What the band shows: the account's own numbers when a login token is at hand, else
# what this session last saw in a response header.
if usage=$(usage_reading); then
  limit_5h=$(printf '%s' "$usage" | jq -r '.five_hour // empty' 2>/dev/null)
  limit_7d=$(printf '%s' "$usage" | jq -r '.seven_day // empty' 2>/dev/null)
else
  limit_5h=$seen_5h; limit_7d=$seen_7d
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
if [ -n "$warn_at" ] && [ -n "$limit_5h" ] && [ "$limit_5h" -ge "$warn_at" ] 2>/dev/null; then
  printf -v t "$T_LIMIT" "$limit_5h"
  seg+=" ${ALARM} ${t} ${band}"
elif [ "$(conf_get SHOW_LIMIT)" != false ] && [ -n "$limit_5h" ]; then
  seg+=" ┃ ⏳ 5h ${limit_5h}%"
  [ -n "$limit_7d" ] && seg+=" · 7d ${limit_7d}%"
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
