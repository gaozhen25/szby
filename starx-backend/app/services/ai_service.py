import os
import logging
import base64
import binascii
import mimetypes
import asyncio
import json
from time import perf_counter
from urllib.parse import urlparse
from contextvars import ContextVar
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.services.prompt_builder import build_domain_image_followup_prompt, build_report_section_prompt

DEFAULT_LLM_MODEL = settings.DEFAULT_LLM_MODEL or "qwen-plus"
DEFAULT_IMAGE_DISCERN_MODEL = settings.DEFAULT_IMAGE_DISCERN_MODEL or "qwen3-vl-plus"
DEFALUT_IMAGE_GENERATE_MODEL = settings.DEFAULT_IMAGE_GENERATE_MODEL or "gpt-image-2"
DEFAULT_VIDEO_DISCERN_MODEL = settings.DEFAULT_VIDEO_DISCERN_MODEL or "qwen3-vl-plus"
DEFAULT_VOICE_GENERATE_MODEL = settings.DEFAULT_VOICE_GENERATE_MODEL or "speech-02-hd"
DEFAULT_VOICE_DISCERN_MODEL = settings.DEFAULT_VOICE_DISCERN_MODEL or "qwen3-asr-flash"
DEFAULT_VOICE_FILETRANS_MODEL = (
    settings.DEFAULT_VOICE_FILETRANS_MODEL or "qwen3-asr-flash-filetrans"
)

DEFAULT_BASE_URL = getattr(settings, "DEFAULT_BASE_URL", None) 
DEFAULT_TOKEN = getattr(settings, "DEFAULT_TOKEN", None)
DEFAULT_TIMEOUT = float(getattr(settings, "DEFAULT_TIMEOUT", None) or 360)
DEFAULT_IMAGE_GENERATION_TIMEOUT = float(getattr(settings, "DEFAULT_IMAGE_GENERATION_TIMEOUT", None) or 360)
DEFAULT_REMOTE_EMBEDDING_MODEL = getattr(settings, "DEFAULT_REMOTE_EMBEDDING_MODEL", None) 
DEFAULT_OLLAMA_BASE_URL = getattr(settings, "DEFAULT_OLLAMA_BASE_URL", None) 
DEFAULT_LOCAL_EMBEDDING_MODEL = getattr(settings, "DEFAULT_LOCAL_EMBEDDING_MODEL", None) or "qwen3-embedding:8b"

logger = logging.getLogger(__name__)
_TOKEN_USAGE_TRACKER: ContextVar[dict[str, Any] | None] = ContextVar("ai_service_token_usage_tracker", default=None)
_REQUEST_TRACE_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar("ai_service_request_trace_context", default=None)
AI_SERVICE_FORBIDDEN_SENTINEL = "__AI_SERVICE_FORBIDDEN_430__"
IMAGE_EDIT_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp"}
IMAGE_EDIT_DOWNLOAD_RETRY_DELAYS = (0.2, 0.5)
IMAGE_EDIT_REQUEST_RETRY_DELAYS = (0.75, 1.5)


def _normalize_authorization(token: Optional[str], fallback_token: Optional[str]) -> str:
    resolved = (token or fallback_token or "").strip()
    if not resolved:
        return ""
    if resolved.lower().startswith("bearer "):
        return resolved
    return f"Bearer {resolved}"


def _resolve_base_url(base_url: Optional[str], fallback_base_url: str) -> str:
    resolved = (base_url or fallback_base_url or "").strip().rstrip("/")
    return resolved


def _openai_compatible_endpoint(base_url: str, endpoint: str) -> str:
    """兼容传入服务根地址或已经包含 /v1 的 OpenAI base_url。"""
    resolved = str(base_url or "").strip().rstrip("/")
    normalized_endpoint = str(endpoint or "").strip().strip("/")
    if resolved.endswith(f"/{normalized_endpoint}"):
        return resolved
    if resolved.endswith("/v1"):
        return f"{resolved}/{normalized_endpoint}"
    return f"{resolved}/v1/{normalized_endpoint}"


def _dashscope_endpoint(base_url: str, endpoint: str) -> str:
    """使用同一中转站根地址拼装 DashScope 兼容端点。"""
    resolved = str(base_url or "").strip().rstrip("/")
    for suffix in ("/compatible-mode/v1", "/api/v1", "/v1"):
        if resolved.endswith(suffix):
            resolved = resolved.removesuffix(suffix)
            break
    return f"{resolved}/api/v1/{str(endpoint or '').strip().strip('/')}"


def _safe_int_value(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip() or "0")
        except Exception:
            return 0
    return 0


def _safe_dict_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}
    return {}


def _extract_asr_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first, dict) else None
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                parts = [
                    str(item.get("text") or item.get("content") or "").strip()
                    for item in content
                    if isinstance(item, dict)
                ]
                return "\n".join(part for part in parts if part).strip()
    return str(payload.get("text") or payload.get("transcript") or "").strip()


def _find_nested_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        if key in value and value[key] not in (None, ""):
            return value[key]
        for child in value.values():
            found = _find_nested_value(child, key)
            if found not in (None, ""):
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_nested_value(child, key)
            if found not in (None, ""):
                return found
    return None


def _contains_filetrans_result(value: Any) -> bool:
    return isinstance(_find_nested_value(value, "transcripts"), list)


def _ensure_https_image_generation_url(value: Any) -> str:
    url = str(value or "").strip()
    if url.startswith("http://"):
        return f"https://{url.removeprefix('http://')}"
    return url


def _normalize_image_generation_references(value: str | list[Any]) -> list[dict[str, Any]]:
    raw_items = value if isinstance(value, list) else [value]
    references: list[dict[str, Any]] = []
    for item in raw_items:
        if isinstance(item, dict):
            image_url = item.get("image_url")
            if item.get("type") == "image_url" and isinstance(image_url, dict) and image_url.get("url"):
                references.append(
                    {"type": "image_url", "image_url": {"url": _ensure_https_image_generation_url(image_url["url"])}}
                )
            elif item.get("url"):
                references.append(
                    {"type": "image_url", "image_url": {"url": _ensure_https_image_generation_url(item["url"])}}
                )
            continue
        url = _ensure_https_image_generation_url(item)
        if url:
            references.append({"type": "image_url", "image_url": {"url": url}})
    return references


