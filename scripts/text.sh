#!/usr/bin/env bash
# model-guard user-facing text, sourced by lib.sh. Every string the band, the
# hooks, the driver and the desktop notice show lives here, once per language.
#
# mg_text KEY [printf args...]: prints the string for the band language.
#   Recovery hooks and driver
#     stop            the turn was stopped: <from> was flagged, session is on <to>
#     tail_switch     ...switching to <target> automatically
#     tail_manual     ...switch to <target> by hand
#     tail_halted     ...<target> would be flagged too; pick one by hand
#     block_wait      prompt blocked while the driver types (<to>, <target>)
#     notify_t        desktop notice title
#     notify_go       <from> → <to>, switching to <target>
#     notify_done     switched to <target>
#     notify_fail     switch to <target> failed (<why>)
#     notify_stop     <from> → <to>, stopped; <why>
#     prompt          the continue prompt typed after a recovery
#   Band
#     band_switch     recovery in progress (<from>, <to>, <target>)
#     band_manual     stopped, switch by hand (<from>, <to>, <target>)
#     band_halted     stopped, pick a model by hand (<to>)
#     band_recov      recovered (<from>, <target>)
#     band_down       silent downgrade (<name>, <id>, <expected>)
#     band_back       the call to action after band_down
#     band_up         above the default (<name>, <id>, <expected>)
#     seg_effort      effort below the saved default (<level>, <default>)
#     seg_think       extended thinking is off
#     seg_limit       5-hour usage at the warning threshold (<percent>)
#     acct_unknown    no logged-in account email

