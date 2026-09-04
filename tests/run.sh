#!/usr/bin/env bash
# model-guard test suite: drives guard-hook.sh / recover.sh / statusline.sh with
# synthetic Claude Code payloads in an isolated state dir. Run: tests/run.sh
set -u
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
export MODEL_GUARD_STATE_DIR="$tmp/state" MODEL_GUARD_CONF="$tmp/model-guard.conf" \
       MODEL_GUARD_SETTINGS="$tmp/settings.json" MODEL_GUARD_SESSIONS_DIR="$tmp/sessions"
unset KITTY_LISTEN_ON KITTY_WINDOW_ID TMUX TMUX_PANE
mkdir -p "$tmp/sessions"
printf 'LANGUAGE=en\nRECOVER_CHANNEL=dryrun\nRECOVER_MODEL=claude-opus-5[1m]\nRECOVER_EFFORT=max\nRECOVER_MAX=2\n' > "$MODEL_GUARD_CONF"
printf '{"model":"claude-fable-5-1[1m]","effortLevel":"xhigh"}\n' > "$MODEL_GUARD_SETTINGS"
. "$root/scripts/lib.sh"

pass=0; fail=0
ok()   { pass=$((pass+1)); printf '  ok   %s\n' "$1"; }
bad()  { fail=$((fail+1)); printf '  FAIL %s\n    %s\n' "$1" "${2:-}"; }
check(){ if eval "$2"; then ok "$1"; else bad "$1" "$2"; fi; }
hook() { jq -nc "$1" | "$root/scripts/guard-hook.sh"; }
switch(){ hook "{hook_event_name:\"PostModelSwitch\",session_id:\"$1\",from_model:\"$2\",to_model:\"$3\",requested_model:null,source:\"$4\"}"; }
pretool(){ hook "{hook_event_name:\"PreToolUse\",session_id:\"$1\",tool_name:\"Bash\",tool_input:{command:\"ls\"}}"; }
prompt(){ hook "{hook_event_name:\"UserPromptSubmit\",session_id:\"$1\",prompt:\"go on\"}"; }
status(){ mg_state_get "$1" status; }
wait_status(){ local i; for i in $(seq 1 100); do [ "$(status "$1")" = "$2" ] && return 0; sleep 0.1; done; return 1; }

echo "== automatic downgrade: stop, switch, restore default, continue"
s=s1
out=$(switch $s 'claude-fable-5-1[1m]' claude-opus-4-8 auto)
check "no hook output on PostModelSwitch(auto)" '[ -z "$out" ]'
check "state pending or switching" 'st=$(status $s); [ "$st" = pending ] || [ "$st" = switching ]'
check "default model captured" '[ "$(mg_state_get $s default_model)" = "claude-fable-5-1[1m]" ]'
out=$(pretool $s)
check "PreToolUse stops the turn" 'jq -e ".continue==false and (.hookSpecificOutput.permissionDecision==\"deny\")" <<<"$out" >/dev/null'
check "stop reason names both models" 'jq -r .stopReason <<<"$out" | grep -q "Fable 5.1 (1M).*Opus 4.8"'
check "driver reached switching" 'wait_status $s switching'
out=$(hook "{hook_event_name:\"PreModelSwitch\",session_id:\"$s\",from_model:\"claude-opus-4-8\",to_model:\"claude-opus-5[1m]\",requested_model:\"claude-opus-5[1m]\",source:\"command\"}")
check "PreModelSwitch allows the recovery switch (skips confirm dialog)" 'jq -e ".hookSpecificOutput.permissionDecision==\"allow\"" <<<"$out" >/dev/null'
out=$(hook "{hook_event_name:\"PreModelSwitch\",session_id:\"$s\",from_model:\"claude-opus-4-8\",to_model:\"claude-sonnet-5\",requested_model:\"sonnet\",source:\"command\"}")
check "PreModelSwitch stays silent for other targets" '[ -z "$out" ]'
out=$(prompt $s)
check "prompt blocked while switching" 'jq -e ".decision==\"block\"" <<<"$out" >/dev/null'
# wait for the driver to type /model, then play Claude Code: persist the model and fire PostModelSwitch(command)
for i in $(seq 1 60); do grep -q 'TEXT /model' "$MG_STATE_DIR/$s.log" 2>/dev/null && break; sleep 0.1; done
check "driver sent Esc then /model" 'grep -q "KEY escape" "$MG_STATE_DIR/$s.log" && grep -q "TEXT /model claude-opus-5\[1m\]" "$MG_STATE_DIR/$s.log"'
jq '.model="claude-opus-5[1m]"' "$MODEL_GUARD_SETTINGS" > "$tmp/x" && mv "$tmp/x" "$MODEL_GUARD_SETTINGS"
out=$(switch $s claude-opus-4-8 'claude-opus-5[1m]' command)
check "status recovered by auto" '[ "$(status $s)" = recovered ] && [ "$(mg_state_get $s recovered_by)" = auto ]'
check "settings.json default restored" '[ "$(jq -r .model "$MODEL_GUARD_SETTINGS")" = "claude-fable-5-1[1m]" ]'
for i in $(seq 1 100); do grep -q 'sent continue prompt' "$MG_STATE_DIR/$s.log" 2>/dev/null && break; sleep 0.1; done
check "driver sent /effort max then the prompt" 'grep -q "TEXT /effort max" "$MG_STATE_DIR/$s.log" && grep -q "TEXT Continue\." "$MG_STATE_DIR/$s.log"'
check "prompt allowed after recovery" '[ -z "$(prompt $s)" ]'
check "tools allowed after recovery" '[ -z "$(pretool $s)" ]'
out=$(switch $s 'claude-opus-5[1m]' 'claude-fable-5-1[1m]' command)
check "switching back to Fable clears the episode" '[ ! -e "$(mg_state_file $s)" ]'