def _multipart_form_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _image_content_type(value: Any, url: str) -> str:
    content_type = str(value or "").split(";", 1)[0].strip().lower()
    if content_type:
        return content_type
    guessed, _ = mimetypes.guess_type(urlparse(url).path)
    return str(guessed or "").lower() if guessed in IMAGE_EDIT_CONTENT_TYPES else "image/png"


def _image_file_name(url: str, index: int, content_type: str) -> str:
    name = os.path.basename(urlparse(url).path).strip()
    if name:
        return name
    extension = {"image/jpeg": ".jpg", "image/webp": ".webp"}.get(content_type, ".png")
    return f"image-{index}{extension}"


def _trim_text(value: Any, limit: int = 300) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...(truncated)"


def _token_fingerprint(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered.startswith("bearer "):
        text = text[7:].strip()
    if not text:
        return ""
    tail = text[-4:] if len(text) >= 4 else text
    return f"len={len(text)} tail={tail}"


def _current_task_name() -> str:
    task = asyncio.current_task()
    if task is None:
        return ""
    return task.get_name()


def _exception_message(exc: BaseException) -> str:
    original = getattr(exc, "orig", None)
    if original is not None:
        original_message = str(original).strip()
        if original_message:
            return original_message
    message = str(exc).strip()
    return message or exc.__class__.__name__


def _extract_json_object(raw_text: Any) -> dict[str, Any]:
    text = str(raw_text or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


def _decode_data_url_bytes(data_url: str) -> tuple[bytes, str]:
    text = str(data_url or "").strip()
    if not text.startswith("data:") or "," not in text:
        return b"", "application/octet-stream"
    header, encoded = text.split(",", 1)
    mime_type = "application/octet-stream"
    if ";" in header:
        mime_type = header[5:].split(";", 1)[0].strip() or mime_type
    try:
        return base64.b64decode(encoded), mime_type
    except Exception:
        return b"", mime_type


def _normalize_domain_name(domain_name: str) -> str:
    text = str(domain_name or "").strip().lower()
    if any(keyword in text for keyword in ["减肥", "瘦身", "体重", "weight", "nutrition", "diet"]):
        return "weight_loss"
    return text or "general"


def _stringify_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value or "")


class AIService:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        llm_model: str = DEFAULT_LLM_MODEL,
        image_discern_model: str = DEFAULT_IMAGE_DISCERN_MODEL,
        video_discern_model: str = DEFAULT_VIDEO_DISCERN_MODEL,
        voice_generate_model: str = DEFAULT_VOICE_GENERATE_MODEL,
        voice_discern_model: str = DEFAULT_VOICE_DISCERN_MODEL,
        voice_filetrans_model: str = DEFAULT_VOICE_FILETRANS_MODEL,
        image_generate_model: str = DEFALUT_IMAGE_GENERATE_MODEL,
        embedding_model: str = DEFAULT_REMOTE_EMBEDDING_MODEL,
        token: Optional[str] = DEFAULT_TOKEN,
        timeout_seconds: float = DEFAULT_TIMEOUT,
        image_generation_timeout_seconds: float = DEFAULT_IMAGE_GENERATION_TIMEOUT,
        video_analysis_timeout_seconds: float | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.llm_model = llm_model
        self.image_discern_model = image_discern_model
        self.video_discern_model = video_discern_model
        self.voice_generate_model = voice_generate_model
        self.voice_discern_model = voice_discern_model
        self.voice_filetrans_model = voice_filetrans_model
        self.image_generate_model = image_generate_model
        self.embedding_model = embedding_model
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.image_generation_timeout_seconds = image_generation_timeout_seconds
        self.video_analysis_timeout_seconds = (
            float(video_analysis_timeout_seconds)
            if video_analysis_timeout_seconds is not None
            else float(settings.video_analysis_ai_timeout_seconds)
        )

    def reset_token_usage_tracker(self) -> None:
        _TOKEN_USAGE_TRACKER.set(
            {
                "total_calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "by_api": {},
                "by_model": {},
            }
        )

    def set_request_trace_context(self, context: dict[str, Any]) -> None:
        _REQUEST_TRACE_CONTEXT.set(dict(context or {}))

    def clear_request_trace_context(self) -> None:
        _REQUEST_TRACE_CONTEXT.set(None)

    def get_request_trace_context(self) -> dict[str, Any]:
        current = _REQUEST_TRACE_CONTEXT.get()
        if isinstance(current, dict):
            return dict(current)
        return {}

    def get_token_usage_snapshot(self) -> dict[str, Any]:
        current = _TOKEN_USAGE_TRACKER.get()
        if isinstance(current, dict):
            return {
                "total_calls": int(current.get("total_calls", 0) or 0),
                "prompt_tokens": int(current.get("prompt_tokens", 0) or 0),
                "completion_tokens": int(current.get("completion_tokens", 0) or 0),
                "total_tokens": int(current.get("total_tokens", 0) or 0),
                "by_api": dict(current.get("by_api") or {}),
                "by_model": dict(current.get("by_model") or {}),
            }
        return {
            "total_calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "by_api": {},
            "by_model": {},
        }

    def _record_token_usage(self, *, api_name: str, model: str, payload: dict[str, Any]) -> None:
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            return
        tracker = _TOKEN_USAGE_TRACKER.get()
        if not isinstance(tracker, dict):
            tracker = {
                "total_calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "by_api": {},
                "by_model": {},
            }
        prompt_tokens = _safe_int_value(usage.get("prompt_tokens", 0))
        completion_tokens = _safe_int_value(usage.get("completion_tokens", 0))
        total_tokens = _safe_int_value(usage.get("total_tokens", prompt_tokens + completion_tokens))
        tracker["total_calls"] = _safe_int_value(tracker.get("total_calls", 0)) + 1
        tracker["prompt_tokens"] = _safe_int_value(tracker.get("prompt_tokens", 0)) + prompt_tokens
        tracker["completion_tokens"] = _safe_int_value(tracker.get("completion_tokens", 0)) + completion_tokens
        tracker["total_tokens"] = _safe_int_value(tracker.get("total_tokens", 0)) + total_tokens

        by_api = _safe_dict_value(tracker.get("by_api"))
        api_item = _safe_dict_value(by_api.get(api_name))
        api_item["calls"] = _safe_int_value(api_item.get("calls", 0)) + 1
        api_item["prompt_tokens"] = _safe_int_value(api_item.get("prompt_tokens", 0)) + prompt_tokens
        api_item["completion_tokens"] = _safe_int_value(api_item.get("completion_tokens", 0)) + completion_tokens
        api_item["total_tokens"] = _safe_int_value(api_item.get("total_tokens", 0)) + total_tokens
        by_api[api_name] = api_item
        tracker["by_api"] = by_api

        by_model = _safe_dict_value(tracker.get("by_model"))
        model_item = _safe_dict_value(by_model.get(model))
        model_item["calls"] = _safe_int_value(model_item.get("calls", 0)) + 1
        model_item["prompt_tokens"] = _safe_int_value(model_item.get("prompt_tokens", 0)) + prompt_tokens
        model_item["completion_tokens"] = _safe_int_value(model_item.get("completion_tokens", 0)) + completion_tokens
        model_item["total_tokens"] = _safe_int_value(model_item.get("total_tokens", 0)) + total_tokens
        by_model[model] = model_item
        tracker["by_model"] = by_model
        _TOKEN_USAGE_TRACKER.set(tracker)

    def _resolve_llm_model(self, model: Optional[str]) -> str:
        selected_model = str(model).strip() if model is not None else ""
        if selected_model.lower() in {"", "none", "null"}:
            return self.llm_model
        return selected_model

    def _resolve_image_discern_model(self, model: Optional[str]) -> str:
        selected_model = str(model).strip() if model is not None else ""
        if selected_model.lower() in {"", "none", "null"}:
            return self.image_discern_model
        return selected_model
    
    def _resolve_video_discern_model(self, model: Optional[str]) -> str:
        selected_model = str(model).strip() if model is not None else ""
        if selected_model.lower() in {"", "none", "null"}:
            return self.video_discern_model
        return selected_model

    def _resolve_image_generate_model(self, model: Optional[str]) -> str:
        selected_model = str(model).strip() if model is not None else ""
        if selected_model.lower() in {"", "none", "null"}:
            return self.image_generate_model
        return selected_model

    def _resolve_voice_model(self, model: Optional[str]) -> str:
        selected_model = str(model).strip() if model is not None else ""
        if selected_model.lower() in {"", "none", "null"}:
            return self.voice_generate_model
        return selected_model

    def _resolve_voice_discern_model(self, model: Optional[str]) -> str:
        selected_model = str(model).strip() if model is not None else ""
        if selected_model.lower() in {"", "none", "null"}:
            return self.voice_discern_model
        return selected_model

    def _resolve_voice_filetrans_model(self, model: Optional[str]) -> str:
        selected_model = str(model).strip() if model is not None else ""
        if selected_model.lower() in {"", "none", "null"}:
            return self.voice_filetrans_model
        return selected_model

    def _resolve_embedding_model(self, model: Optional[str]) -> str:
        selected_model = str(model).strip() if model is not None else ""
        if selected_model.lower() in {"", "none", "null"}:
            return self.embedding_model
        return selected_model

    async def analyze_report_section(self, *, section_key: str, account_context: dict[str, object]) -> str:
        prompt = build_report_section_prompt(section_key=section_key, account_context=account_context)
        result = await self.chat_completion(messages=[{"role": "user", "content": prompt}], temperature=0.4)
        return str(result or "").strip() or "AI 分析暂时不可用，请稍后重试。"

    def _headers(self, token: Optional[str] = None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        authorization = _normalize_authorization(token, self.token)
        if authorization:
            headers["Authorization"] = authorization
        return headers

    def get_models(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
    ) -> list[str]:
        resolved_base_url = _resolve_base_url(base_url, self.base_url)
        url = f"{resolved_base_url}/v1/models"
        response = httpx.get(url, headers=self._headers(token), timeout=self.timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        return [item.get("id") for item in payload.get("data", []) if item.get("id")]

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        stream: bool = False,
        model: Optional[str] = None,    
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        extra_body: Optional[dict[str, Any]] = None,
    ) -> Optional[str]:
        resolved_base_url = _resolve_base_url(base_url, self.base_url)
        url = f"{resolved_base_url}/v1/chat/completions"
        final_messages = list(messages)
        if system_prompt:
            final_messages.insert(0, {"role": "system", "content": system_prompt})
        selected_model = self._resolve_llm_model(model)
        body = {
            "model": selected_model,
            "messages": final_messages,
            "temperature": temperature,
            "stream": stream,
        }
        if extra_body:
            body.update(extra_body)

        headers = self._headers(token)
        started_at = perf_counter()
        response: httpx.Response | None = None
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(url, headers=headers, json=body)
                _ = response.raise_for_status()
                payload = response.json()
            self._record_token_usage(api_name="chat_completion", model=selected_model, payload=payload)
            raw_payload = _stringify_json(payload)
            logger.info(
                "chat_completion response base_url=%s model=%s trace=%s status=%s duration_ms=%s "
                "timeout_seconds=%s response_length=%s payload=%s",
                resolved_base_url,
                body.get("model"),
                self.get_request_trace_context(),
                response.status_code,
                max(int((perf_counter() - started_at) * 1000), 0),
                self.timeout_seconds,
                len(raw_payload),
                raw_payload,
            )
            return payload.get("choices", [{}])[0].get("message", {}).get("content", "")
        except asyncio.CancelledError:
            logger.warning(
                "chat_completion cancelled url=%s model=%s trace=%s message_count=%s first_message=%s task=%s",
                url,
                selected_model,
                self.get_request_trace_context(),
                len(final_messages),
                _trim_text(final_messages[0] if final_messages else ""),
                _current_task_name(),
            )
            raise
        except httpx.HTTPStatusError as exc:
            response = exc.response
            logger.warning(
                "chat_completion http_status_error url=%s status=%s base_url=%s model=%s trace=%s "
                "error_type=%s error=%s timeout_seconds=%s duration_ms=%s response_received=true raw_response=%s",
                url,
                getattr(response, "status_code", ""),
                resolved_base_url,
                body.get("model"),
                self.get_request_trace_context(),
                exc.__class__.__name__,
                _exception_message(exc),
                self.timeout_seconds,
                max(int((perf_counter() - started_at) * 1000), 0),
                getattr(response, "text", ""),
            )
            if int(getattr(response, "status_code", 0) or 0) == 430:
                return AI_SERVICE_FORBIDDEN_SENTINEL
            return None
        except Exception as exc:
            response_received = response is not None
            logger.warning(
                "chat_completion failed base_url=%s model=%s trace=%s error_type=%s error=%s "
                "timeout_seconds=%s duration_ms=%s response_received=%s response_status=%s raw_response=%s",
                resolved_base_url,
                body.get("model"),
                self.get_request_trace_context(),
                exc.__class__.__name__,
                _exception_message(exc),
                self.timeout_seconds,
                max(int((perf_counter() - started_at) * 1000), 0),
                "true" if response_received else "false",
                getattr(response, "status_code", "") if response_received else "",
                getattr(response, "text", "") if response_received else "",
            )
            return None

    async def image_generation(
        self,
        prompt: str,
        model: Optional[str] = None,
        input_reference: Optional[str | list[Any]] = None,
        aspect_ratio: Optional[str] = None,
        size: str = "1024x1024",
        n: int = 1,
        output_format: Optional[str] = None,
        quality: Optional[str] = None,
        style: Optional[str] = None,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        extra_body: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        resolved_base_url = _resolve_base_url(base_url, self.base_url)
        url = f"{resolved_base_url}/v1/images/generations"
        selected_model = self._resolve_image_generate_model(model)
        body: dict[str, Any] = {
            "model": selected_model,
            "prompt": prompt,
        }
        if input_reference:
            body["input_reference"] = _normalize_image_generation_references(input_reference)
        if aspect_ratio:
            body["aspect_ratio"] = aspect_ratio
        if size:
            body["size"] = size
        if output_format:
            body["response_format"] = output_format
        if quality:
            body["quality"] = quality
        if style:
            body["style"] = style
        if extra_body:
            body.update(extra_body)
        headers = self._headers(token)
        try:
            async with httpx.AsyncClient(timeout=self.image_generation_timeout_seconds) as client:
                response = await client.post(url, headers=headers, json=body)
                response.raise_for_status()
                payload = response.json()
        except asyncio.CancelledError:
            logger.warning(
                "image_generation cancelled url=%s model=%s trace=%s prompt=%s task=%s",
                url,
                selected_model,
                self.get_request_trace_context(),
                _trim_text(prompt, 200),
                _current_task_name(),
            )
            raise
        except httpx.HTTPStatusError as exc:
            response = exc.response
            logger.warning(
                "image_generation http_status_error url=%s status=%s base_url=%s model=%s trace=%s auth=%s token=%s response=%s",
                url,
                getattr(response, "status_code", ""),
                resolved_base_url,
                selected_model,
                self.get_request_trace_context(),
                "Authorization" in (headers if isinstance(headers, dict) else {}),
                _token_fingerprint(token if token is not None else self.token),
                _trim_text(getattr(response, "text", ""), 800),
            )
            raise
        except Exception as exc:
            logger.warning(
                "image_generation failed base_url=%s model=%s trace=%s error=%s",
                resolved_base_url,
                selected_model,
                self.get_request_trace_context(),
                _exception_message(exc),
            )
            raise
        self._record_token_usage(api_name="image_generation", model=selected_model, payload=payload)
        return payload.get("data", [])

    async def image_edit(
        self,
        prompt: str,
        input_reference: str | list[Any],
        model: Optional[str] = None,
        size: str = "1024x1024",
        n: int = 1,
        output_format: Optional[str] = None,
        quality: Optional[str] = None,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        extra_body: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        resolved_base_url = _resolve_base_url(base_url, self.base_url)
        url = f"{resolved_base_url}/v1/images/edits"
        selected_model = self._resolve_image_generate_model(model)
        references = _normalize_image_generation_references(input_reference)
        if not references:
            raise ValueError("image_edit requires at least one input reference")

        reference_urls = [
            str((reference.get("image_url") or {}).get("url") or "").strip()
            for reference in references
            if isinstance(reference, dict)
        ]
        reference_urls = [url for url in reference_urls if url]
        if not reference_urls:
            raise ValueError("image_edit requires at least one input reference url")

        form_data: dict[str, str] = {
            "model": selected_model,
            "prompt": prompt,
            "n": str(n),
        }
        if size:
            form_data["size"] = size
        if output_format:
            form_data["response_format"] = output_format
        if quality:
            form_data["quality"] = quality
        if extra_body:
            form_data.update({key: _multipart_form_value(value) for key, value in extra_body.items()})

        headers = self._headers(token)
        headers.pop("Content-Type", None)
        try:
            async with httpx.AsyncClient(timeout=self.image_generation_timeout_seconds) as client:
                files = []
                for index, reference_url in enumerate(reference_urls, start=1):
                    file_name, content, content_type = await self._download_image_edit_reference(
                        client,
                        reference_url,
                        index,
                    )
                    files.append(("image", (file_name, content, content_type)))
                response: httpx.Response | None = None
                for attempt in range(len(IMAGE_EDIT_REQUEST_RETRY_DELAYS) + 1):
                    try:
                        response = await client.post(url, headers=headers, data=form_data, files=files)
                        break
                    except httpx.TransportError as exc:
                        if attempt >= len(IMAGE_EDIT_REQUEST_RETRY_DELAYS):
                            raise
                        delay = IMAGE_EDIT_REQUEST_RETRY_DELAYS[attempt]
                        logger.warning(
                            "image_edit transport retry base_url=%s model=%s attempt=%s delay_seconds=%s error=%s",
                            resolved_base_url,
                            selected_model,
                            attempt + 1,
                            delay,
                            _exception_message(exc),
                        )
                        await asyncio.sleep(delay)
                if response is None:
                    raise RuntimeError("image_edit request returned no response")
                response.raise_for_status()
                payload = response.json()
        except asyncio.CancelledError:
            logger.warning(
                "image_edit cancelled url=%s model=%s trace=%s prompt=%s task=%s",
                url,
                selected_model,
                self.get_request_trace_context(),
                _trim_text(prompt, 200),
                _current_task_name(),
            )
            raise
        except httpx.HTTPStatusError as exc:
            response = exc.response
            logger.warning(
                "image_edit http_status_error url=%s status=%s base_url=%s model=%s trace=%s auth=%s token=%s response=%s",
                url,
                getattr(response, "status_code", ""),
                resolved_base_url,
                selected_model,
                self.get_request_trace_context(),
                "Authorization" in (headers if isinstance(headers, dict) else {}),
                _token_fingerprint(token if token is not None else self.token),
                _trim_text(getattr(response, "text", ""), 800),
            )
            raise
        except Exception as exc:
            logger.warning(
                "image_edit failed base_url=%s model=%s trace=%s error=%s",
                resolved_base_url,
                selected_model,
                self.get_request_trace_context(),
                _exception_message(exc),
            )
            raise
        self._record_token_usage(api_name="image_edit", model=selected_model, payload=payload)
        return payload.get("data", [])

    async def _download_image_edit_reference(
        self,
        client: httpx.AsyncClient,
        url: str,
        index: int,
    ) -> tuple[str, bytes, str]:
        if url.startswith("data:image/"):
            header, separator, encoded = url.partition(",")
            if not separator or ";base64" not in header:
                raise ValueError("image_edit data URL must be base64 encoded")
            content_type = _image_content_type(header.removeprefix("data:").split(";", 1)[0], url)
            try:
                content = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ValueError("image_edit received invalid base64 image data") from exc
            self._validate_image_edit_download(content, content_type)
            return _image_file_name("", index, content_type), content, content_type

        response: httpx.Response | None = None
        for attempt in range(len(IMAGE_EDIT_DOWNLOAD_RETRY_DELAYS) + 1):
            try:
                response = await client.get(url)
                response.raise_for_status()
                break
            except httpx.TransportError:
                if attempt >= len(IMAGE_EDIT_DOWNLOAD_RETRY_DELAYS):
                    raise
                await asyncio.sleep(IMAGE_EDIT_DOWNLOAD_RETRY_DELAYS[attempt])
        if response is None:
            raise RuntimeError("image_edit reference download returned no response")

        content_type = _image_content_type(response.headers.get("Content-Type"), url)
        content = response.content
        self._validate_image_edit_download(content, content_type)
        return _image_file_name(url, index, content_type), content, content_type

    @staticmethod
    def _validate_image_edit_download(content: bytes, content_type: str) -> None:
        if content_type not in IMAGE_EDIT_CONTENT_TYPES:
            raise ValueError(f"image_edit received unsupported content type: {content_type}")
        if not content:
            raise ValueError("image_edit received an empty reference image")
        if len(content) > settings.max_upload_image_bytes:
            raise ValueError("image_edit reference image exceeds upload size limit")

    async def image_view(
        self,
        prompt: str,
        image_url: str,
        model: Optional[str] = None,
        temperature: float = 0.2,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
    ) -> Optional[str]:
        resolved_base_url = _resolve_base_url(base_url, self.base_url)
        url = f"{resolved_base_url}/v1/chat/completions"
        selected_model = self._resolve_image_discern_model(model)
        image_source = str(image_url or "").strip()
        if not image_source:
            return None
        if image_source.startswith(("http://", "https://", "data:")):
            final_image_url = image_source
        else:
            if not os.path.exists(image_source):
                logger.warning("image_view failed image not found path=%s", image_source)
                return None
            mime_type = mimetypes.guess_type(image_source)[0] or "image/jpeg"
            with open(image_source, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("utf-8")
            final_image_url = f"data:{mime_type};base64,{encoded}"
        body = {
            "model": selected_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": str(prompt or "").strip() or "请描述这张图片"},
                        {"type": "image_url", "image_url": {"url": final_image_url}},
                    ],
                }
            ],
            "temperature": temperature,
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(url, headers=self._headers(token), json=body)
                response.raise_for_status()
                payload = response.json()
            self._record_token_usage(api_name="image_view", model=selected_model, payload=payload)
            return payload.get("choices", [{}])[0].get("message", {}).get("content", "")
        except asyncio.CancelledError:
            logger.warning(
                "image_view cancelled url=%s model=%s trace=%s image=%s task=%s",
                url,
                selected_model,
                self.get_request_trace_context(),
                _trim_text(image_source, 200),
                _current_task_name(),
            )
            raise
        except Exception as exc:
            logger.warning(
                "image_view failed base_url=%s model=%s trace=%s error=%s",
                resolved_base_url,
                selected_model,
                self.get_request_trace_context(),
                _exception_message(exc),
            )
            raise

    async def video_view(
        self,
        user_prompt: str,
        system_prompt: str,
        video_url: str,
        model: Optional[str] = None,
        temperature: float = 0.2,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
    ):
        import time as _time

        resolved_base_url = _resolve_base_url(base_url, self.base_url)
        url = f"{resolved_base_url}/v1/chat/completions"
        selected_model = self._resolve_video_discern_model(model)
        video_source = str(video_url or "").strip()

        if not video_source:
            logger.warning("video_view failed video_url is empty")
            return None

        body = {
            "model": selected_model,
            "messages": [
                {
                    "role": "system",
                    "content": [
                        {"type": "text", "text": str(system_prompt or "").strip() or "你是一个视频解析助手。请根据用户提供的视频链接，分析视频内容并返回详细描述。"}
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": str(user_prompt or "").strip() or "请描述这张图片"},
                        {"type": "video_url", "video_url": {"url": video_source}},
                    ],
                },
            ],
            "temperature": temperature,
            "stream": False,
        }

        request_started_at = _time.monotonic()
        logger.info(
            "video_view request started base_url=%s model=%s video=%s",
            resolved_base_url,
            selected_model,
            _trim_text(video_source, 200),
        )
        try:
            timeout = httpx.Timeout(
                connect=min(self.video_analysis_timeout_seconds, 30),
                read=self.video_analysis_timeout_seconds,
                write=min(self.video_analysis_timeout_seconds, 60),
                pool=min(self.video_analysis_timeout_seconds, 30),
            )
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, headers=self._headers(token), json=body)
                response.raise_for_status()
                payload = response.json()
            elapsed_ms = int((_time.monotonic() - request_started_at) * 1000)
            self._record_token_usage(api_name="video_view", model=selected_model, payload=payload)
            choice = payload.get("choices", [{}])[0]
            content_text = choice.get("message", {}).get("content", "")
            finish_reason = choice.get("finish_reason") or "unknown"
            usage = payload.get("usage") or {}
            logger.info(
                "video_view request completed model=%s video=%s duration_ms=%s response_length=%s "
                "finish_reason=%s completion_tokens=%s total_tokens=%s",
                selected_model,
                _trim_text(video_source, 200),
                elapsed_ms,
                len(content_text or ""),
                finish_reason,
                usage.get("completion_tokens", ""),
                usage.get("total_tokens", ""),
            )
            return content_text
        except asyncio.CancelledError:
            elapsed_ms = int((_time.monotonic() - request_started_at) * 1000)
            logger.warning(
                "video_view cancelled url=%s model=%s trace=%s video=%s duration_ms=%s task=%s",
                url,
                selected_model,
                self.get_request_trace_context(),
                _trim_text(video_source, 200),
                elapsed_ms,
                _current_task_name(),
            )
            raise
        except Exception as exc:
            elapsed_ms = int((_time.monotonic() - request_started_at) * 1000)
            logger.warning(
                "video_view failed base_url=%s model=%s trace=%s video=%s duration_ms=%s status=%s response=%s error=%s",
                resolved_base_url,
                selected_model,
                self.get_request_trace_context(),
                _trim_text(video_source, 200),
                elapsed_ms,
                getattr(getattr(exc, "response", None), "status_code", ""),
                _trim_text(getattr(getattr(exc, "response", None), "text", ""), 800),
                str(exc),
            )
            return None

    # def _build_generic_image_analysis_prompt(
    #     self,
    #     *,
    #     sender_name: str,
    #     receiver_name: str,
    # ) -> str:
    #     return (
    #         "你是通用图片识别助手。"
    #         "请先对图片做第一轮通用识别，并严格返回 JSON。"
    #         '输出格式：{"image_type":"food|weight_scale|other","summary":"中文摘要","visible_text":"图片中的关键文字，若无则为空","key_objects":["对象1","对象2"],"reason":"判断原因"}。'
    #         "判断规则：餐食、饮料、零食、水果等归为 food；体重秤、体脂秤、称重读数界面归为 weight_scale；其他归为 other。"
    #         "不要输出 markdown，不要输出 JSON 以外的文字。"
    #         f"发送者：{sender_name or '用户'}。"
    #         f"对话对象：{receiver_name or '角色'}。"
    #     )


    def _build_domain_image_followup_prompt(
        self,
        *,
        domain_name: str,
        generic_summary: str,
        visible_text: str,
        current_state_summary: str,
        recent_dialogue: str,
    ) -> str:
        return build_domain_image_followup_prompt(
            domain_name=domain_name,
            generic_summary=generic_summary,
            visible_text=visible_text,
            current_state_summary=current_state_summary,
            recent_dialogue=recent_dialogue,
        )

    def _build_image_deep_final_text(
        self,
        *,
        domain_key: str,
        image_type: str,
        generic_analysis: dict[str, Any],
        specialized_result: Any,
    ) -> str:
        generic_summary = str(generic_analysis.get("summary") or "").strip()
        visible_text = str(generic_analysis.get("visible_text") or "").strip()
        if domain_key == "weight_loss" and image_type == "food" and isinstance(specialized_result, dict):
            foods = list(specialized_result.get("foods") or [])
            food_names = [str(item.get("name") or "").strip() for item in foods if isinstance(item, dict) and str(item.get("name") or "").strip()]
            total_calories = specialized_result.get("total_calories", 0)
            total_protein = specialized_result.get("total_protein", 0)
            meal_type = str(specialized_result.get("meal_type") or "").strip()
            health_rating = specialized_result.get("health_rating", 0)
            overall_description = str(specialized_result.get("overall_description") or "").strip()
            return (
                f"图片是一份与饮食相关的内容，识别食物有：{', '.join(food_names) or '未明确'}；"
                f"餐型：{meal_type or '未明确'}；总热量：{total_calories} 千卡；总蛋白质：{total_protein} 克；"
                f"健康评分：{health_rating}。"
                f"{overall_description or generic_summary}"
            ).strip()
        if domain_key == "weight_loss" and image_type == "weight_scale" and isinstance(specialized_result, dict):
            weight_kg = specialized_result.get("weight_kg", 0)
            body_fat_percent = specialized_result.get("body_fat_percent", 0)
            bmi = specialized_result.get("bmi", 0)
            interpretation = str(specialized_result.get("health_interpretation") or "").strip()
            return (
                f"图片是体重秤或体脂秤读数；体重：{weight_kg} 公斤；体脂率：{body_fat_percent}%；BMI：{bmi}。"
                f"{interpretation or generic_summary}"
            ).strip()
        if isinstance(specialized_result, dict):
            text_value = _stringify_json(specialized_result)
            if text_value:
                return text_value
        text_value = str(specialized_result or "").strip()
        if text_value:
            return text_value
        return generic_summary or visible_text


    async def speech_discern(
        self,
        audio_url: str,
        prompt: str = "",
        model: Optional[str] = None,
        language: Optional[str] = None,
        temperature: float = 0.2,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        enable_itn: bool = False,
    ) -> Optional[str]:
        """使用 Qwen3-ASR-Flash 的 OpenAI 兼容接口识别公网音频或 Data URI。"""
        resolved_base_url = _resolve_base_url(base_url, self.base_url)
        url = _openai_compatible_endpoint(resolved_base_url, "chat/completions")
        selected_model = self._resolve_voice_discern_model(model)
        audio_source = str(audio_url or "").strip()
        if not audio_source:
            return None

        messages: list[dict[str, Any]] = []
        context_text = str(prompt or "").strip()
        if context_text:
            messages.append({"role": "system", "content": context_text})
        messages.append({
            "role": "user",
            "content": [{
                "type": "input_audio",
                "input_audio": {"data": audio_source},
            }],
        })
        asr_options: dict[str, Any] = {"enable_itn": bool(enable_itn)}
        language_text = str(language or "").strip()
        if language_text:
            asr_options["language"] = language_text
        data: dict[str, Any] = {
            "model": selected_model,
            "messages": messages,
            "stream": False,
            "asr_options": asr_options,
        }

        # Qwen3-ASR-Flash 不支持 temperature；保留参数仅兼容现有调用方。
        _ = temperature
        headers = self._headers(token)
        request_started_at = perf_counter()
        try:
            timeout = httpx.Timeout(
                connect=min(self.video_analysis_timeout_seconds, 30),
                read=self.video_analysis_timeout_seconds,
                write=min(self.video_analysis_timeout_seconds, 60),
                pool=min(self.video_analysis_timeout_seconds, 30),
            )
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, headers=headers, json=data)
                response.raise_for_status()
                payload = response.json()

            if isinstance(payload, dict):
                self._record_token_usage(api_name="speech_discern", model=selected_model, payload=payload)
                text = _extract_asr_text(payload)
                if text:
                    logger.info(
                        "speech_discern completed base_url=%s model=%s trace=%s duration_ms=%s "
                        "response_length=%s",
                        resolved_base_url,
                        selected_model,
                        self.get_request_trace_context(),
                        max(int((perf_counter() - request_started_at) * 1000), 0),
                        len(text),
                    )
                    return text
            logger.warning(
                "speech_discern returned empty transcript base_url=%s model=%s trace=%s",
                resolved_base_url,
                selected_model,
                self.get_request_trace_context(),
            )
            return None
        except asyncio.CancelledError:
            logger.warning(
                "speech_discern cancelled url=%s model=%s trace=%s audio=%s task=%s",
                url,
                selected_model,
                self.get_request_trace_context(),
                _trim_text(audio_source, 200),
                _current_task_name(),
            )
            raise
        except Exception as exc:
            logger.warning(
                "speech_discern failed base_url=%s model=%s trace=%s error_type=%s "
                "error=%r timeout_seconds=%s duration_ms=%s",
                resolved_base_url,
                selected_model,
                self.get_request_trace_context(),
                exc.__class__.__name__,
                exc,
                self.video_analysis_timeout_seconds,
                max(int((perf_counter() - request_started_at) * 1000), 0),
            )
            return None

    async def speech_filetrans(
        self,
        audio_url: str,
        *,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        enable_itn: bool = False,
        enable_words: bool = True,
        poll_interval_seconds: float = 1.0,
        max_wait_seconds: float | None = None,
    ) -> dict[str, Any] | None:
        """提交 Qwen3-ASR-Flash-Filetrans 异步任务并下载完整结果。"""
        audio_source = str(audio_url or "").strip()
        if not audio_source:
            return None

        resolved_base_url = _resolve_base_url(base_url, self.base_url)
        submit_url = _dashscope_endpoint(
            resolved_base_url,
            "services/audio/asr/transcription",
        )
        selected_model = self._resolve_voice_filetrans_model(model)
        headers = self._headers(token)
        headers["X-DashScope-Async"] = "enable"
        body = {
            "model": selected_model,
            "input": {"file_url": audio_source},
            "parameters": {
                "channel_id": [0],
                "enable_itn": bool(enable_itn),
                "enable_words": bool(enable_words),
            },
        }
        wait_limit = float(
            max_wait_seconds
            if max_wait_seconds is not None
            else self.video_analysis_timeout_seconds
        )
        started_at = perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    submit_url,
                    headers=headers,
                    json=body,
                )
                response.raise_for_status()
                payload = response.json()
                if _contains_filetrans_result(payload):
                    return payload

                task_id = str(_find_nested_value(payload, "task_id") or "").strip()
                if not task_id:
                    raise ValueError("Filetrans submit response does not contain task_id")
                task_url = _dashscope_endpoint(resolved_base_url, f"tasks/{task_id}")

                while True:
                    if perf_counter() - started_at > wait_limit:
                        raise TimeoutError(f"Filetrans task {task_id} timed out")
                    task_response = await client.get(task_url, headers=self._headers(token))
                    task_response.raise_for_status()
                    task_payload = task_response.json()
                    status = str(
                        _find_nested_value(task_payload, "task_status")
                        or _find_nested_value(task_payload, "status")
                        or ""
                    ).upper()
                    if status in {"FAILED", "CANCELED", "CANCELLED", "UNKNOWN"}:
                        message = _find_nested_value(task_payload, "message") or status
                        raise ValueError(f"Filetrans task {task_id} failed: {message}")
                    if status == "SUCCEEDED" or _find_nested_value(
                        task_payload,
                        "transcription_url",
                    ):
                        self._record_token_usage(
                            api_name="speech_filetrans",
                            model=selected_model,
                            payload=task_payload,
                        )
                        transcription_url = str(
                            _find_nested_value(task_payload, "transcription_url") or ""
                        ).strip()
                        if not transcription_url:
                            if _contains_filetrans_result(task_payload):
                                return task_payload
                            raise ValueError(
                                f"Filetrans task {task_id} has no transcription_url"
                            )
                        result_response = await client.get(transcription_url)
                        result_response.raise_for_status()
                        result_payload = result_response.json()
                        logger.info(
                            "speech_filetrans completed base_url=%s model=%s trace=%s "
                            "task_id=%s duration_ms=%s",
                            resolved_base_url,
                            selected_model,
                            self.get_request_trace_context(),
                            task_id,
                            max(int((perf_counter() - started_at) * 1000), 0),
                        )
                        return result_payload if isinstance(result_payload, dict) else None
                    await asyncio.sleep(max(float(poll_interval_seconds), 0.05))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "speech_filetrans failed base_url=%s model=%s trace=%s audio=%s error=%s",
                resolved_base_url,
                selected_model,
                self.get_request_trace_context(),
                _trim_text(audio_source, 200),
                str(exc) or exc.__class__.__name__,
            )
            return None

    async def speech_synthesis(
        self,
        model: Optional[str],
        text: str,
        voice: str,
        response_format: str = "mp3",
        speed: float = 1.0,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        extra_body: Optional[dict[str, Any]] = None,
    ) -> bytes:
        resolved_base_url = _resolve_base_url(base_url, self.base_url)
        url = f"{resolved_base_url}/v1/audio/speech"
        selected_model = self._resolve_voice_model(model)
        body: dict[str, Any] = {
            "model": selected_model,
            "input": text,
            "voice": voice,
            "response_format": response_format,
            "speed": speed,
        }
        if extra_body:
            body.update(extra_body)
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(url, headers=self._headers(token), json=body)
            response.raise_for_status()
            return response.content

    async def embeddings(
        self,
        model: Optional[str],
        input_text: str | list[str],
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        extra_body: Optional[dict[str, Any]] = None,
        use_local: bool = False,
    ) -> list[list[float]]:
        if use_local:
            return await self.local_embeddings(
                model=model,
                input_text=input_text,
                base_url=base_url,
            )
        resolved_base_url = _resolve_base_url(base_url, self.base_url)
        url = f"{resolved_base_url}/v1/embeddings"
        selected_model = self._resolve_embedding_model(model)
        body: dict[str, Any] = {
            "model": selected_model,
            "input": input_text,
        }
        if extra_body:
            body.update(extra_body)
        headers = self._headers(token)
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(url, headers=headers, json=body)
                response.raise_for_status()
                payload = response.json()
            self._record_token_usage(api_name="embeddings", model=selected_model, payload=payload)
            vectors: list[list[float]] = []
            for item in payload.get("data", []):
                embedding = item.get("embedding")
                if isinstance(embedding, list):
                    vectors.append(embedding)
            return vectors
        except asyncio.CancelledError:
            logger.warning(
                "embeddings cancelled url=%s model=%s trace=%s input_type=%s task=%s",
                url,
                selected_model,
                self.get_request_trace_context(),
                type(input_text).__name__,
                _current_task_name(),
            )
            raise
        except httpx.HTTPStatusError as exc:
            response = exc.response
            logger.warning(
                "embeddings http_status_error url=%s status=%s base_url=%s model=%s trace=%s auth=%s token=%s response=%s",
                url,
                getattr(response, "status_code", ""),
                resolved_base_url,
                selected_model,
                self.get_request_trace_context(),
                "Authorization" in (headers if isinstance(headers, dict) else {}),
                _token_fingerprint(token if token is not None else self.token),
                _trim_text(getattr(response, "text", ""), 800),
            )
            return []
        except Exception as exc:
            logger.warning(
                "embeddings failed base_url=%s model=%s use_local=%s trace=%s error=%s",
                resolved_base_url,
                selected_model,
                use_local,
                self.get_request_trace_context(),
                str(exc),
            )
            return []

    async def local_embeddings(
        self,
        model: Optional[str],
        input_text: str | list[str],
        base_url: Optional[str] = None,
    ) -> list[list[float]]:
        resolved_base_url = _resolve_base_url(base_url, DEFAULT_OLLAMA_BASE_URL)
        url = f"{resolved_base_url}/api/embed"
        selected_model = str(model).strip() if model is not None else ""
        if selected_model.lower() in {"", "none", "null"}:
            selected_model = DEFAULT_LOCAL_EMBEDDING_MODEL
        body: dict[str, Any] = {
            "model": selected_model,
            "input": input_text,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(url, json=body)
                response.raise_for_status()
                payload = response.json()
            embeddings = payload.get("embeddings")
            if isinstance(embeddings, list) and embeddings:
                if isinstance(embeddings[0], list):
                    return [[float(x) for x in row] for row in embeddings if isinstance(row, list)]
                if all(isinstance(x, (int, float)) for x in embeddings):
                    return [[float(x) for x in embeddings]]
            embedding = payload.get("embedding")
            if isinstance(embedding, list) and all(isinstance(x, (int, float)) for x in embedding):
                return [[float(x) for x in embedding]]
            return []
        except asyncio.CancelledError:
            logger.warning(
                "local_embeddings cancelled url=%s model=%s trace=%s input_type=%s task=%s",
                url,
                selected_model,
                self.get_request_trace_context(),
                type(input_text).__name__,
                _current_task_name(),
            )
            raise
        except Exception as exc:
            logger.warning(
                "local_embeddings failed base_url=%s model=%s trace=%s error=%s",
                resolved_base_url,
                selected_model,
                self.get_request_trace_context(),
                str(exc),
            )
            return []



# default_ai_service = AIService(llm_model="gpt-5.4")
default_ai_service = AIService(llm_model="qwen-plus")
stupid_ai_service = AIService(llm_model="qwen-flash")
smart_ai_service = AIService(llm_model="claude-sonnet-4-6")
