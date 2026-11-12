from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    ContentCreationRecord,
    CreationPublishAttemptRecord,
    TaskRecord,
)
from app.schemas.creations import CreationResponse


RETRYABLE_PUBLISH_STATUSES = {"failed", "cancelled"}
TERMINAL_PUBLISH_STATUSES = {"succeeded", "failed", "cancelled"}
PUBLISH_SUBMISSION_LEASE = timedelta(minutes=5)


def _coerce_attempt(value: object) -> int:
    if isinstance(value, bool):
        return 1
    try:
        attempt = int(value)
    except (TypeError, ValueError):
        return 1
    return max(attempt, 1)


def _recorded_state(state: dict[str, object]) -> dict[str, object]:
    recorded = dict(state)
    recorded["attempt"] = _coerce_attempt(recorded.get("attempt"))
    recorded["recordedAt"] = datetime.now(UTC).isoformat()
    return recorded


class PublishReservationError(ValueError):
    pass


@dataclass(frozen=True)
class PublishAttemptReservation:
    attempt: int
    external_id: str


class PublishAttemptMixin:
    """发布尝试的持久化、并发占位与单调状态机。"""

    session: Session

    def get_creation(
        self,
        user_id: str,
        account_id: str,
        creation_id: str,
    ) -> CreationResponse:
        raise NotImplementedError

    def _publish_attempts_for_record(
        self,
        record: ContentCreationRecord,
        *,
        for_update: bool = False,
    ) -> list[CreationPublishAttemptRecord]:
        query = (
            select(CreationPublishAttemptRecord)
            .where(
                CreationPublishAttemptRecord.creation_id == record.id,
                CreationPublishAttemptRecord.account_id == record.account_id,
                CreationPublishAttemptRecord.user_id == record.user_id,
            )
            .order_by(CreationPublishAttemptRecord.attempt)
            .execution_options(populate_existing=True)
        )
        if for_update:
            query = query.with_for_update()
        return list(self.session.scalars(query).all())

    def _seed_legacy_publish_attempts(
        self,
        record: ContentCreationRecord,
        *,
        fallback_platform: str = "",
    ) -> list[CreationPublishAttemptRecord]:
        existing = self._publish_attempts_for_record(record, for_update=True)
        if existing:
            return existing

        creation_state = dict(record.creation_state or {})
        raw_history = creation_state.get("publishHistory")
        raw_current = creation_state.get("publish")
        candidates = (
            [dict(item) for item in raw_history if isinstance(item, dict)]
            if isinstance(raw_history, list)
            else []
        )
        if isinstance(raw_current, dict):
            current = dict(raw_current)
            if not candidates or candidates[-1] != current:
                candidates.append(current)
        if not candidates:
            return []

        grouped: dict[int, list[dict[str, object]]] = {}
        for candidate in candidates:
            attempt = _coerce_attempt(candidate.get("attempt"))
            state = dict(candidate)
            state["attempt"] = attempt
            state.setdefault("recordedAt", datetime.now(UTC).isoformat())
            grouped.setdefault(attempt, []).append(state)

        values_by_attempt: list[dict[str, object]] = []
        now = datetime.now(UTC)
        for attempt in sorted(grouped):
            events = grouped[attempt]
            current = events[-1]
            external_id = next(
                (
                    str(item.get("externalId") or "")
                    for item in reversed(events)
                    if item.get("externalId")
                ),
                "",
            )
            if not external_id:
                continue
            platform = str(current.get("platform") or fallback_platform)
            current["externalId"] = external_id
            current["platform"] = platform
            values_by_attempt.append(
                {
                    "account_id": record.account_id,
                    "user_id": record.user_id,
                    "creation_id": record.id,
                    "attempt": attempt,
                    "external_id": external_id,
                    "platform": platform,
                    "status": str(current.get("status") or ""),
                    "state": current,
                    "history": events[-50:],
                    "created_at": now,
                    "updated_at": now,
                }
            )

        if self.session.get_bind().dialect.name == "sqlite":
            for values in values_by_attempt:
                self.session.execute(
                    sqlite_insert(CreationPublishAttemptRecord)
                    .values(**values)
                    .on_conflict_do_nothing()
                )
            self.session.flush()
            return self._publish_attempts_for_record(record, for_update=True)

        records = [CreationPublishAttemptRecord(**values) for values in values_by_attempt]
        self.session.add_all(records)
        self.session.flush()
        return records

    def _creation_state_with_publish_attempts(
        self,
        record: ContentCreationRecord,
    ) -> dict[str, object]:
        creation_state = dict(record.creation_state or {})
        attempts = self._publish_attempts_for_record(record)
        if not attempts:
            return creation_state
        latest = attempts[-1]
        history = [
            dict(event)
            for attempt in attempts
            for event in list(attempt.history or [])
            if isinstance(event, dict)
        ]
        creation_state["publish"] = dict(latest.state or {})
        creation_state["publishHistory"] = history[-50:]
        return creation_state

    def _locked_creation_record(
        self,
        user_id: str,
        account_id: str,
        creation_id: str,
    ) -> ContentCreationRecord:
        record = self.session.scalar(
            select(ContentCreationRecord)
            .where(
                ContentCreationRecord.id == creation_id,
                ContentCreationRecord.account_id == account_id,
                ContentCreationRecord.user_id == user_id,
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if record is None:
            raise StopIteration(creation_id)
        return record

    def reserve_creation_publish_attempt(
        self,
        user_id: str,
        account_id: str,
        creation_id: str,
        *,
        expected_target_platform: str,
        external_platform: str,
        android_id: str,
        retry: bool,
    ) -> PublishAttemptReservation:
        try:
            record = self._locked_creation_record(user_id, account_id, creation_id)
            if record.target_platform != expected_target_platform:
                raise PublishReservationError(
                    "creation target platform changed; reload before publishing"
                )

            tasks = list(
                self.session.scalars(
                    select(TaskRecord)
                    .where(
                        TaskRecord.account_id == account_id,
                        TaskRecord.creation_id == creation_id,
                    )
                    .with_for_update()
                ).all()
            )
            if not tasks:
                raise PublishReservationError("workflow task not found for creation")
            if len(tasks) != 1:
                raise PublishReservationError("creation must have exactly one workflow task")
            if tasks[0].status != "pending_review":
                raise PublishReservationError(
                    "workflow task must be pending_review before publishing"
                )

            attempts = self._seed_legacy_publish_attempts(
                record,
                fallback_platform=external_platform,
            )
            latest = attempts[-1] if attempts else None
            if latest is None:
                if retry:
                    raise PublishReservationError(
                        "publish retry requires a failed or cancelled current attempt"
                    )
                attempt = 1
            else:
                if not retry:
                    raise PublishReservationError("creation already has a publish attempt")
                if str(latest.status or "").strip().lower() not in RETRYABLE_PUBLISH_STATUSES:
                    raise PublishReservationError(
                        "publish retry requires a failed or cancelled current attempt"
                    )
                attempt = latest.attempt + 1

            base_external_id = f"starx_{creation_id}_{external_platform}"
            external_id = (
                base_external_id
                if attempt == 1
                else f"{base_external_id}_attempt_{attempt}"
            )
            pending_state = _recorded_state(
                {
                    "externalId": external_id,
                    "platform": external_platform,
                    "status": "pending",
                    "androidId": android_id,
                    "materialId": "",
                    "publishJobId": "",
                    "taskId": "",
                    "attempt": attempt,
                    "errorMessage": None,
                    "createdAt": None,
                    "triggeredAt": None,
                    "startedAt": None,
                    "finishedAt": None,
                }
            )
            self.session.add(
                CreationPublishAttemptRecord(
                    account_id=account_id,
                    user_id=user_id,
                    creation_id=creation_id,
                    attempt=attempt,
                    external_id=external_id,
                    platform=external_platform,
                    status="submitting",
                    state=pending_state,
                    history=[],
                )
            )
            record.updated_at = datetime.now(UTC)
            self.session.commit()
            return PublishAttemptReservation(attempt=attempt, external_id=external_id)
        except IntegrityError:
            self.session.rollback()
            raise PublishReservationError("publish attempt was already reserved") from None
        except Exception:
            self.session.rollback()
            raise

    def get_current_creation_publish_state(
        self,
        user_id: str,
        account_id: str,
        creation_id: str,
    ) -> dict[str, object] | None:
        record = self._locked_creation_record(user_id, account_id, creation_id)
        attempts = self._seed_legacy_publish_attempts(record)
        state = dict(attempts[-1].state or {}) if attempts else None
        self.session.commit()
        return state

    def update_creation_publish_state(
        self,
        user_id: str,
        account_id: str,
        creation_id: str,
        publish_state: dict[str, object],
        *,
        expected_external_id: str,
        expected_attempt: int,
    ) -> CreationResponse:
        record = self._locked_creation_record(user_id, account_id, creation_id)
        self._seed_legacy_publish_attempts(record)
        attempt_record = self.session.scalar(
            select(CreationPublishAttemptRecord)
            .where(
                CreationPublishAttemptRecord.creation_id == creation_id,
                CreationPublishAttemptRecord.account_id == account_id,
                CreationPublishAttemptRecord.user_id == user_id,
                CreationPublishAttemptRecord.external_id == expected_external_id,
                CreationPublishAttemptRecord.attempt == expected_attempt,
            )
            .with_for_update()
        )
        if attempt_record is not None:
            recorded = _recorded_state({**publish_state, "attempt": expected_attempt})
            incoming_status = str(recorded.get("status") or "").strip().lower()
            recorded["status"] = incoming_status
            history = [
                dict(item)
                for item in list(attempt_record.history or [])
                if isinstance(item, dict)
            ]
            history.append(recorded)
            normalized_stored_status = func.lower(
                func.trim(CreationPublishAttemptRecord.status)
            )
            now = datetime.now(UTC)
            updated = self.session.execute(
                update(CreationPublishAttemptRecord)
                .where(
                    CreationPublishAttemptRecord.id == attempt_record.id,
                    or_(
                        normalized_stored_status.not_in(TERMINAL_PUBLISH_STATUSES),
                        normalized_stored_status == incoming_status,
                    ),
                )
                .values(
                    status=incoming_status,
                    state=recorded,
                    history=history[-50:],
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            if updated.rowcount == 1:
                record.updated_at = now
        self.session.commit()
        return self.get_creation(user_id, account_id, creation_id)

    def fail_stale_publish_reservation(
        self,
        user_id: str,
        account_id: str,
        creation_id: str,
        *,
        expected_external_id: str,
        expected_attempt: int,
        error: str,
    ) -> CreationResponse | None:
        record = self._locked_creation_record(user_id, account_id, creation_id)
        self._seed_legacy_publish_attempts(record)
        attempt_record = self.session.scalar(
            select(CreationPublishAttemptRecord)
            .where(
                CreationPublishAttemptRecord.creation_id == creation_id,
                CreationPublishAttemptRecord.account_id == account_id,
                CreationPublishAttemptRecord.user_id == user_id,
                CreationPublishAttemptRecord.external_id == expected_external_id,
                CreationPublishAttemptRecord.attempt == expected_attempt,
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if attempt_record is None:
            self.session.commit()
            return None

        now = datetime.now(UTC)
        failed_state = _recorded_state(
            {
                **dict(attempt_record.state or {}),
                "externalId": expected_external_id,
                "status": "failed",
                "attempt": expected_attempt,
                "errorMessage": error,
                "finishedAt": now.isoformat(),
            }
        )
        history = [
            dict(item)
            for item in list(attempt_record.history or [])
            if isinstance(item, dict)
        ]
        history.append(failed_state)
        expired = self.session.execute(
            update(CreationPublishAttemptRecord)
            .where(
                CreationPublishAttemptRecord.id == attempt_record.id,
                CreationPublishAttemptRecord.status == "submitting",
                CreationPublishAttemptRecord.updated_at <= now - PUBLISH_SUBMISSION_LEASE,
            )
            .values(
                status="failed",
                state=failed_state,
                history=history[-50:],
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if expired.rowcount == 1:
            record.updated_at = now
        self.session.commit()
        if expired.rowcount != 1:
            return None
        return self.get_creation(user_id, account_id, creation_id)