mg_text() {
  local key="$1"; shift
  local fmt
  case "$(mg_lang):$key" in
    zh:stop)         fmt="🚨 model-guard：%s 被 flag，会话被降到 %s，已停止。";;
    zh:tail_switch)  fmt="正在自动切到 %s…";;
    zh:tail_manual)  fmt="请 /model 切到 %s 后重发。";;
    zh:tail_halted)  fmt="%s 也会被 flag，不再自动切换，请 /model 自选。";;
    zh:block_wait)   fmt="🚨 model-guard：正在从 %s 自动切到 %s，请稍等；若 30 秒内没切成功，/model 手动切。";;
    zh:band_switch)  fmt="🚨 被 flag：%s → %s · 自动切回 %s 中…";;
    zh:band_manual)  fmt="🚨 被 flag：%s → %s · 已停 · /model 切到 %s";;
    zh:band_halted)  fmt="🚨 被 flag 降到 %s · 已停 · /model 自选";;
    zh:band_recov)   fmt="🔁 %s 被 flag → 已切到 %s";;
    zh:band_down)    fmt="🚨🚨🚨 模型被降级!当前: %s (%s) < %s";;
    zh:band_back)    fmt="立刻 /model 切回!";;
    zh:band_up)      fmt="⬆ 强于默认:当前 %s · %s(默认 %s)";;
    zh:seg_effort)   fmt="⚡%s < 默认%s!";;
    zh:seg_think)    fmt="🧠思考OFF!";;
    zh:seg_limit)    fmt="⏳5h额度 %s%%!";;
    zh:acct_unknown) fmt="账号未知(API key?)";;
    zh:notify_t)     fmt="model-guard：模型被 flag 降级";;
    zh:notify_go)    fmt="%s → %s，已停止，正在切到 %s 并继续";;
    zh:notify_done)  fmt="已切到 %s，任务已继续";;
    zh:notify_fail)  fmt="切到 %s 没有成功（%s），会话保持停止";;
    zh:notify_stop)  fmt="%s → %s，已停止；%s";;
    zh:prompt)       fmt="继续";;
    ja:stop)         fmt="🚨 model-guard：%s がフラグされ、セッションは %s に格下げされました。停止しました。";;
    ja:tail_switch)  fmt="%s へ自動で切り替え中…";;
    ja:tail_manual)  fmt="/model で %s に切り替えてから再送してください。";;
    ja:tail_halted)  fmt="%s もフラグ対象のため自動切替しません。/model で選んでください。";;
    ja:block_wait)   fmt="🚨 model-guard：%s から %s へ自動切替中です。30 秒で切り替わらなければ /model で手動切替。";;
    ja:band_switch)  fmt="🚨 フラグ：%s → %s · %s へ自動切替中…";;
    ja:band_manual)  fmt="🚨 フラグ：%s → %s · 停止 · /model で %s へ";;
    ja:band_halted)  fmt="🚨 フラグで %s に格下げ · 停止 · /model で選択";;
    ja:band_recov)   fmt="🔁 %s がフラグ → %s に切替済み";;
    ja:band_down)    fmt="🚨🚨🚨 モデルがダウングレード!現在: %s (%s) < %s";;
    ja:band_back)    fmt="今すぐ /model で戻して!";;
    ja:band_up)      fmt="⬆ デフォルトより上位: %s · %s(デフォルト %s)";;
    ja:seg_effort)   fmt="⚡%s < デフォルト%s!";;
    ja:seg_think)    fmt="🧠思考OFF!";;
    ja:seg_limit)    fmt="⏳5h上限 %s%%!";;
    ja:acct_unknown) fmt="アカウント不明(API key?)";;
    ja:notify_t)     fmt="model-guard：モデルが格下げ";;
    ja:notify_go)    fmt="%s → %s、停止。%s へ切替して続行します";;
    ja:notify_done)  fmt="%s に切替、タスク再開";;
    ja:notify_fail)  fmt="%s への切替失敗（%s）、停止のまま";;
    ja:notify_stop)  fmt="%s → %s、停止；%s";;
    ja:prompt)       fmt="続けて";;
    ko:stop)         fmt="🚨 model-guard: %s 이(가) 플래그되어 세션이 %s (으)로 강등되었습니다. 중지됨.";;
    ko:tail_switch)  fmt="%s (으)로 자동 전환 중…";;
    ko:tail_manual)  fmt="/model 로 %s (으)로 바꾼 뒤 다시 보내세요.";;
    ko:tail_halted)  fmt="%s 도 플래그 대상이라 자동 전환하지 않습니다. /model 로 고르세요.";;
    ko:block_wait)   fmt="🚨 model-guard: %s → %s 자동 전환 중입니다. 30초 안에 안 되면 /model 로 수동 전환.";;
    ko:band_switch)  fmt="🚨 플래그: %s → %s · %s (으)로 자동 전환 중…";;
    ko:band_manual)  fmt="🚨 플래그: %s → %s · 중지 · /model 로 %s";;
    ko:band_halted)  fmt="🚨 플래그로 %s 강등 · 중지 · /model 로 선택";;
    ko:band_recov)   fmt="🔁 %s 플래그 → %s 로 전환됨";;
    ko:band_down)    fmt="🚨🚨🚨 모델 다운그레이드! 현재: %s (%s) < %s";;
    ko:band_back)    fmt="지금 /model 로 되돌리세요!";;
    ko:band_up)      fmt="⬆ 기본보다 상위: %s · %s (기본 %s)";;
    ko:seg_effort)   fmt="⚡%s < 기본 %s!";;
    ko:seg_think)    fmt="🧠사고 OFF!";;
    ko:seg_limit)    fmt="⏳5h한도 %s%%!";;
    ko:acct_unknown) fmt="계정 알 수 없음 (API key?)";;
    ko:notify_t)     fmt="model-guard: 모델 강등";;
    ko:notify_go)    fmt="%s → %s, 중지. %s 로 전환 후 계속";;
    ko:notify_done)  fmt="%s 로 전환, 작업 재개";;
    ko:notify_fail)  fmt="%s 전환 실패 (%s), 중지 유지";;
    ko:notify_stop)  fmt="%s → %s, 중지; %s";;
    ko:prompt)       fmt="계속";;
    es:stop)         fmt="🚨 model-guard: %s fue marcado y la sesión bajó a %s. Detenido.";;
    es:tail_switch)  fmt="Cambiando automáticamente a %s…";;
    es:tail_manual)  fmt="Cambia a %s con /model y reenvía.";;
    es:tail_halted)  fmt="%s también sería marcado; sin cambio automático: elige con /model.";;
    es:block_wait)   fmt="🚨 model-guard: cambiando de %s a %s; espera. Si no cambia en 30 s, usa /model.";;
    es:band_switch)  fmt="🚨 marcado: %s → %s · cambiando a %s…";;
    es:band_manual)  fmt="🚨 marcado: %s → %s · detenido · /model a %s";;
    es:band_halted)  fmt="🚨 marcado, bajado a %s · detenido · elige con /model";;
    es:band_recov)   fmt="🔁 %s marcado → ahora en %s";;
    es:band_down)    fmt="🚨🚨🚨 ¡MODELO DEGRADADO! ahora: %s (%s) < %s";;
    es:band_back)    fmt="¡/model para volver YA!";;
    es:band_up)      fmt="⬆ superior al predeterminado: %s · %s (predet.: %s)";;
    es:seg_effort)   fmt="¡⚡%s < predet. %s!";;
    es:seg_think)    fmt="🧠 ¡thinking OFF!";;
    es:seg_limit)    fmt="¡⏳ límite 5h %s%%!";;
    es:acct_unknown) fmt="cuenta desconocida (¿API key?)";;
    es:notify_t)     fmt="model-guard: modelo degradado";;
    es:notify_go)    fmt="%s → %s, detenido. Cambiando a %s y continuando";;
    es:notify_done)  fmt="Cambiado a %s, tarea reanudada";;
    es:notify_fail)  fmt="No se pudo cambiar a %s (%s); sigue detenido";;
    es:notify_stop)  fmt="%s → %s, detenido; %s";;
    es:prompt)       fmt="Continúa.";;
    fr:stop)         fmt="🚨 model-guard : %s a été signalé, la session est passée à %s. Arrêt.";;
    fr:tail_switch)  fmt="Bascule automatique vers %s…";;
    fr:tail_manual)  fmt="Passe à %s avec /model puis renvoie.";;
    fr:tail_halted)  fmt="%s serait aussi signalé ; pas de bascule automatique : choisis avec /model.";;
    fr:block_wait)   fmt="🚨 model-guard : bascule de %s vers %s en cours ; patiente. Sans succès en 30 s, utilise /model.";;
    fr:band_switch)  fmt="🚨 signalé : %s → %s · bascule vers %s…";;
    fr:band_manual)  fmt="🚨 signalé : %s → %s · arrêté · /model vers %s";;
    fr:band_halted)  fmt="🚨 signalé, rétrogradé à %s · arrêté · choisis avec /model";;
    fr:band_recov)   fmt="🔁 %s signalé → passé à %s";;
    fr:band_down)    fmt="🚨🚨🚨 MODÈLE RÉTROGRADÉ ! actuel : %s (%s) < %s";;
    fr:band_back)    fmt="/model pour revenir !";;
    fr:band_up)      fmt="⬆ au-dessus du défaut : %s · %s (défaut : %s)";;
    fr:seg_effort)   fmt="⚡%s < défaut %s !";;
    fr:seg_think)    fmt="🧠 thinking OFF !";;
    fr:seg_limit)    fmt="⏳ limite 5h %s%% !";;
    fr:acct_unknown) fmt="compte inconnu (API key ?)";;
    fr:notify_t)     fmt="model-guard : modèle rétrogradé";;
    fr:notify_go)    fmt="%s → %s, arrêté. Bascule vers %s puis reprise";;
    fr:notify_done)  fmt="Passé à %s, tâche reprise";;
    fr:notify_fail)  fmt="Bascule vers %s échouée (%s) ; toujours arrêté";;
    fr:notify_stop)  fmt="%s → %s, arrêté ; %s";;
    fr:prompt)       fmt="Continue.";;
    de:stop)         fmt="🚨 model-guard: %s wurde markiert, die Sitzung ist auf %s herabgestuft. Gestoppt.";;
    de:tail_switch)  fmt="Wechsle automatisch zu %s…";;
    de:tail_manual)  fmt="Mit /model zu %s wechseln und erneut senden.";;
    de:tail_halted)  fmt="%s würde ebenfalls markiert; kein automatischer Wechsel: mit /model wählen.";;
    de:block_wait)   fmt="🚨 model-guard: Wechsel von %s zu %s läuft; bitte warten. Klappt es nicht in 30 s, /model verwenden.";;
    de:band_switch)  fmt="🚨 markiert: %s → %s · Wechsel zu %s…";;
    de:band_manual)  fmt="🚨 markiert: %s → %s · gestoppt · /model zu %s";;
    de:band_halted)  fmt="🚨 markiert, herabgestuft auf %s · gestoppt · mit /model wählen";;
    de:band_recov)   fmt="🔁 %s markiert → gewechselt zu %s";;
    de:band_down)    fmt="🚨🚨🚨 MODELL HERABGESTUFT! jetzt: %s (%s) < %s";;
    de:band_back)    fmt="sofort /model zurückwechseln!";;
    de:band_up)      fmt="⬆ über Standard: %s · %s (Standard: %s)";;
    de:seg_effort)   fmt="⚡%s < Standard %s!";;
    de:seg_think)    fmt="🧠 Thinking AUS!";;
    de:seg_limit)    fmt="⏳ 5h-Limit %s%%!";;
    de:acct_unknown) fmt="Konto unbekannt (API key?)";;
    de:notify_t)     fmt="model-guard: Modell herabgestuft";;
    de:notify_go)    fmt="%s → %s, gestoppt. Wechsel zu %s, dann weiter";;
    de:notify_done)  fmt="Gewechselt zu %s, Aufgabe fortgesetzt";;
    de:notify_fail)  fmt="Wechsel zu %s fehlgeschlagen (%s); bleibt gestoppt";;
    de:notify_stop)  fmt="%s → %s, gestoppt; %s";;
    de:prompt)       fmt="Weiter.";;
    pt:stop)         fmt="🚨 model-guard: %s foi sinalizado e a sessão caiu para %s. Parado.";;
    pt:tail_switch)  fmt="Trocando automaticamente para %s…";;
    pt:tail_manual)  fmt="Troque para %s com /model e reenvie.";;
    pt:tail_halted)  fmt="%s também seria sinalizado; sem troca automática: escolha com /model.";;
    pt:block_wait)   fmt="🚨 model-guard: trocando de %s para %s; aguarde. Se não trocar em 30 s, use /model.";;
    pt:band_switch)  fmt="🚨 sinalizado: %s → %s · trocando para %s…";;
    pt:band_manual)  fmt="🚨 sinalizado: %s → %s · parado · /model para %s";;
    pt:band_halted)  fmt="🚨 sinalizado, rebaixado para %s · parado · escolha com /model";;
    pt:band_recov)   fmt="🔁 %s sinalizado → agora em %s";;
    pt:band_down)    fmt="🚨🚨🚨 MODELO REBAIXADO! agora: %s (%s) < %s";;
    pt:band_back)    fmt="rode /model para voltar JÁ!";;
    pt:band_up)      fmt="⬆ acima do padrão: %s · %s (padrão: %s)";;
    pt:seg_effort)   fmt="⚡%s < padrão %s!";;
    pt:seg_think)    fmt="🧠 thinking OFF!";;
    pt:seg_limit)    fmt="⏳ limite 5h %s%%!";;
    pt:acct_unknown) fmt="conta desconhecida (API key?)";;
    pt:notify_t)     fmt="model-guard: modelo rebaixado";;
    pt:notify_go)    fmt="%s → %s, parado. Trocando para %s e continuando";;
    pt:notify_done)  fmt="Trocado para %s, tarefa retomada";;
    pt:notify_fail)  fmt="Troca para %s falhou (%s); segue parado";;
    pt:notify_stop)  fmt="%s → %s, parado; %s";;
    pt:prompt)       fmt="Continue.";;
    *:stop)          fmt="🚨 model-guard: %s was flagged and the session was downgraded to %s. Stopped.";;
    *:tail_switch)   fmt="Switching to %s automatically…";;
    *:tail_manual)   fmt="Switch to %s with /model and resend.";;
    *:tail_halted)   fmt="%s would be flagged too, so no automatic switch: pick one with /model.";;
    *:block_wait)    fmt="🚨 model-guard: switching from %s to %s, hold on. If it has not switched within 30 s, use /model.";;
    *:band_switch)   fmt="🚨 FLAGGED: %s → %s · switching to %s…";;
    *:band_manual)   fmt="🚨 FLAGGED: %s → %s · stopped · /model to %s";;
    *:band_halted)   fmt="🚨 FLAGGED, downgraded to %s · stopped · pick one with /model";;
    *:band_recov)    fmt="🔁 %s flagged → switched to %s";;
    *:band_down)     fmt="🚨🚨🚨 MODEL DOWNGRADED! now: %s (%s) < %s";;
    *:band_back)     fmt="run /model to switch back NOW!";;
    *:band_up)       fmt="⬆ above default: %s · %s (default: %s)";;
    *:seg_effort)    fmt="⚡%s < default %s!";;
    *:seg_think)     fmt="🧠 thinking OFF!";;
    *:seg_limit)     fmt="⏳ 5h limit %s%%!";;
    *:acct_unknown)  fmt="account unknown (API key?)";;
    *:notify_t)      fmt="model-guard: model downgraded";;
    *:notify_go)     fmt="%s → %s, stopped. Switching to %s and continuing";;
    *:notify_done)   fmt="Switched to %s, task resumed";;
    *:notify_fail)   fmt="Switch to %s failed (%s); still stopped";;
    *:notify_stop)   fmt="%s → %s, stopped; %s";;
    *:prompt)        fmt="Continue.";;
  esac
  # shellcheck disable=SC2059
  printf "$fmt" "$@"
}
