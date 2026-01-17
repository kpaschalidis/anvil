from pydantic import BaseModel


class SessionMetadata(BaseModel):
    id: str
    title: str | None = None
    created_at: str
    updated_at: str
    model: str


class SessionState(BaseModel):
    metadata: SessionMetadata
    system_prompt_hash: str
    system_prompt_version: str
    messages: list[dict]
