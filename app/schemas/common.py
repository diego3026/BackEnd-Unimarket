"""Base de los schemas: JSON en camelCase (como los modelos de Dart)."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

T = TypeVar("T")


class CamelModel(BaseModel):
    """Acepta snake_case o camelCase al recibir y responde en camelCase."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        str_strip_whitespace=True,
    )


class InputModel(CamelModel):
    """Para cuerpos de petición: rechaza campos desconocidos."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        str_strip_whitespace=True,
        extra="forbid",
    )


class Page(CamelModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int


class Message(CamelModel):
    message: str


class PageParams(CamelModel):
    page: int = Field(1, ge=1)
    size: int = Field(20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size