echo "== driver timed out, user confirms the switch later: default still restored"
s=s1b
switch $s 'claude-fable-5-1[1m]' claude-opus-4-8 auto >/dev/null; wait_status $s switching
for i in $(seq 1 60); do grep -q 'TEXT /model' "$MG_STATE_DIR/$s.log" 2>/dev/null && break; sleep 0.1; done
mg_state_update $s '.status="stopped" | .note="switch_not_observed" | .turn_stopped=true'
jq '.model="claude-opus-5[1m]"' "$MODEL_GUARD_SETTINGS" > "$tmp/x" && mv "$tmp/x" "$MODEL_GUARD_SETTINGS"
switch $s claude-opus-4-8 'claude-opus-5[1m]' command >/dev/null
check "late confirmation still counts as automatic" '[ "$(mg_state_get $s recovered_by)" = auto ]'
check "default restored after late confirmation" '[ "$(jq -r .model "$MODEL_GUARD_SETTINGS")" = "claude-fable-5-1[1m]" ]'

echo "== resume-restored downgrade: switch without continue"
s=s2
switch $s 'claude-fable-5-1[1m]' claude-opus-4-8 resume >/dev/null
check "continue flag off for resume" '[ "$(mg_state_get $s continue)" = false ]'
wait_status $s switching
for i in $(seq 1 60); do grep -q 'TEXT /model' "$MG_STATE_DIR/$s.log" 2>/dev/null && break; sleep 0.1; done
switch $s claude-opus-4-8 'claude-opus-5[1m]' command >/dev/null
for i in $(seq 1 100); do grep -q ' done' "$MG_STATE_DIR/$s.log" 2>/dev/null && break; sleep 0.1; done
check "no continue prompt after resume" '! grep -q "TEXT Continue" "$MG_STATE_DIR/$s.log" && grep -q " done" "$MG_STATE_DIR/$s.log"'

echo "== the recovery model itself gets flagged: stop once, then hands off"
s=s3
switch $s claude-opus-5 claude-opus-4-8 auto >/dev/null
check "stopped with note target_flagged" '[ "$(status $s)" = stopped ] && [ "$(mg_state_get $s note)" = target_flagged ]'
out=$(pretool $s)
check "first tool call after the downgrade is stopped" 'jq -e ".continue==false" <<<"$out" >/dev/null'
check "stop reason says pick one with /model" 'jq -r .stopReason <<<"$out" | grep -q "pick one with /model"'
check "prompts are never blocked once stopped" '[ -z "$(prompt $s)" ]'
check "later tool calls pass" '[ -z "$(pretool $s)" ]'

