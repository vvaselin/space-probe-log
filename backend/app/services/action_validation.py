from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Probe
from app.repositories.read import signal_by_id, system_detail
from app.schemas.domain import ProposedAction


@dataclass
class ValidationResult:
    action: ProposedAction
    status: str
    message: str
    fallback_used: bool = False


def fallback(reason: str) -> ValidationResult:
    return ValidationResult(ProposedAction(action="wait", reason=reason), "fallback", reason, True)


def validate_action(db: Session, probe: Probe, proposed: ProposedAction) -> ValidationResult:
    if probe.energy <= 1:
        return fallback("エネルギー不足のため待機します")
    if proposed.action == "wait":
        return ValidationResult(proposed, "accepted", "待機可能")
    if proposed.action == "move":
        if not proposed.target_id:
            return fallback("移動対象が指定されていません")
        target = system_detail(db, proposed.target_id)
        if target is None:
            return fallback("LLMが存在しない恒星系または航行点を指定しました")
        if probe.target_id and proposed.target_id != probe.target_id:
            return fallback("航行中の目標と異なる移動先は受け付けません")
        if probe.fuel < 4:
            return fallback("燃料不足のため移動できません")
        if not probe.target_id and probe.fuel < 12:
            return fallback("新規航行を開始するには燃料が不足しています")
        if probe.propulsion < 25:
            return fallback("推進系の耐久値不足のため移動できません")
        return ValidationResult(proposed, "accepted", "移動可能")
    if proposed.action == "observe":
        if probe.sensors < 5:
            return fallback("センサーがほぼ停止しており観測できません")
        if probe.storage_used + 4 > probe.storage_capacity:
            return fallback("ストレージ容量不足のため観測データを保存できません")
        return ValidationResult(proposed, "accepted", "観測可能")
    if proposed.action == "investigate_signal":
        if not proposed.target_id:
            return fallback("信号IDが指定されていません")
        if probe.target_id:
            return fallback("航行中は新しい信号調査を開始できません")
        signal = signal_by_id(db, proposed.target_id)
        if signal is None:
            return fallback("LLMが存在しない信号を指定しました")
        if signal.system_id != probe.current_system_id:
            return fallback("現在地から届かない信号が指定されました")
        if probe.energy < 8:
            return fallback("エネルギー不足のため信号調査ができません")
        if probe.sensors < 10:
            return fallback("センサー耐久値不足のため信号調査ができません")
        if probe.storage_used + 6 > probe.storage_capacity:
            return fallback("ストレージ容量不足のため信号データを保存できません")
        return ValidationResult(proposed, "accepted", "信号調査可能")
    if proposed.action == "collect_resource":
        if probe.target_id:
            return fallback("航行中は資源採取できません")
        system = system_detail(db, probe.current_system_id)
        if system is None or not system.resources:
            return fallback("採取可能な資源がありません")
        if probe.energy < 6 or probe.storage_used + 3 > probe.storage_capacity:
            return fallback("資源採取に必要なエネルギーまたは容量が不足しています")
        return ValidationResult(proposed, "accepted", "資源採取可能")
    return fallback("未対応の行動が指定されました")
