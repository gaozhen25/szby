from __future__ import annotations

import asyncio
import logging
import sqlite3
import socket
from uuid import uuid4

import grpc
import httpx
import pytest

from adapter_gateway.app import create_app
from adapter_gateway.config import GatewayServerConfig
from adapter_gateway.grpc_client import IMCallError, IMGrpcClient
from adapter_gateway.proto import im_pb2, im_pb2_grpc
from adapter_gateway.store import GatewayStore
from message_adapter.config import AdapterConfig
from message_adapter.gateway.control import ControlGatewayClient, ControlGatewayError
from message_adapter.storage import CredentialStore


class FakeIMClient:
    def __init__(self):
        self.actor_calls: list[tuple[dict, str]] = []
        self.audience_calls: list[dict] = []

    async def ready(self, timeout=2.0):
        return True

    async def ensure_actor(self, account, activation_code):
        self.actor_calls.append((account, activation_code))
        return {
            "actor": {"actorID": f"im-{account['platform_actor_id']}"},
            "account": {"openIMID": f"openim-{account['platform_actor_id']}"},
        }

    async def ensure_audience(self, account):
        self.audience_calls.append(account)
        return {"account": {"audiencePlatformID": account["platform_audience_id"]}, "created": True}

    async def close(self):
        return None


def server_config(tmp_path):
    return GatewayServerConfig(
        database=tmp_path / "gateway.sqlite3",
        im_grpc_target="im.internal:30500",
    )


def activation_payload(*, device_id=None, platform_actor_id="actor-1001"):
    return {
        "device_id": str(device_id or uuid4()),
        "activation_code": "activation-secret",
        "accounts": [
            {
                "platform": "douyin",
                "platform_actor_id": platform_actor_id,
                "nickname": "平台昵称",
                "avatar_url": "https://example.test/avatar.png",
                "profile": {"region": "cn"},
            }
        ],
    }


def test_activation_registers_device_and_scopes_audience_calls(tmp_path):
    async def scenario():
        store = GatewayStore(tmp_path / "gateway.sqlite3")
        im = FakeIMClient()
        app = create_app(server_config(tmp_path), im_client=im, store=store)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            activated = await client.post("/v1/activate", json=activation_payload())
            assert activated.status_code == 200
            token = activated.json()["device_token"]
            assert token.startswith("dvc_")
            assert activated.json()["accounts"][0]["actor_id"] == "im-actor-1001"

            unauthorized = await client.post(
                "/v1/audiences/ensure",
                json={
                    "platform": "douyin",
                    "platform_actor_id": "actor-1001",
                    "platform_audience_id": "audience-2002",
                },
            )
            assert unauthorized.status_code == 401

            ensured = await client.post(
                "/v1/audiences/ensure",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "platform": "douyin",
                    "platform_actor_id": "actor-1001",
                    "platform_audience_id": "audience-2002",
                    "nickname": "联系人",
                    "profile": {},
                },
            )
            assert ensured.status_code == 200
            assert im.audience_calls[0]["platform_audience_id"] == "audience-2002"

        connection = sqlite3.connect(store.path)
        token_hash = connection.execute("SELECT token_hash FROM devices").fetchone()[0]
        connection.close()
        assert token not in token_hash
        assert "activation-secret" not in store.path.read_bytes().decode("utf-8", errors="ignore")
        store.close()

    asyncio.run(scenario())


def test_platform_uid_cannot_be_claimed_by_a_second_device(tmp_path):
    async def scenario():
        store = GatewayStore(tmp_path / "gateway.sqlite3")
        im = FakeIMClient()
        app = create_app(server_config(tmp_path), im_client=im, store=store)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post("/v1/activate", json=activation_payload())
            assert first.status_code == 200
            conflict = await client.post("/v1/activate", json=activation_payload())
            assert conflict.status_code == 409
            assert "another device" in conflict.json()["error"]
        store.close()

    asyncio.run(scenario())


