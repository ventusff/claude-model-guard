#!/usr/bin/env bash
# model-guard hook dispatcher: the single command behind every hook event the
# plugin registers. Reads the hook JSON on stdin, updates the per-session
# recovery state (lib.sh) and answers with hook JSON on stdout.
#
#   PostModelSwitch  source auto|resume and to_model weaker than from_model:
#                    the session was downgraded behind the user's back. Record
#                    the episode and start the detached recovery driver when a
#                    keystroke channel exists. Any other switch ends the episode.
#   PreModelSwitch   the switch the recovery driver typed: answer "allow", which
#                    skips Claude Code's cache-miss confirmation dialog. Any other
#                    switch gets no decision.
#   PreToolUse       pending|switching|halted: deny the tool and stop the turn.
#   UserPromptSubmit switching: block (recovery in flight). pending|halted:
#                    block once with an explanation; the next submission goes
#                    through and the session is marked released.
#   SessionStart     startup|clear|resume: forget stale state for this session
#                    (a latched fallback re-announces itself via
#                    PostModelSwitch source=resume). Also hints once per session
#                    when recovery is on but no keystroke channel exists.
#   SessionEnd       forget the session's state.
set -u
command -v jq >/dev/null 2>&1 || exit 0
plugin_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib.sh
. "$plugin_root/scripts/lib.sh"

input=$(cat 2>/dev/null || true)
[ -n "$input" ] || exit 0
event=$(jq -r '.hook_event_name // empty' <<<"$input" 2>/dev/null) || exit 0
sid=$(jq -r '.session_id // empty' <<<"$input" 2>/dev/null) || exit 0
[ -n "$sid" ] || exit 0
[ "$(mg_conf_or RECOVER on)" != off ] || exit 0
if [ "$(mg_conf_get DEBUG)" = true ]; then
  mg_debug "$(jq -c '{hook_event_name, session_id, source, from_model, to_model, tool_name, prompt: (.prompt // "" | .[0:80])} | with_entries(select(.value != null and .value != ""))' <<<"$input")"
fi

emit_stop() {
  jq -n --arg r "$1" '{continue: false, stopReason: $r,
    hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $r}}'
}
emit_block() { jq -n --arg r "$1" '{decision: "block", reason: $r}'; }

# What happens next, for the current state (second half of the stop text).
reason_tail() {
  local state="$1" status to target channel
  status=$(jq -r '.status // empty' <<<"$state")
  to=$(mg_display_name "$(jq -r '.to_model // empty' <<<"$state")")
  target=$(mg_display_name "$(jq -r '.target_model // empty' <<<"$state")")
  channel=$(jq -r '.channel // "none"' <<<"$state")
  case "$status" in
    switching) mg_text tail_switch "$target";;
    pending)   if [ "$channel" != none ]; then mg_text tail_switch "$target"; else mg_text tail_manual "$target"; fi;;
    halted)    mg_text tail_halted "$target" "$to";;
  esac
}
# Stop/deny text for the current state.
reason_for() {
  local state="$1" from to
  from=$(mg_display_name "$(jq -r '.from_model // empty' <<<"$state")")
  to=$(mg_display_name "$(jq -r '.to_model // empty' <<<"$state")")
  printf '%s %s' "$(mg_text stop "$from" "$to")" "$(reason_tail "$state")"
}

begin_episode() {
  local from="$1" to="$2" source="$3"
  local state status attempts target effort maxn channel note="" new_status cont=false
  state=$(mg_state_read "$sid")
  status=$(jq -r '.status // "idle"' <<<"$state")
  attempts=$(jq -r '.attempts // 0' <<<"$state")
  target=$(mg_conf_or RECOVER_MODEL 'claude-opus-5[1m]')
  effort=$(mg_conf_or RECOVER_EFFORT max)
  maxn=$(mg_conf_or RECOVER_MAX 3)
  channel=$(mg_channel)
  attempts=$((attempts + 1))
  if [ "$status" = pending ] || [ "$status" = switching ]; then
    new_status=halted; note=downgraded_again
  elif mg_same_model "$from" "$target"; then
    new_status=halted; note=target_flagged
  elif ! mg_is_downgrade "$target" "$to"; then
    new_status=halted; note=target_not_stronger
  elif [ "$attempts" -gt "$maxn" ] 2>/dev/null; then
    new_status=halted; note=too_many_recoveries
  elif [ "$channel" = none ]; then
    new_status=pending; note=no_channel
  else
    new_status=pending
  fi
  [ "$source" = auto ] && cont=true
  mg_state_update "$sid" \
    '{status: $st, from_model: $from, to_model: $to, target_model: $t, target_effort: $e,
      default_model: $dm, attempts: ($n | tonumber), source: $src, channel: $ch, note: $note,
      continue: ($cont == "true"), at: $at, warned: false, transcript_path: $tp}' \
    --arg st "$new_status" --arg from "$from" --arg to "$to" --arg t "$target" --arg e "$effort" \
    --arg dm "$(mg_settings_model)" --arg n "$attempts" --arg src "$source" --arg ch "$channel" \
    --arg note "$note" --arg cont "$cont" --arg at "$(date -Is)" \
    --arg tp "$(jq -r '.transcript_path // empty' <<<"$input")"
  mg_debug "episode $new_status ($note) from=$from to=$to target=$target channel=$channel attempts=$attempts"
  local dfrom dto dtarget
  dfrom=$(mg_display_name "$from"); dto=$(mg_display_name "$to"); dtarget=$(mg_display_name "$target")
  if [ "$new_status" = pending ] && [ "$channel" != none ]; then
    setsid -f "$plugin_root/scripts/recover.sh" "$sid" </dev/null >/dev/null 2>&1
    mg_notify "$(mg_text notify_t)" "$(mg_text notify_go "$dfrom" "$dto" "$dtarget")" normal
  else
    mg_notify "$(mg_text notify_t)" "$(mg_text notify_stop "$dfrom" "$dto" "$(reason_tail "$(mg_state_read "$sid")")")" critical
  fi
}