echo "== no keystroke channel: plain stop"
s=s4
printf 'LANGUAGE=zh\nRECOVER_CHANNEL=none\n' > "$MODEL_GUARD_CONF"
switch $s 'claude-fable-5-1[1m]' claude-opus-4-8 auto >/dev/null
check "stopped with note no_channel" '[ "$(status $s)" = stopped ] && [ "$(mg_state_get $s note)" = no_channel ]'
check "no driver spawned" '[ ! -e "$MG_STATE_DIR/$s.log" ]'
out=$(pretool $s)
check "zh stop reason asks for /model" 'jq -r .stopReason <<<"$out" | grep -q "请 /model 切到 Opus 5 (1M)"'
check "turn marked stopped" '[ "$(mg_state_get $s turn_stopped)" = true ]'
check "next tool call passes" '[ -z "$(pretool $s)" ]'
check "prompts pass" '[ -z "$(prompt $s)" ]'
s=s4b
switch $s 'claude-fable-5-1[1m]' claude-opus-4-8 auto >/dev/null
hook "{hook_event_name:\"Stop\",session_id:\"$s\",stop_hook_active:false}" >/dev/null
check "a turn that ends by itself counts as stopped" '[ "$(mg_state_get $s turn_stopped)" = true ] && [ -z "$(pretool $s)" ]'
s=s4c
switch $s 'claude-fable-5-1[1m]' claude-opus-4-8 resume >/dev/null
check "resume without channel: nothing to stop" '[ "$(status $s)" = stopped ] && [ -z "$(pretool $s)" ]'
switch $s claude-opus-4-8 'claude-opus-5[1m]' picker >/dev/null
check "manual switch after a plain stop: recovered by user" '[ "$(status $s)" = recovered ] && [ "$(mg_state_get $s recovered_by)" = user ]'
printf 'LANGUAGE=en\nRECOVER_CHANNEL=dryrun\nRECOVER_MODEL=claude-opus-5[1m]\nRECOVER_EFFORT=max\nRECOVER_MAX=2\n' > "$MODEL_GUARD_CONF"

echo "== attempts cap"
s=s5
switch $s 'claude-fable-5-1[1m]' claude-opus-4-8 auto >/dev/null; wait_status $s switching
switch $s claude-opus-4-8 'claude-opus-5[1m]' command >/dev/null
switch $s 'claude-fable-5-1[1m]' claude-opus-4-8 auto >/dev/null; wait_status $s switching
switch $s claude-opus-4-8 'claude-opus-5[1m]' command >/dev/null
switch $s 'claude-fable-5-1[1m]' claude-opus-4-8 auto >/dev/null
check "third automatic downgrade only stops (RECOVER_MAX=2)" '[ "$(status $s)" = stopped ] && [ "$(mg_state_get $s note)" = too_many_recoveries ]'

echo "== non-downgrades are ignored"
s=s6
switch $s claude-sonnet-5 claude-opus-4-8 auto >/dev/null
check "automatic upgrade leaves no state" '[ ! -e "$(mg_state_file $s)" ]'
switch $s 'claude-fable-5-1[1m]' claude-opus-5 command >/dev/null
check "user switch without episode leaves no state" '[ ! -e "$(mg_state_file $s)" ]'