def test_invalid_activation_code_is_not_reflected(tmp_path):
    async def scenario():
        store = GatewayStore(tmp_path / "gateway.sqlite3")
        app = create_app(server_config(tmp_path), im_client=FakeIMClient(), store=store)
        transport = httpx.ASGITransport(app=app)
        payload = activation_payload()
        payload["activation_code"] = "abc"
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/v1/activate", json=payload)
        assert response.status_code == 422
        assert "abc" not in response.text
        store.close()

    asyncio.run(scenario())


def test_im_failure_logs_rpc_and_returns_safe_grpc_code(tmp_path, caplog):
    class RejectingIM(FakeIMClient):
        async def ensure_audience(self, account):
            raise IMCallError("AudienceAddAccount", "INVALID_ARGUMENT", retryable=False)

    async def scenario():
        store = GatewayStore(tmp_path / "gateway.sqlite3")
        app = create_app(server_config(tmp_path), im_client=RejectingIM(), store=store)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            activated = await client.post("/v1/activate", json=activation_payload())
            token = activated.json()["device_token"]
            with caplog.at_level(logging.WARNING, logger="adapter_gateway.app"):
                response = await client.post(
                    "/v1/audiences/ensure",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "platform": "douyin",
                        "platform_actor_id": "actor-1001",
                        "platform_audience_id": "audience-2002",
                    },
                )

        assert response.status_code == 502
        assert response.json() == {
            "error": "im_rejected",
            "operation": "AudienceAddAccount",
            "grpc_code": "INVALID_ARGUMENT",
            "retryable": False,
        }
        assert "operation=AudienceAddAccount" in caplog.text
        assert "grpc_code=INVALID_ARGUMENT" in caplog.text
        assert token not in caplog.text
        store.close()

    asyncio.run(scenario())


def test_pc_control_client_persists_device_token_and_registers_audience(tmp_path):
    async def scenario():
        store = GatewayStore(tmp_path / "gateway.sqlite3")
        im = FakeIMClient()
        app = create_app(server_config(tmp_path), im_client=im, store=store)
        credentials = CredentialStore(tmp_path / "credentials.sqlite3")
        config = AdapterConfig(
            platform="douyin",
            rabbitmq_host="rabbit.test",
            rabbitmq_user="adapter",
            rabbitmq_password="secret",
            state_db=tmp_path / "douyin.sqlite3",
            credential_db=tmp_path / "credentials.sqlite3",
            control_gateway_url="http://localhost:8080",
        )
        transport = httpx.ASGITransport(app=app)
        gateway = ControlGatewayClient(config, credentials, transport=transport)

        result = await gateway.activate(
            "activation-secret",
            [{"platform": "douyin", "platform_actor_id": "actor-1001", "profile": {}}],
        )
        saved = credentials.get("control_gateway")
        assert saved["device_token"] == result["device_token"]
        assert saved["device_id"] == result["device_id"]
        assert saved["activation_code"] == "activation-secret"

        await gateway.ensure_audience(
            {
                "platform": "douyin",
                "platform_actor_id": "actor-1001",
                "platform_audience_id": "audience-2002",
                "nickname": "联系人",
                "avatar_url": "",
                "profile": {},
            }
        )
        assert len(im.audience_calls) == 1

        credentials.close()
        store.close()

    asyncio.run(scenario())


def test_pc_control_client_explains_gateway_errors_in_chinese(tmp_path):
    responses = [
        httpx.Response(
            502,
            json={
                "error": "im_rejected",
                "operation": "ActorAddAccount",
                "grpc_code": "FAILED_PRECONDITION",
                "retryable": False,
            },
        ),
        httpx.Response(
            409,
            json={"error": "rednote platform UID is already bound to another device"},
        ),
        httpx.Response(503, json={"error": "im_unavailable", "grpc_code": "UNAVAILABLE", "retryable": True}),
    ]

    async def handler(_request):
        return responses.pop(0)

    async def scenario():
        credentials = CredentialStore(tmp_path / "credentials.sqlite3")
        config = AdapterConfig(
            platform="rednote",
            rabbitmq_host="rabbit.test",
            rabbitmq_user="adapter",
            rabbitmq_password="secret",
            state_db=tmp_path / "rednote.sqlite3",
            credential_db=tmp_path / "credentials.sqlite3",
            control_gateway_url="http://localhost:8080",
        )
        gateway = ControlGatewayClient(config, credentials, transport=httpx.MockTransport(handler))
        accounts = [{"platform": "rednote", "platform_actor_id": "6a4717b5000000000e03dc02"}]

        with pytest.raises(ControlGatewayError) as rejected:
            await gateway.activate("activation-secret", accounts)
        assert rejected.value.retryable is False
        assert str(rejected.value) == "账号已在轻回绑定"
        assert len(str(rejected.value)) <= 15

        with pytest.raises(ControlGatewayError) as owned:
            await gateway.activate("activation-secret", accounts)
        assert str(owned.value) == "账号已绑在其他电脑"
        assert len(str(owned.value)) <= 15

        with pytest.raises(ControlGatewayError) as unavailable:
            await gateway.activate("activation-secret", accounts)
        assert unavailable.value.retryable is True
        assert str(unavailable.value) == "暂时连不上轻回"
        assert len(str(unavailable.value)) <= 15
        credentials.close()

    asyncio.run(scenario())


