import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.routes.uploads import get_direct_upload_service
from app.api.deps import get_service
from app.db.models import AccountRecord, DirectUploadRecord, UserRecord
from app.main import app
from app.schemas.uploads import PresignUploadRequest, UploadedObjectRef
from app.services.db_service import DBService
from app.services.object_storage import ObjectStat
from app.services.uploads import DirectUploadError, DirectUploadService
from tests.db_test_utils import db_session


class FakeDirectStorage:
    def __init__(self) -> None:
        self.objects: dict[str, ObjectStat] = {}
        self.signed: list[tuple[str, str, int]] = []

    def public_url(self, key: str) -> str:
        return f"https://oss.example.test/{key}"

    def presign_put(self, key: str, content_type: str, expires_seconds: int) -> str:
        self.signed.append((key, content_type, expires_seconds))
        return f"https://upload.example.test/{key}?signature=temporary"

    def stat_object(self, key: str) -> ObjectStat:
        try:
            return self.objects[key]
        except KeyError as exc:
            raise RuntimeError("object not found") from exc


def _auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "demo@starx.ai", "password": "demo123"},
    )
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


def test_presign_route_creates_user_scoped_single_object_permission():
    with db_session() as session:
        storage = FakeDirectStorage()
        uploads = DirectUploadService(session, storage)
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_direct_upload_service] = lambda: uploads
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = client.get("/api/v1/accounts", headers=headers).json()[0]["id"]
            response = client.post(
                "/api/v1/uploads/presign",
                json={
                    "accountId": account_id,
                    "purpose": "generation_reference",
                    "filename": "../reference.png",
                    "contentType": "image/png",
                    "sizeBytes": 123,
                },
                headers=headers,
            )

            assert response.status_code == 200
            payload = response.json()
            assert payload["method"] == "PUT"
            assert payload["headers"] == {"Content-Type": "image/png"}
            assert f"/accounts/{account_id}/generation-reference/" in payload["objectKey"]
            assert ".." not in payload["objectKey"]
            record = session.get(DirectUploadRecord, payload["uploadId"])
            assert record is not None
            assert record.user_id == "u_001"
            assert record.filename == "reference.png"
            assert storage.signed == [
                (payload["objectKey"], "image/png", 300)
            ]
        finally:
            app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("background.jpg", "image/jpeg"),
        ("bubble.png", "image/png"),
        ("background-music.mp3", "audio/mpeg"),
    ],
)
def test_presign_route_accepts_digital_human_editing_asset(filename, content_type):
    with db_session() as session:
        storage = FakeDirectStorage()
        uploads = DirectUploadService(session, storage)
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_direct_upload_service] = lambda: uploads
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = client.get("/api/v1/accounts", headers=headers).json()[0]["id"]
            response = client.post(
                "/api/v1/uploads/presign",
                json={
                    "accountId": account_id,
                    "purpose": "digital_human_editing_asset",
                    "filename": filename,
                    "contentType": content_type,
                    "sizeBytes": 1024,
                },
                headers=headers,
            )

            assert response.status_code == 200
            payload = response.json()
            assert payload["headers"] == {"Content-Type": content_type}
            assert (
                f"/accounts/{account_id}/digital-human-editing-asset/"
                in payload["objectKey"]
            )
            record = session.get(DirectUploadRecord, payload["uploadId"])
            assert record is not None
            assert record.purpose == "digital_human_editing_asset"
        finally:
            app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("music.wav", "audio/wav"),
        ("music.mp4", "video/mp4"),
    ],
)
def test_presign_route_accepts_background_music_audio_and_mp4(
    filename,
    content_type,
):
    with db_session() as session:
        storage = FakeDirectStorage()
        uploads = DirectUploadService(session, storage)
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_direct_upload_service] = lambda: uploads
        try:
            client = TestClient(app)
            headers = _auth_headers(client)
            account_id = client.get("/api/v1/accounts", headers=headers).json()[0]["id"]
            response = client.post(
                "/api/v1/uploads/presign",
                json={
                    "accountId": account_id,
                    "purpose": "digital_human_background_music",
                    "filename": filename,
                    "contentType": content_type,
                    "sizeBytes": 1024,
                },
                headers=headers,
            )

            assert response.status_code == 200
            payload = response.json()
            assert "/digital-human-background-music/" in payload["objectKey"]
        finally:
            app.dependency_overrides.clear()


def test_verify_ref_checks_oss_metadata_and_rejects_cross_user_consumption():
    with db_session() as session:
        storage = FakeDirectStorage()
        uploads = DirectUploadService(session, storage)
        account = session.scalar(select(AccountRecord).where(AccountRecord.user_id == "u_001"))
        assert account is not None
        signed = uploads.create_presigned_upload(
            user_id="u_001",
            payload=PresignUploadRequest(
                accountId=account.id,
                purpose="publish_image",
                filename="cover.webp",
                contentType="image/webp",
                sizeBytes=5,
            ),
        )
        storage.objects[signed.objectKey] = ObjectStat(
            size_bytes=5,
            content_type="image/webp",
            etag="etag-1",
        )
        ref = UploadedObjectRef(
            uploadId=signed.uploadId,
            url=signed.objectUrl,
            filename="cover.webp",
            contentType="image/webp",
            sizeBytes=5,
            etag="etag-1",
        )

        record = uploads.verify_ref(
            user_id="u_001",
            ref=ref,
            purposes={"publish_image"},
            account_id=account.id,
        )
        assert record is not None
        assert record.status == "uploaded"
        assert record.actual_size_bytes == 5

        session.add(
            UserRecord(
                id="u_other",
                email="other@example.test",
                password_hash="unused",
                nickname="other",
                status="active",
            )
        )
        session.flush()
        with pytest.raises(DirectUploadError, match="another user"):
            uploads.verify_ref(
                user_id="u_other",
                ref=ref,
                purposes={"publish_image"},
                account_id=account.id,
            )


@pytest.mark.parametrize(
    ("filename", "content_type", "size_bytes"),
    [
        ("payload.exe", "image/png", 10),
        ("payload.png", "application/octet-stream", 10),
        ("payload.png", "image/png", 10 * 1024 * 1024 + 1),
    ],
)
def test_presign_rejects_invalid_file_declarations(filename, content_type, size_bytes):
    with db_session() as session:
        storage = FakeDirectStorage()
        uploads = DirectUploadService(session, storage)
        account = session.scalar(select(AccountRecord).where(AccountRecord.user_id == "u_001"))
        with pytest.raises(DirectUploadError):
            uploads.create_presigned_upload(
                user_id="u_001",
                payload=PresignUploadRequest(
                    accountId=account.id,
                    purpose="generation_reference",
                    filename=filename,
                    contentType=content_type,
                    sizeBytes=size_bytes,
                ),
            )
