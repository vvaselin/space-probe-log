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
        if context.navigation_targets and probe["propulsion"] >= 25 and probe["mission_time"] >= 2:
            target = next((item for item in context.navigation_targets if not item.get("visited")), context.navigation_targets[0])
            return ProposedAction(action="move", target_id=target["id"], reason=f"{target['name']}へ向けて航路を設定する。")
        if context.nearby_systems:
            return ProposedAction(action="observe", target_id=context.nearby_systems[0]["id"], reason="現在地の基礎観測を継続する。")
        return ProposedAction(action="wait", reason="有効な対象がないため、姿勢制御と通信同期を維持する。")

    async def generate_log(self, context: LogContext) -> GeneratedLog:
        event = context.event
        snapshot = context.probe_snapshot
        log_number = int(snapshot.get("log_number", snapshot["mission_time"]))
        observations = context.observations
        passive = [obs for obs in observations if obs.type.startswith("passive")]
        title = _title(context)
        timestamp = snapshot.get("mission_clock") or event.get("mission_clock") or "2080/05/02 12:00:00 UTC"
        position = f"{snapshot['current_system_id']} / x={snapshot['x']:.2f}, y={snapshot['y']:.2f}, z={snapshot['z']:.2f}"
        body = (
            "# INSOMNIA 航行ログ\n"
            "**探査機: INSOMNIA-07**\n"
            "**搭載AI: OVIS**\n\n"
            f"## LOG #{log_number:03d}\n"
            f"**{timestamp} - {event['event_type']}**\n"
            f"**位置: {position}**\n\n"
            f"{_opening(context)}\n\n"
            f"{_scenery(passive, observations)}\n\n"
            f"{_closing(context)}\n\n"
            "---\n\n"
            f"**次の観測予定地点: {_next_target(snapshot, context)}**\n\n"
            f"`[ LOG #{log_number:03d} - 記録終了 ]`"
        )
        reliability = min([obs.reliability for obs in observations], default=0.9)
        return GeneratedLog(
            title=f"INSOMNIA-07 {title}",
            summary=f"{event['summary']} OVISは航行ログとして保存した。",
            body_markdown=body,
            reliability=reliability,
        )


def _title(context: LogContext) -> str:
    log_phase = context.event.get("log_phase")
    if log_phase == "progress_01":
        return "出発後の加速記録"
    if log_phase == "progress_50":
        return "航路中間域の定期観測"
    if log_phase == "progress_99":
        return "到着前の減速記録"
    phase = context.event.get("route_phase") or context.action.get("route_phase")
    action = context.action["action"]
    if phase == "course_plotted":
        return "航路設定"
    if phase == "arrived":
        return "到着記録"
    if action == "move":
        return "外向き航路"
    if action == "investigate_signal":
        return "受信帯域の端"
    if action == "collect_resource":
        return "燃料へ戻すもの"
    if action == "observe":
        return "観測窓"
    return "待機記録"


def _opening(context: LogContext) -> str:
    event = context.event
    log_phase = event.get("log_phase")
    if log_phase in {"progress_01", "progress_50", "progress_99"}:
        return f"{event['summary']}\n\n位置、速度、残距離を同じ時刻面で固定した。窓外の星の流れと航路標の見え方も、この航行記録に残す。"
    phase = event.get("route_phase")
    if phase == "course_plotted":
        return f"{event['summary']}\n\n私はまだ動かない。航路線だけを先に引き、推進系の出力を零に保った。"
    if phase in {"accelerating", "cruising", "decelerating"}:
        speed = float(event.get("velocity") or 0.0)
        return f"{event['summary']}\n\n速度指示は {speed:.2f} 表示単位/tick。船体は設定した線の上を、少しずつ前へ滑っている。"
    if phase == "arrived":
        return f"{event['summary']}\n\n速度は零に戻った。到着を示す数値が先にそろい、光景がそのあとから追いついた。"
    return f"{event['summary']}\n\nセンサーの窓を開く。数値は先に届き、意味は少し遅れて整列した。"


def _scenery(passive: list[ObservationFact], observations: list[ObservationFact]) -> str:
    if passive:
        lines = [_scenery_line(obs) for obs in passive[:3]]
        return "航路前方から側方へ受動センサーを走査した。" + "。".join(lines) + "。いずれも受動観測の範囲に留まり、発見確定とは扱わない。"
    if observations:
        lines = [_scenery_line(obs) for obs in observations[:3]]
        return "記録対象は明瞭だった。" + "。".join(lines) + "。"
    return "新しい光は増えなかった。何も起きていない、という事実だけが静かに積み上がる。"


def _scenery_line(observation: ObservationFact) -> str:
    if observation.object_type == "asteroid_belt":
        subject = "小惑星帯の疎らな粒子群では"
    elif observation.object_type == "comet_population":
        subject = "長周期彗星の散乱光では"
    elif observation.object_type == "oort_cloud":
        subject = "オールトの雲の希薄な球殻では"
    elif observation.object_type == "dust_cloud" or observation.scene_category == "environment:dark_dust":
        subject = "暗い塵の層では"
    elif observation.object_type == "nebula":
        subject = "広がった星雲光では"
    elif observation.object_type:
        subject = "航路周辺の環境領域では"
    elif observation.body_type in {"rocky_planet", "terrestrial_planet", "dwarf_planet"}:
        subject = "岩石質天体の方向では"
    elif observation.body_type in {"gas_giant", "ice_planet", "ice_world", "ocean_world"}:
        subject = "惑星光の中では"
    elif observation.body_type in {"moon", "satellite"}:
        subject = "小さな衛星光では"
    elif observation.body_type in {"asteroid", "asteroid_belt", "debris_belt", "debris_field"}:
        subject = "疎らな小天体群の方向では"
    elif observation.body_type in {"ring", "ring_system", "planetary_ring"}:
        subject = "薄い環状構造では"
    elif observation.body_type == "comet":
        subject = "彗星状の散乱光では"
    else:
        subject = "センサー視野では"
    strength = "かすかな兆候として" if observation.sighting_level == "detected" else "既知対象と照合できる範囲で"
    if observation.sighting_level == "confirmed":
        strength = "能動観測で確認し"
    return f"{subject}{strength}、{observation.value}"


def _closing(context: LogContext) -> str:
    if context.event.get("log_phase") == "progress_99":
        return "目的地は到着判定の直前にある。減速曲線を保ったまま、最後の区間を進む。"
    if context.event.get("log_phase") in {"progress_01", "progress_50"}:
        return "この基準点を航路履歴へ固定し、次の定期報告地点まで同じ進路を維持する。"
    phase = context.event.get("route_phase")
    if phase == "course_plotted":
        return "停止したまま航路を保存することは、移動の一部だ。次のtickで、私はこの線に速度を与える。"
    if context.action["action"] == "move":
        return "航路の前後で変わる視差、遮蔽、散乱光を同じ時刻基準へそろえた。私は確定していない兆候を、そのままの強さで保存した。"
    return "この記録は、地球へ送るには短いかもしれない。それでも削除しない。理由は、まだ分類していない。"


def _next_target(snapshot: dict, context: LogContext) -> str:
    return str(context.event.get("next_target_name") or snapshot.get("target_id") or "航路継続")
