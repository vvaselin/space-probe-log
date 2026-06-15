from app.schemas.domain import ActionContext, GeneratedLog, LogContext, ProposedAction


class MockLLMClient:
    async def propose_action(self, context: ActionContext) -> ProposedAction:
        probe = context.probe
        if probe.get("target_id"):
            return ProposedAction(action="move", target_id=str(probe["target_id"]), reason="航行中の目標へ向けて外縁航路を維持する")
        if probe["storage_used"] >= probe["storage_capacity"] - 2:
            return ProposedAction(action="wait", reason="ストレージ容量が逼迫しているため、通信同期と整理を優先する")
        if context.visible_signals:
            return ProposedAction(
                action="investigate_signal",
                target_id=context.visible_signals[0]["id"],
                reason="長距離移動の前に、既知の未調査信号を確認するべきだから",
            )
        if context.navigation_targets and probe["fuel"] >= 12 and probe["propulsion"] >= 25 and probe["mission_time"] >= 2:
            target = context.navigation_targets[0]
            return ProposedAction(
                action="move",
                target_id=target["id"],
                reason=f"既知信号の調査を終えたため、外側の航行目標 {target['name']} へ向かう",
            )
        if context.nearby_systems:
            return ProposedAction(action="observe", target_id=context.nearby_systems[0]["id"], reason="現在地周辺の基礎観測を続ける")
        return ProposedAction(action="wait", reason="有効な対象がないため、姿勢制御を保って待機する")

    async def generate_log(self, context: LogContext) -> GeneratedLog:
        event = context.event
        mission_time = context.probe_snapshot["mission_time"]
        facts = "\n".join(f"- {obs.type}: {obs.value} (信頼度 {obs.reliability:.2f})" for obs in context.observations)
        if not facts:
            facts = "- 新規の観測事実はありません。"
        hypotheses = "\n".join(f"- {item.hypothesis} (確信度 {item.confidence:.2f})" for item in context.interpretations)
        if not hypotheses:
            hypotheses = "- 新しい仮説はありません。"
        target = context.probe_snapshot.get("target_id")
        voyage_note = "外縁方向へ航行中。" if target else "姿勢制御は安定。"
        intro = (
            "INSOMNIA-07の外殻を、星間の暗さが静かに撫でていく。"
            "OVISは記録を開き、まだ名付けきれない景色に短い見出しを置いた。"
        )
        body = (
            f"{intro}\n\n"
            f"## 確認済みの事実\n{facts}\n\n"
            f"## OVISの解釈\n{hypotheses}\n\n"
            f"## 航行メモ\n{event['summary']}\n{voyage_note}\n"
        )
        return GeneratedLog(
            title=f"INSOMNIA-07 航行記 T+{mission_time}",
            summary=f"OVISは{event['event_type']}の結果を記録した。{event['summary']}",
            body_markdown=body,
            reliability=min([obs.reliability for obs in context.observations], default=0.9),
        )
