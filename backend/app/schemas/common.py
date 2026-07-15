"""Pydantic schemas shared by the API routers.

Response fields use camelCase aliases to match the frontend TypeScript
contracts in ``frontend/src/types`` while keeping snake_case in Python.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base model that serializes/deserializes using camelCase aliases."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )
