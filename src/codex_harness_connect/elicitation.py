"""Bounded, non-sensitive form qualification; never grants native tool permission."""
from __future__ import annotations

import asyncio
import math
import time

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class FormCheckAnswer(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    # MCP 1.30's validation helper accepts primitive annotations, not Literal.
    # Advertise the enum on the wire and enforce the same set on every answer.
    choice: str = Field(
        title="Interface check",
        description="Choose form_visible only if this form is visible and usable. "
                    "This check authorizes no action and asks for no sensitive information.",
        json_schema_extra={"enum": ["form_visible", "form_not_usable"]},
    )

    @field_validator("choice")
    @classmethod
    def exact_choice(cls, value: str) -> str:
        if value not in {"form_visible", "form_not_usable"}:
            raise ValueError("Unknown interface-check choice")
        return value


MESSAGE = (
    "Harness Connect: проверка интерфейса MCP. Если вы видите эту форму и можете ответить, "
    "выберите form_visible. Если форма неудобна или не работает, выберите form_not_usable. "
    "Можно отклонить или закрыть запрос. Проверка не запускает модель, не разрешает инструменты "
    "и не меняет настройки. Не вводите пароли, ключи или личные данные."
)


def _metadata(params) -> dict:
    """Only bounded advertised identity; never report arbitrary initialize metadata."""
    info = params.clientInfo
    def text(value, limit):
        return value[:limit] if isinstance(value, str) else None

    return {"name": text(info.name, 256), "version": text(info.version, 256),
            "client_requested_protocol": text(params.protocolVersion, 64)}


def _form_advertised(params) -> bool:
    capability = params.capabilities.elicitation
    if capability is None:
        return False
    if capability.form is not None:
        return True
    # MCP 2025-11-25 defines the legacy *empty* capability as form support.
    # A URL-only or unknown extension capability does not prove form support.
    return not capability.model_fields_set and not capability.model_extra


async def check_interaction(ctx, timeout_seconds: float = 45) -> dict:
    """Test the connected client's standard form route, with no native action/state write.

    An accepted form cannot attest to a human: MCP agent clients may generate answers.
    Consequently this result must never be reused as permission for a native operation.
    """
    if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (float, int))
            or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 45):
        raise ValueError("Interaction check timeout must be finite, positive and at most 45 seconds")
    started = time.monotonic()
    result = {"status": "unsupported", "choice": None, "form_advertised": False,
              "client": None, "authorizes_native_action": False,
              "human_attestation_verified": False, "answer_persisted_by_connector": False,
              "contract": "standard MCP form; no native permission mapping"}
    # client_params is the public initialized-session property, not private internals.
    params = ctx.request_context.session.client_params
    if params is not None:
        result["client"] = _metadata(params)
        result["form_advertised"] = _form_advertised(params)
    if result["form_advertised"]:
        deadline = time.monotonic() + timeout_seconds
        try:
            answer = await asyncio.wait_for(ctx.elicit(MESSAGE, FormCheckAnswer), timeout_seconds)
            # wait_for can receive an answer while its timeout cancellation unwinds.
            # That late answer is expired regardless of its content or action.
            if time.monotonic() >= deadline:
                result["status"] = "timed_out"
            elif answer.action == "accept":
                # Validate again at this boundary; accepted empty content is not an answer.
                data = answer.data
                if isinstance(data, BaseModel):
                    data = data.model_dump()
                validated = FormCheckAnswer.model_validate(data)
                result.update(status="answered", choice=validated.choice)
            elif answer.action in {"decline", "cancel"}:
                result["status"] = "declined" if answer.action == "decline" else "cancelled"
            else:
                result["status"] = "invalid_response"
        except TimeoutError:
            result["status"] = "timed_out"
        except (ValidationError, ValueError, AttributeError, TypeError):
            result["status"] = "invalid_response"
        except Exception:
            # Transport exceptions may embed paths, credentials or raw form responses.
            result["status"] = "transport_error"
        # Caller cancellation propagates; it cannot become an accepted result.
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return result