echo "== session lifecycle"
s=s7
switch $s 'claude-fable-5-1[1m]' claude-opus-4-8 auto >/dev/null
hook "{hook_event_name:\"SessionStart\",session_id:\"$s\",source:\"compact\"}" >/dev/null
check "compact keeps state" '[ -e "$(mg_state_file $s)" ]'
out=$(hook "{hook_event_name:\"SessionStart\",session_id:\"$s\",source:\"startup\"}")
check "startup clears state" '[ ! -e "$(mg_state_file $s)" ]'
check "session start is silent" '[ -z "$out" ]'
switch $s 'claude-fable-5-1[1m]' claude-opus-4-8 auto >/dev/null
hook "{hook_event_name:\"SessionEnd\",session_id:\"$s\",reason:\"other\"}" >/dev/null
check "session end clears state" '[ ! -e "$(mg_state_file $s)" ]'
printf 'RECOVER=off\n' > "$MODEL_GUARD_CONF"
switch $s 'claude-fable-5-1[1m]' claude-opus-4-8 auto >/dev/null
check "RECOVER=off disables everything" '[ ! -e "$(mg_state_file $s)" ]'
printf 'LANGUAGE=en\n' > "$MODEL_GUARD_CONF"
out=$(hook "{hook_event_name:\"SessionStart\",session_id:\"$s\",source:\"startup\"}")
check "session start is silent without a channel too" '[ -z "$out" ]'

echo "== statusline bands"
sl="$root/scripts/statusline.sh"
printf 'LANGUAGE=en\nSHOW_ACCOUNT=false\nRECOVER_CHANNEL=dryrun\n' > "$MODEL_GUARD_CONF"
printf '{"model":"claude-fable-5-1[1m]","effortLevel":"xhigh"}\n' > "$MODEL_GUARD_SETTINGS"
s=s8
switch $s 'claude-fable-5-1[1m]' claude-opus-4-8 auto >/dev/null; wait_status $s switching
out=$(printf '{"session_id":"%s","model":{"id":"claude-opus-4-8","display_name":"Opus 4.8"},"effort":{"level":"xhigh"}}' $s | HOME="$tmp" "$sl")
check "switching band" 'grep -q "switching to Opus 5 (1M)" <<<"$out"'
mg_state_update $s '.status="stopped" | .note="no_channel"'
out=$(printf '{"session_id":"%s","model":{"id":"claude-opus-4-8","display_name":"Opus 4.8"}}' $s | HOME="$tmp" "$sl")
check "stopped band names the /model target" 'grep -q "stopped · /model to Opus 5 (1M)" <<<"$out"'
mg_state_update $s '.status="stopped" | .note="target_flagged"'
out=$(printf '{"session_id":"%s","model":{"id":"claude-opus-4-8","display_name":"Opus 4.8"}}' $s | HOME="$tmp" "$sl")
check "stopped band after a flagged recovery model" 'grep -q "pick one with /model" <<<"$out"'
mg_state_update $s '.status="switching"'
switch $s claude-opus-4-8 'claude-opus-5[1m]' command >/dev/null
out=$(printf '{"session_id":"%s","model":{"id":"claude-opus-5[1m]","display_name":"Opus 5 (1M context)"},"effort":{"level":"max"}}' $s | HOME="$tmp" "$sl")
check "recovered band is calm and names the switch" 'grep -q "Fable 5.1 (1M) flagged → switched to Opus 5 (1M)" <<<"$out" && ! grep -q "DOWNGRADED" <<<"$out"'
out=$(printf '{"session_id":"%s","model":{"id":"claude-sonnet-5","display_name":"Sonnet 5"}}' $s | HOME="$tmp" "$sl")
check "other model after recovery: normal alarm" 'grep -q "DOWNGRADED" <<<"$out"'
out=$(printf '{"session_id":"nostate","model":{"id":"claude-fable-5-1[1m]","display_name":"Fable 5.1"}}' | HOME="$tmp" "$sl")
check "green when on the expected model" 'grep -q "✔" <<<"$out"'
out=$(printf '{"session_id":"nostate","model":{"id":"claude-opus-5","display_name":"Opus 5"}}' | HOME="$tmp" "$sl")
check "opus-5 below fable alarms" 'grep -q "DOWNGRADED" <<<"$out"'
printf 'LANGUAGE=en\nSHOW_ACCOUNT=false\nEXPECTED_MODEL=claude-opus-4-8\n' > "$MODEL_GUARD_CONF"
out=$(printf '{"session_id":"nostate","model":{"id":"claude-opus-5","display_name":"Opus 5"}}' | HOME="$tmp" "$sl")
check "opus-5 above expected opus-4-8 is an upgrade, not an alarm" 'grep -q "above default" <<<"$out"'

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