end_episode() {
  local to="$1" source="$2" state status by from
  state=$(mg_state_read "$sid")
  status=$(jq -r '.status // empty' <<<"$state")
  [ -n "$status" ] || return 0
  from=$(jq -r '.from_model // empty' <<<"$state")
  if [ -n "$from" ] && ! mg_is_downgrade "$from" "$to"; then
    # Back at (or above) the model the episode started from: nothing to remember.
    mg_state_clear "$sid"
    mg_debug "episode cleared: back on $to"
    return 0
  fi
  by=user
  if [ "$status" = switching ] || { [ "$(jq -r '.typed_switch // false' <<<"$state")" = true ] && mg_same_model "$to" "$(jq -r '.target_model // empty' <<<"$state")"; }; then
    by=auto
  fi
  mg_state_update "$sid" '.status="recovered" | .recovered_to=$to | .recovered_by=$by | .recovered_at=$at | .warned=false' \
    --arg to "$to" --arg by "$by" --arg at "$(date -Is)"
  mg_debug "episode recovered to=$to by=$by source=$source"
  [ "$by" = auto ] && mg_restore_default_model "$sid"
  return 0
}

on_model_switch() {
  local from to source
  from=$(jq -r '.from_model // empty' <<<"$input")
  to=$(jq -r '.to_model // empty' <<<"$input")
  source=$(jq -r '.source // "auto"' <<<"$input")
  case "$source" in
    auto|resume)
      if mg_is_downgrade "$from" "$to"; then begin_episode "$from" "$to" "$source"; else end_episode "$to" "$source"; fi;;
    *) end_episode "$to" "$source";;
  esac
}

on_pre_model_switch() {
  local state to
  state=$(mg_state_read "$sid")
  [ "$(jq -r '.status // empty' <<<"$state")" = switching ] || return 0
  to=$(jq -r '.to_model // empty' <<<"$input")
  mg_same_model "$to" "$(jq -r '.target_model // empty' <<<"$state")" || return 0
  jq -n '{hookSpecificOutput: {hookEventName: "PreModelSwitch", permissionDecision: "allow",
          permissionDecisionReason: "model-guard recovery: switching away from the flagged fallback"}}'
}

on_pre_tool_use() {
  local state status
  state=$(mg_state_read "$sid")
  status=$(jq -r '.status // empty' <<<"$state")
  case "$status" in
    pending|switching|halted) emit_stop "$(reason_for "$state")";;
  esac
}

on_prompt() {
  local state status warned from to target
  state=$(mg_state_read "$sid")
  status=$(jq -r '.status // empty' <<<"$state")
  case "$status" in
    switching)
      to=$(mg_display_name "$(jq -r '.to_model' <<<"$state")")
      target=$(mg_display_name "$(jq -r '.target_model' <<<"$state")")
      emit_block "$(mg_text block_wait "$to" "$target")";;
    pending|halted)
      warned=$(jq -r '.warned // false' <<<"$state")
      if [ "$warned" = true ]; then
        mg_state_update "$sid" '.status="released" | .released_at=$at' --arg at "$(date -Is)"
        mg_debug "released on user's second prompt"
        return 0
      fi
      mg_state_update "$sid" '.warned=true'
      to=$(mg_display_name "$(jq -r '.to_model' <<<"$state")")
      from=$(mg_display_name "$(jq -r '.from_model' <<<"$state")")
      emit_block "$(mg_text block_first "$to" "$from" "$to")";;
  esac
}

on_session_start() {
  local source
  source=$(jq -r '.source // "startup"' <<<"$input")
  [ "$source" = compact ] || mg_state_clear "$sid"
  [ "$(mg_conf_get SETUP_HINT)" != off ] || return 0
  [ "$(mg_conf_or RECOVER_CHANNEL auto)" = auto ] || return 0
  [ "$(mg_channel)" = none ] || return 0
  jq -n --arg m "$(mg_text hint_chan)" '{systemMessage: $m}'
}

case "$event" in
  PreModelSwitch)   on_pre_model_switch;;
  PostModelSwitch)  on_model_switch;;
  PreToolUse)       on_pre_tool_use;;
  UserPromptSubmit) on_prompt;;
  SessionStart)     on_session_start;;
  SessionEnd)       mg_state_clear "$sid";;
esac
exit 0
