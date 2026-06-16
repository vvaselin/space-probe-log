from app.schemas.domain import ActionContext, GeneratedLog, LogContext, ObservationFact, ProposedAction


class MockLLMClient:
    async def propose_action(self, context: ActionContext) -> ProposedAction:
        probe = context.probe
        if probe.get("target_id"):
            return ProposedAction(action="move", target_id=str(probe["target_id"]), reason="航行中の目標へ向けて推進を継続する。")
        if probe["storage_used"] >= probe["storage_capacity"] - 2:
            return ProposedAction(action="wait", reason="ストレージ容量が逼迫しているため、通信同期と整理を優先する。")
        if context.visible_signals:
            return ProposedAction(
                action="investigate_signal",
                target_id=context.visible_signals[0]["id"],
                reason="長距離移動の前に、現在地で受信可能な未調査信号を確認する。",
            )
        if context.navigation_targets and probe["fuel"] >= 12 and probe["propulsion"] >= 25 and probe["mission_time"] >= 2:
            target = next((item for item in context.navigation_targets if not item.get("visited")), context.navigation_targets[0])
            return ProposedAction(
                action="move",
                target_id=target["id"],
                reason=f"現在地で優先する信号がないため、外向きの航行候補 {target['name']} へ向かう。",
            )
        if context.nearby_systems:
            return ProposedAction(action="observe", target_id=context.nearby_systems[0]["id"], reason="現在地の基礎観測を継続する。")
        return ProposedAction(action="wait", reason="有効な対象がないため、姿勢制御と通信同期を維持する。")

    async def generate_log(self, context: LogContext) -> GeneratedLog:
        event = context.event
        snapshot = context.probe_snapshot
        mission_time = snapshot["mission_time"]
        action = context.action["action"]
        observations = context.observations
        interpretations = context.interpretations
        passive = [obs for obs in observations if obs.type.startswith("passive")]
        confirmed = [obs for obs in observations if obs.sighting_level == "confirmed"]

        if action == "move":
            title = _move_title(passive)
            opening = _move_opening(passive)
        elif action == "investigate_signal":
            title = "途切れない信号"
            opening = "受信帯域の端に、細い反復が残っていました。私は観測窓を少しだけ延長し、その揺れを記録しました。"
        elif action == "observe":
            title = "観測窓の中の星系"
            opening = "センサーを現在地の天体へ向けました。輪郭は静かで、測距値は大きくは揺れていません。"
        elif action == "collect_resource":
            title = "航行のために残すもの"
            opening = "採取装置を短時間だけ展開しました。得られた量は多くありませんが、外側へ進むには十分な意味があります。"
        else:
            title = "姿勢制御下の待機"
            opening = "探査機は移動していません。姿勢制御と通信同期を維持し、次の判断を壊さないための短い停止として記録します。"

        fact_lines = [_format_observation(obs) for obs in observations]
        hypothesis_lines = [f"- {item.hypothesis}（確信度 {item.confidence:.2f}）" for item in interpretations]
        confirmed_note = (
            "今回の受動観測は発見確定ではありません。明示観測または信号調査を行ったものだけを確認済みとして扱います。"
            if passive and not confirmed
            else "確認済みの観測だけを長期記憶へ保存します。"
        )
        body = (
            f"{opening}\n\n"
            "## 確認済みの事実\n"
            f"{event['summary']}\n"
            f"{chr(10).join(fact_lines) if fact_lines else '- 新規の観測事実はありません。'}\n\n"
            "## OVISの解釈\n"
            f"{chr(10).join(hypothesis_lines) if hypothesis_lines else '- 新しい解釈はありません。'}\n\n"
            "## 記録\n"
            f"{confirmed_note} 地球へ送るには小さな変化かもしれませんが、航路上の光の差分として削除せず保持します。"
        )
        reliability = min([obs.reliability for obs in observations], default=0.9)
        return GeneratedLog(
            title=f"INSOMNIA-07 {title} / T+{mission_time}",
            summary=f"{event['summary']} OVISは航行記録として保存しました。",
            body_markdown=body,
            reliability=reliability,
        )


def _format_observation(obs: ObservationFact) -> str:
    level_label = {"detected": "検出", "resolved": "照合", "confirmed": "確認"}[obs.sighting_level]
    extra = f" / {obs.distance_hint}" if obs.distance_hint else ""
    return f"- {level_label}: {obs.value}（信頼度 {obs.reliability:.2f}{extra}）"


def _move_title(passive: list[ObservationFact]) -> str:
    if any(obs.type == "passive_signal" for obs in passive):
        return "航路上の微かな反復"
    if any(obs.source == "sol" for obs in passive):
        return "後方視野の太陽系"
    return "外側へ向かう航路"


def _move_opening(passive: list[ObservationFact]) -> str:
    if not passive:
        return "推進系の出力を低く保ち、既定航路を進みました。航路線はまだ外側へ伸びています。"
    first = passive[0]
    second = passive[1] if len(passive) > 1 else None
    text = f"{first.value}。"
    if second:
        text += f" 同時に、{second.value}。"
    text += " どちらも航路を変えるほどの確定情報ではありませんが、進行方向をただの空白とは扱わない理由になります。"
    return text
