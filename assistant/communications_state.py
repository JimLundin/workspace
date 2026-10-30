"""Immutable saved drafts, settings and outgoing evidence; incoming bodies stay volatile."""

from dataclasses import dataclass, field
from typing import Annotated

from pydantic import BeforeValidator, Field, PlainSerializer, StringConstraints, TypeAdapter

from assistant.communications import MAX_FOLLOWED, MAX_HANDLED, Delivery

type ConversationId = Annotated[str, StringConstraints(max_length=512)]
type DraftText = Annotated[str, StringConstraints(max_length=32000)]

_DRAFT_VALUES = TypeAdapter(dict[ConversationId, DraftText])


def draft_pairs(value: object) -> tuple[tuple[str, str], ...]:
    return tuple(_DRAFT_VALUES.validate_python(value).items())


def draft_values(pairs: tuple[tuple[str, str], ...]) -> dict[str, str]:
    # This map is the drafts field's native wire representation, not domain state.
    return dict(pairs)


def restored_delivery(value: object) -> Delivery:
    match value:
        case Delivery():
            return value
        case str() as name:
            try:
                return Delivery[name]
            except KeyError as error:
                raise ValueError("Unknown saved delivery state.") from error
        case _:
            raise ValueError("Invalid saved delivery state.")


def delivery_name(value: Delivery) -> str:
    return value.name


@dataclass(frozen=True, slots=True)
class StoredReply:
    identity: ConversationId
    conversation: ConversationId
    title: Annotated[str, StringConstraints(max_length=300)]
    text: DraftText
    created_at: Annotated[float, Field(ge=0, allow_inf_nan=False, strict=True)]
    delivery: Annotated[Delivery, BeforeValidator(restored_delivery), PlainSerializer(delivery_name, return_type=str)]
    detail: Annotated[str, StringConstraints(max_length=1000)] = ""


@dataclass(frozen=True, slots=True)
class StoredAcknowledgement:
    source: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    identity: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    fingerprint: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


@dataclass(frozen=True, slots=True)
class CommunicationsState:
    target: ConversationId = ""
    followed: Annotated[tuple[ConversationId, ...], Field(max_length=MAX_FOLLOWED)] = ()
    muted_apps: Annotated[tuple[ConversationId, ...], Field(max_length=256)] = ()
    drafts: Annotated[
        tuple[tuple[ConversationId, DraftText], ...],
        BeforeValidator(draft_pairs),
        PlainSerializer(draft_values),
        Field(max_length=150),
    ] = ()
    replies: Annotated[tuple[StoredReply, ...], Field(max_length=50)] = ()
    handled: Annotated[tuple[StoredAcknowledgement, ...], Field(max_length=MAX_HANDLED)] = ()
    enabled: Annotated[bool, Field(strict=True)] = field(default=False, kw_only=True)


COMMUNICATIONS_STATE = TypeAdapter(CommunicationsState)