def test_pc_control_client_honors_non_retryable_gateway_error(tmp_path):
    async def handler(_request):
        return httpx.Response(
            502,
            json={"error": "activation rejected", "retryable": False},
        )

    async def scenario():
        credentials = CredentialStore(tmp_path / "credentials.sqlite3")
        config = AdapterConfig(
            platform="douyin",
            rabbitmq_host="rabbit.test",
            rabbitmq_user="adapter",
            rabbitmq_password="secret",
            state_db=tmp_path / "douyin.sqlite3",
            credential_db=tmp_path / "credentials.sqlite3",
            control_gateway_url="http://localhost:8080",
        )
        gateway = ControlGatewayClient(
            config,
            credentials,
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(ControlGatewayError) as captured:
            await gateway.activate(
                "activation-secret",
                [{"platform": "douyin", "platform_actor_id": "actor-1001"}],
            )

        assert captured.value.retryable is False
        credentials.close()

    asyncio.run(scenario())


def test_grpc_client_uses_confirmed_actor_and_audience_field_mapping(tmp_path, caplog):
    class Stub:
        def __init__(self):
            self.actor_add = None
            self.audience_get = None
            self.audience_add = None
            self.metadata = []

        async def ActorGetAccount(self, request, **kwargs):
            self.metadata.append(kwargs["metadata"])
            return im_pb2.ActorAccountResp()

        async def ActorAddAccount(self, request, **kwargs):
            self.actor_add = request
            self.metadata.append(kwargs["metadata"])
            return im_pb2.ActorAccountResp(
                actor=im_pb2.Actor(actor_id=request.actor_id),
                account=im_pb2.ActorPlatformAccount(
                    actor_id=request.actor_id,
                    platform=request.platform,
                ),
            )

        async def AudienceGetAccount(self, request, **kwargs):
            self.audience_get = request
            self.metadata.append(kwargs["metadata"])
            return im_pb2.AudienceAccountResp()

        async def AudienceAddAccount(self, request, **kwargs):
            self.audience_add = request
            self.metadata.append(kwargs["metadata"])
            return im_pb2.AudienceAddAccountResp(is_new_session=True)

    async def scenario():
        client = IMGrpcClient(server_config(tmp_path))
        stub = Stub()
        client._stub = stub
        try:
            with caplog.at_level(logging.INFO, logger="adapter_gateway.grpc_client"):
                await client.ensure_actor(
                    {
                        "platform": "douyin",
                        "platform_actor_id": "actor-1001",
                        "nickname": "平台昵称",
                        "avatar_url": "avatar",
                        "profile": {"region": "cn"},
                    },
                    "activation-secret",
                )
                await client.ensure_audience(
                    {
                        "platform": "douyin",
                        "platform_actor_id": "actor-1001",
                        "platform_audience_id": "audience-2002",
                        "nickname": "联系人",
                        "avatar_url": "audience-avatar",
                        "profile": {"source": "chat"},
                    }
                )
        finally:
            await client.close()

        assert stub.actor_add.actor_id == "actor-1001"
        assert stub.actor_add.shop_name == ""
        assert stub.actor_add.business_domain == "default"
        assert stub.actor_add.activation_code == "activation-secret"
        assert stub.actor_add.openim_id == ""
        assert stub.actor_add.status == "enable"
        assert stub.actor_add.profile == '{"region":"cn"}'
        assert stub.audience_get.platform == "douyin"
        assert stub.audience_get.actor_platform_id == "actor-1001"
        assert stub.audience_get.audience_platform_id == "audience-2002"
        assert stub.audience_add.actor_platform_id == "actor-1001"
        assert stub.audience_add.audience_platform_id == "audience-2002"
        assert stub.audience_add.status == "enable"
        assert stub.audience_add.profile == '{"source":"chat"}'
        assert all(metadata[0][0] == "operationid" for metadata in stub.metadata)
        assert "operation=AudienceGetAccount" in caplog.text
        assert (
            'payload={"platform":"douyin","audiencePlatformID":"audience-2002",'
            '"actorPlatformID":"actor-1001"}' in caplog.text
        )
        assert "operation=AudienceAddAccount" in caplog.text
        assert '"actorPlatformID":"actor-1001"' in caplog.text
        assert '"nickname":"联系人"' in caplog.text
        assert '"activationCode":"<redacted>"' in caplog.text
        assert "activation-secret" not in caplog.text

    asyncio.run(scenario())


def test_audience_lookup_invalid_argument_falls_through_to_create(tmp_path, caplog):
    class Stub:
        def __init__(self):
            self.audience_add = None

        async def AudienceGetAccount(self, request, **kwargs):
            raise AssertionError("_call is replaced for this compatibility test")

        async def AudienceAddAccount(self, request, **kwargs):
            raise AssertionError("_call is replaced for this compatibility test")

    async def scenario():
        client = IMGrpcClient(server_config(tmp_path))
        stub = Stub()
        client._stub = stub

        async def call(operation, method, request, **kwargs):
            if operation == "AudienceGetAccount":
                raise IMCallError(operation, "INVALID_ARGUMENT", retryable=False)
            assert operation == "AudienceAddAccount"
            stub.audience_add = request
            return im_pb2.AudienceAddAccountResp(is_new_session=True)

        client._call = call
        with caplog.at_level(logging.WARNING, logger="adapter_gateway.grpc_client"):
            result = await client.ensure_audience(
                {
                    "platform": "douyin",
                    "platform_actor_id": "actor-1001",
                    "platform_audience_id": "audience-2002",
                    "nickname": "联系人",
                    "avatar_url": "",
                    "profile": {},
                }
            )

        assert result["created"] is True
        assert stub.audience_add.actor_platform_id == "actor-1001"
        assert stub.audience_add.audience_platform_id == "audience-2002"
        assert "trying create" in caplog.text
        await client.close()

    asyncio.run(scenario())


def test_real_grpc_channel_is_created_inside_server_event_loop(tmp_path):
    class Servicer(im_pb2_grpc.csServicer):
        def __init__(self):
            self.metadata = ()

        async def ActorGetAccount(self, request, context):
            self.metadata = context.invocation_metadata()
            return im_pb2.ActorAccountResp(
                actor=im_pb2.Actor(actor_id=request.actor_platform_id),
                account=im_pb2.ActorPlatformAccount(
                    actor_id=request.actor_platform_id,
                    platform=request.platform,
                ),
            )

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = GatewayServerConfig(
        database=tmp_path / "gateway.sqlite3",
        im_grpc_target=f"127.0.0.1:{port}",
        im_grpc_timeout_seconds=1,
    )
    # Constructed before asyncio.run, matching adapter-gateway CLI startup.
    client = IMGrpcClient(config)

    async def scenario():
        server = grpc.aio.server()
        servicer = Servicer()
        im_pb2_grpc.add_csServicer_to_server(servicer, server)
        server.add_insecure_port(config.im_grpc_target)
        await server.start()
        try:
            assert await client.ready(1)
            result = await client.ensure_actor(
                {"platform": "douyin", "platform_actor_id": "actor-1001"},
                "activation-secret",
            )
            assert result["actor"]["actorID"] == "actor-1001"
            assert any(item.key == "operationid" for item in servicer.metadata)
        finally:
            await client.close()
            await server.stop(0)

    asyncio.run(scenario())
