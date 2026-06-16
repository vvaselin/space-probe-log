from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.read import discoveries_for_events, events_for_log, log_by_id, logs
from app.schemas.domain import LogDetail, LogListItem

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("", response_model=list[LogListItem])
def list_logs(db: Session = Depends(get_db)):
    return logs(db)


@router.get("/{log_id}", response_model=LogDetail)
def get_log(log_id: int, db: Session = Depends(get_db)):
    log = log_by_id(db, log_id)
    if log is None:
        raise HTTPException(status_code=404, detail="log not found")
    discoveries = discoveries_for_events(db, log.related_event_ids)
    events = events_for_log(db, log)
    observations = []
    for event in events:
        observations.extend(event.data.get("observations", []))
    if not observations:
        observations = [
            {"type": item.observation_type, "value": item.value, "reliability": item.reliability, "sighting_level": "confirmed"}
            for item in discoveries
        ]
    interpretations = []
    for event in events:
        interpretations.extend(event.data.get("interpretations", []))
    if not interpretations:
        interpretations = [interp for item in discoveries for interp in item.interpretations]
    return {
        "id": log.id,
        "title": log.title,
        "summary": log.summary,
        "body_markdown": log.body_markdown,
        "log_type": log.log_type,
        "mission_time": log.mission_time,
        "generated_at": log.generated_at,
        "probe_position": log.probe_position,
        "related_event_ids": log.related_event_ids,
        "related_body_ids": log.related_body_ids,
        "probe_state_snapshot": log.probe_state_snapshot,
        "communication_status": log.communication_status,
        "reliability": log.reliability,
        "observations": observations,
        "interpretations": interpretations,
    }
