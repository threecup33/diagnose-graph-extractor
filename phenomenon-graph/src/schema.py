from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class PhenomenonNode(BaseModel):
    id: str
    label: str
    type: Literal["symptom", "intermediate", "root_cause"]
    verified: bool = False


class CausalEdge(BaseModel):
    from_id: str
    to_id: str
    relation: Literal["causes", "triggers", "co-occurs"]
    label: Optional[str] = None
    weight: int = 1


class PhenomenonGraph(BaseModel):
    symptom: str
    nodes: List[PhenomenonNode] = Field(default_factory=list)
    edges: List[CausalEdge] = Field(default_factory=list)
    source_file: Optional[str] = None
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
