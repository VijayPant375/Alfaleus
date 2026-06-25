import uuid
from typing import Optional
from pydantic import BaseModel

class ScrapeRequest(BaseModel):
    title: Optional[str] = None
    location: Optional[str] = None

class ScrapeResponse(BaseModel):
    job_id: uuid.UUID
    linkedin_count: int
    indeed_count: int
    total_added: int
    warnings: list[str]
