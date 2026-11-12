from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import AccountRecord, DirectUploadRecord
from app.schemas.uploads import PresignUploadRequest, PresignUploadResponse, UploadedObjectRef
from app.services.object_storage import ObjectStat, default_object_storage
from app.services.uploads.policy import policy_for, validate_file_declaration


class DirectUploadError(ValueError):
    pass


class DirectUploadService:
    def __init__(self, session: Session, storage=default_object_storage) -> None:
        self.session = session
        self.storage = storage

    def create_presigned_upload(
        self,
        *,
        user_id: str,
        payload: PresignUploadRequest,
    ) -> PresignUploadResponse:
        try:
            policy, content_type, suffix = validate_file_declaration(
                purpose=payload.purpose,
                filename=payload.filename,
                content_type=payload.contentType,
                size_bytes=payload.sizeBytes,
            )
        except ValueError as exc:
            raise DirectUploadError(str(exc)) from exc
        account_id = str(payload.accountId or "").strip() or None
        if policy.account_required and not account_id:
            raise DirectUploadError("accountId is required for this upload purpose")
        if account_id is not None:
            account = self.session.scalar(
                select(AccountRecord).where(
                    AccountRecord.id == account_id,
                    AccountRecord.user_id == user_id,
                    AccountRecord.status == "active",
                )
            )
            if account is None:
                raise DirectUploadError("account is not available for the current user")

        now = datetime.now(UTC)
        upload_id = f"upl_{uuid4().hex}"
        key_parts = [
            settings.object_storage_upload_dir,
            "direct-uploads",
            "users",
            user_id,
            *(["accounts", account_id] if account_id else []),
            payload.purpose.replace("_", "-"),
            now.strftime("%Y/%m/%d"),
            f"{upload_id}{suffix}",
        ]
        object_key = "/".join(
            str(part).strip("/") for part in key_parts if str(part or "").strip("/")
        )
        expires_seconds = settings.direct_upload_url_expire_seconds
        expires_at = now + timedelta(seconds=expires_seconds)
        object_url = self.storage.public_url(object_key)
        upload_url = self.storage.presign_put(object_key, content_type, expires_seconds)
        record = DirectUploadRecord(
            id=upload_id,
            user_id=user_id,
            account_id=account_id,
            purpose=payload.purpose,
            object_key=object_key,
            object_url=object_url,
            filename=Path(payload.filename).name,
            declared_content_type=content_type,
            declared_size_bytes=payload.sizeBytes,
            sha256=payload.sha256,
            status="pending",
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )
        self.session.add(record)
        self.session.commit()
        return PresignUploadResponse(
            uploadId=upload_id,
            uploadUrl=upload_url,
            objectKey=object_key,
            objectUrl=object_url,
            headers={"Content-Type": content_type},
            expiresAt=expires_at,
            maxSizeBytes=policy.max_size_bytes,
        )

    def verify_ref(
        self,
        *,
        user_id: str,
        ref: UploadedObjectRef,
        purposes: Iterable[str],
        account_id: str | None = None,
        allow_external: bool = False,
    ) -> DirectUploadRecord | None:
        accepted_purposes = set(purposes)
        record = None
        if ref.uploadId:
            record = self.session.get(DirectUploadRecord, ref.uploadId)
        if record is None:
            record = self.session.scalar(
                select(DirectUploadRecord).where(DirectUploadRecord.object_url == ref.url)
            )
        if record is None:
            if allow_external:
                return None
            raise DirectUploadError("uploaded OSS object was not issued by this service")
        if record.user_id != user_id:
            raise DirectUploadError("uploaded OSS object belongs to another user")
        if record.purpose not in accepted_purposes:
            raise DirectUploadError("uploaded OSS object purpose does not match this operation")
        if account_id and record.account_id != account_id:
            raise DirectUploadError("uploaded OSS object belongs to another account")
        if ref.url != record.object_url:
            raise DirectUploadError("uploaded OSS object URL does not match its uploadId")

        stat = self.storage.stat_object(record.object_key)
        self._validate_stat(record, ref, stat)
        now = datetime.now(UTC)
        record.actual_content_type = stat.content_type
        record.actual_size_bytes = stat.size_bytes
        record.etag = stat.etag
        record.status = "uploaded" if record.status == "pending" else record.status
        record.updated_at = now
        self.session.flush()
        return record

    def verify_urls(
        self,
        *,
        user_id: str,
        urls: Iterable[str],
        purposes: Iterable[str],
        account_id: str | None = None,
        allow_external: bool = False,
    ) -> list[DirectUploadRecord]:
        records = []
        for url in urls:
            clean_url = str(url or "").strip()
            if not clean_url:
                continue
            record = self.verify_ref(
                user_id=user_id,
                ref=UploadedObjectRef(url=clean_url),
                purposes=purposes,
                account_id=account_id,
                allow_external=allow_external,
            )
            if record is not None:
                records.append(record)
        return records

    @staticmethod
    def mark_consumed(
        records: Iterable[DirectUploadRecord],
        *,
        resource_type: str,
        resource_id: str,
    ) -> None:
        now = datetime.now(UTC)
        for record in records:
            record.status = "consumed"
            record.consumed_by_type = resource_type
            record.consumed_by_id = resource_id
            record.consumed_at = record.consumed_at or now
            record.updated_at = now

    @staticmethod
    def _validate_stat(
        record: DirectUploadRecord,
        ref: UploadedObjectRef,
        stat: ObjectStat,
    ) -> None:
        actual_type = str(stat.content_type or "").split(";", 1)[0].strip().lower()
        if stat.size_bytes <= 0:
            raise DirectUploadError("uploaded OSS object is empty or missing")
        policy = policy_for(record.purpose)
        if stat.size_bytes > policy.max_size_bytes:
            raise DirectUploadError("uploaded OSS object exceeds the allowed size")
        if stat.size_bytes != record.declared_size_bytes:
            raise DirectUploadError("uploaded OSS object size does not match the signed declaration")
        if actual_type != record.declared_content_type:
            raise DirectUploadError("uploaded OSS object content type does not match the signed declaration")
        if ref.sizeBytes is not None and ref.sizeBytes != stat.size_bytes:
            raise DirectUploadError("uploaded OSS object size metadata does not match OSS")
        expected_etag = str(ref.etag or "").strip('"')
        if expected_etag and stat.etag and expected_etag != stat.etag:
            raise DirectUploadError("uploaded OSS object ETag does not match OSS")
