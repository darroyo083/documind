import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class CreateSpaceRequest(BaseModel):
    name: str = Field(max_length=200)
    description: str | None = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Name must not be empty")
        return stripped

    @field_validator("description")
    @classmethod
    def description_optional(cls, v: str | None) -> str | None:
        if v is not None:
            stripped = v.strip()
            return stripped if stripped else None
        return v


class UpdateSpaceRequest(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str | None) -> str | None:
        if v is not None:
            stripped = v.strip()
            if not stripped:
                raise ValueError("Name must not be empty")
            return stripped
        return v

    @field_validator("description")
    @classmethod
    def description_optional(cls, v: str | None) -> str | None:
        if v is not None:
            stripped = v.strip()
            return stripped if stripped else None
        return v


class SpaceResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
