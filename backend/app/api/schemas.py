from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints


class ChatRequest(BaseModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    session_id: Annotated[str, StringConstraints(strip_whitespace=True, max_length=64)] | None = Field(
        default=None, description="会话 ID；留空则开启新会话")
