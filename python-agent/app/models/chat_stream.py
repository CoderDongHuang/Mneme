"""Canonical chat SSE payloads; exported for Gateway and browser validation."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.chat import PendingMemory, Source


def json_integer(value):
    return int(value) if type(value) is float and value.is_integer() else value


class StreamSource(Source):
    model_config = ConfigDict(allow_inf_nan=False)
    page: int | None = Field(default=None, ge=-2147483648, le=2147483647)
    visual_page: int | None = Field(default=None, ge=-2147483648, le=2147483647)
    retrieval_ranks: dict[str, Annotated[int, Field(ge=-2147483648, le=2147483647)]] = Field(default_factory=dict)

    @field_validator("page", "visual_page", mode="before")
    @classmethod
    def integer_fields(cls, value):
        return json_integer(value)

    @field_validator("retrieval_ranks", mode="before")
    @classmethod
    def integer_ranks(cls, value):
        return {key: json_integer(rank) for key, rank in value.items()} if isinstance(value, dict) else value


class StreamMemory(PendingMemory):
    model_config = ConfigDict(allow_inf_nan=False)


class Payload(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)

    @field_validator("*", mode="before")
    @classmethod
    def json_integer(cls, value, info):
        # JSON Schema integers include 1.0; bools and numeric strings do not.
        if info.field_name in {"answer_generation", "answer_length"} and type(value) is float and value.is_integer():
            return json_integer(value)
        if info.field_name == "ok" and value is not None and type(value) is not bool:
            raise ValueError("boolean required")
        return value


class Start(Payload):
    session_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1, max_length=64)
    answer_generation: int = Field(ge=1, le=9007199254740991)


class Meta(Payload):
    sources: list[StreamSource]
    intent: str | None = None


class Token(Payload):
    content: str


class Memory(Payload):
    pending: list[StreamMemory]
    status: Literal["queued"] | None = None


class Done(Payload):
    answer_length: int | None = Field(default=None, ge=0, le=9007199254740991)
    ok: Literal[True] | None = None
    replayed: bool | None = None

    model_config = ConfigDict(strict=True, extra="forbid", json_schema_extra={
        "anyOf": [
            {"required": ["answer_length"], "properties": {"answer_length": {"type": "integer", "minimum": 0}}},
            {"required": ["ok"], "properties": {"ok": {"const": True}}},
        ],
    })

    @model_validator(mode="after")
    def has_completion_receipt(self):
        if self.answer_length is None and self.ok is not True:
            raise ValueError("completion receipt required")
        return self


class Error(Payload):
    message: str = Field(min_length=1)
    code: str | None = None


class Stopped(Payload):
    code: Literal["USER_STOPPED"]
    message: str | None = None


EVENT_MODELS = {
    "start": Start, "meta": Meta, "token": Token, "memory": Memory,
    "done": Done, "error": Error, "stopped": Stopped,
}
AGENT_EVENTS = ("meta", "token", "memory", "done", "error")
TERMINAL_EVENTS = ("done", "error", "stopped")


def validate_event(event: str, payload: dict, *, agent=False) -> None:
    # Never echo payloads (answers, citations, candidates) in protocol errors.
    try:
        if agent and event not in AGENT_EVENTS:
            raise ValueError()
        EVENT_MODELS[event].model_validate(payload, strict=True)
    except (KeyError, ValueError, TypeError):
        raise ValueError("INVALID_CHAT_EVENT") from None
