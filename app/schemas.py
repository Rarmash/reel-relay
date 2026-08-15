from pydantic import BaseModel, Field


class DownloadRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[^\s].*[^\s]$|^[^\s]$")
