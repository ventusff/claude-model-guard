#!/usr/bin/env bash
# model-guard hook dispatcher: the single command behind every hook event the
# plugin registers. Reads the hook JSON on stdin, updates the per-session
# recovery state (lib.sh) and answers with hook JSON on stdout.
#
#   PostModelSwitch  a switch the user did not ask for, to a weaker model:
#                    the session was downgraded behind the user's back. With a
#                    keystroke channel: record "pending" and start the detached
#                    recovery driver. Without one (or when an automatic switch
#                    is not allowed): record "stopped". Any other switch ends
#                    the episode.
#   PreModelSwitch   the switch the recovery driver typed: answer "allow", which
#                    skips Claude Code's cache-miss confirmation dialog. Any other
#                    switch gets no decision.
#   PreToolUse       pending|switching: deny the tool and stop the turn (the
#                    driver is taking over). stopped: deny once and end the
#                    turn; later tool calls pass.
#   Stop             stopped: the turn ended by itself; nothing left to stop.
#   UserPromptSubmit pending|switching: block, the driver is typing into the
#                    session. Otherwise pass.
#   SessionStart     startup|clear|resume: forget stale state for this session
#                    (a latched fallback re-announces itself via
#                    PostModelSwitch source=resume).
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
    pending|switching) mg_text tail_switch "$target";;
    stopped)
      case "$(jq -r '.note // empty' <<<"$state")" in
        target_flagged|downgraded_again|too_many_recoveries|target_not_stronger) mg_text tail_halted "$target" "$to";;
        *) mg_text tail_manual "$target";;
      esac;;
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
    new_status=stopped; note=downgraded_again
  elif mg_same_model "$from" "$target"; then
    new_status=stopped; note=target_flagged
  elif ! mg_is_downgrade "$target" "$to"; then
    new_status=stopped; note=target_not_stronger
  elif [ "$attempts" -gt "$maxn" ] 2>/dev/null; then
    new_status=stopped; note=too_many_recoveries
  elif [ "$channel" = none ]; then
    new_status=stopped; note=no_channel
  else
    new_status=pending
  fi
  [ "$source" = auto ] && cont=true
  # A downgrade restored on resume has no running turn: nothing to stop.
  local turn_stopped=false; [ "$source" = resume ] && turn_stopped=true
  mg_state_update "$sid" \
    '{status: $st, from_model: $from, to_model: $to, target_model: $t, target_effort: $e,
      default_model: $dm, attempts: ($n | tonumber), source: $src, channel: $ch, note: $note,
      continue: ($cont == "true"), at: $at, turn_stopped: ($ts == "true"), transcript_path: $tp}' \
    --arg st "$new_status" --arg from "$from" --arg to "$to" --arg t "$target" --arg e "$effort" \
    --arg dm "$(mg_settings_model)" --arg n "$attempts" --arg src "$source" --arg ch "$channel" \
    --arg note "$note" --arg cont "$cont" --arg at "$(date -Is)" --arg ts "$turn_stopped" \
    --arg tp "$(jq -r '.transcript_path // empty' <<<"$input")"
  mg_debug "episode $new_status ($note) from=$from to=$to target=$target channel=$channel attempts=$attempts"
  local dfrom dto dtarget
  dfrom=$(mg_display_name "$from"); dto=$(mg_display_name "$to"); dtarget=$(mg_display_name "$target")
  if [ "$new_status" = pending ]; then
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
  mg_state_update "$sid" '.status="recovered" | .recovered_to=$to | .recovered_by=$by | .recovered_at=$at' \
    --arg to "$to" --arg by "$by" --arg at "$(date -Is)"
  mg_debug "episode recovered to=$to by=$by source=$source"
  [ "$by" = auto ] && mg_restore_default_model "$sid"
  return 0
}

# Claude Code names the switches a person asks for. Everything else -- a
# safeguard-flag fallback, a model restored on resume, any source name added
# later -- counts as automatic, so an unrecognised source starts a recovery
# instead of passing the downgrade through.
mg_switch_kind() {
  case "$1" in
    *resume*)                                                     printf resume;;
    command|picker|sdk|config|fast_mode|slash_command|user_request|client_request)
                                                                  printf user;;
    *)                                                            printf auto;;
  esac
}

on_model_switch() {
  local from to source kind
  from=$(jq -r '.from_model // empty' <<<"$input")
  to=$(jq -r '.to_model // empty' <<<"$input")
  source=$(jq -r '.source // "auto"' <<<"$input")
  kind=$(mg_switch_kind "$source")
  if [ "$kind" != user ] && mg_is_downgrade "$from" "$to"; then
    begin_episode "$from" "$to" "$kind"
  else
    end_episode "$to" "$source"
  fi
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
    pending|switching) emit_stop "$(reason_for "$state")";;
    stopped)
      [ "$(jq -r '.turn_stopped // false' <<<"$state")" = true ] && return 0
      mg_state_update "$sid" '.turn_stopped=true'
      emit_stop "$(reason_for "$state")";;
  esac
}

on_stop() {
  [ "$(mg_state_get "$sid" status)" = stopped ] || return 0
  mg_state_update "$sid" '.turn_stopped=true'
}

on_prompt() {
  local state status to target
  state=$(mg_state_read "$sid")
  status=$(jq -r '.status // empty' <<<"$state")
  case "$status" in
    pending|switching)
      to=$(mg_display_name "$(jq -r '.to_model' <<<"$state")")
      target=$(mg_display_name "$(jq -r '.target_model' <<<"$state")")
      emit_block "$(mg_text block_wait "$to" "$target")";;
  esac
}

on_session_start() {
  [ "$(jq -r '.source // "startup"' <<<"$input")" = compact ] || mg_state_clear "$sid"
}

case "$event" in
  PreModelSwitch)   on_pre_model_switch;;
  PostModelSwitch)  on_model_switch;;
  PreToolUse)       on_pre_tool_use;;
  Stop)             on_stop;;
  UserPromptSubmit) on_prompt;;
  SessionStart)     on_session_start;;
  SessionEnd)       mg_state_clear "$sid";;
esac
exit 0
