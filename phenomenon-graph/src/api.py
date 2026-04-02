from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from .extractor import Extractor, LLMConfig
from .graph import MergedGraph
from .schema import PhenomenonGraph

PROJECT_ROOT = Path(__file__).parent.parent
WEB_DIR = PROJECT_ROOT / "web"
DATA_DIR = PROJECT_ROOT / "data" / "graphs"
CONFIG_PATH = PROJECT_ROOT / "config.yaml"

DATA_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="现象因果图分析系统")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _make_extractor() -> Extractor:
    cfg = _load_config()
    api_key = cfg.get("api_key") or os.environ.get("LLM_API_KEY", "")
    extra_headers = cfg.get("extra_headers")
    if isinstance(extra_headers, str):
        extra_headers = json.loads(extra_headers)
    return Extractor(LLMConfig(
        base_url=cfg.get("base_url", "https://api.openai.com/v1"),
        api_key=api_key,
        model=cfg.get("model", "gpt-4o"),
        extra_headers=extra_headers,
    ))


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ExtractRequest(BaseModel):
    text: str
    source_name: Optional[str] = None


class MergeRequest(BaseModel):
    graph_names: List[str]
    output_name: str = "merged_graph"


class ConfigUpdateRequest(BaseModel):
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    return FileResponse(str(WEB_DIR / "index.html"))


@app.get("/api/config")
async def get_config():
    cfg = _load_config()
    # Mask api_key for safety
    masked = {k: ("***" if k == "api_key" else v) for k, v in cfg.items()}
    return masked


@app.post("/api/config")
async def update_config(req: ConfigUpdateRequest):
    cfg = _load_config()
    if req.base_url is not None:
        cfg["base_url"] = req.base_url
    if req.api_key is not None:
        cfg["api_key"] = req.api_key
    if req.model is not None:
        cfg["model"] = req.model
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True)
    return {"status": "ok"}


@app.post("/api/extract")
async def extract_stream(req: ExtractRequest):
    """SSE endpoint: streams LLM thinking, then emits the final graph."""

    source_name = req.source_name or datetime.utcnow().strftime("graph_%Y%m%d_%H%M%S")
    # Sanitise name for filesystem use
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in source_name)

    async def generate():
        extractor = _make_extractor()
        graph_data = None
        try:
            async for event in extractor.extract_stream(req.text, safe_name):
                if event["type"] == "graph":
                    graph_data = event["data"]
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"

        # Persist graph to disk
        if graph_data is not None:
            out_path = DATA_DIR / f"{safe_name}.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(graph_data, f, ensure_ascii=False, indent=2)
            yield f"data: {json.dumps({'type': 'saved', 'name': safe_name}, ensure_ascii=False)}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/graphs")
async def list_graphs():
    graphs = []
    for p in sorted(DATA_DIR.glob("*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            graphs.append({
                "name": p.stem,
                "symptom": data.get("symptom", ""),
                "node_count": len(data.get("nodes", [])),
                "edge_count": len(data.get("edges", [])),
            })
        except Exception:
            pass
    return graphs


@app.get("/api/graph/{name}")
async def get_graph(name: str):
    path = DATA_DIR / f"{name}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"图谱 '{name}' 不存在")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@app.delete("/api/graph/{name}")
async def delete_graph(name: str):
    path = DATA_DIR / f"{name}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"图谱 '{name}' 不存在")
    path.unlink()
    return {"deleted": name}


@app.post("/api/merge")
async def merge_graphs(req: MergeRequest):
    if not req.graph_names:
        raise HTTPException(status_code=400, detail="请至少选择一个图谱")

    merged = MergedGraph()
    for name in req.graph_names:
        path = DATA_DIR / f"{name}.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"图谱 '{name}' 不存在")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        try:
            graph = PhenomenonGraph(**data)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"解析图谱 '{name}' 失败: {exc}")
        merged.add_graph(graph)

    safe_output = "".join(
        c if c.isalnum() or c in "-_" else "_" for c in req.output_name
    ) or "merged_graph"
    result = merged.to_dict()
    result["symptom"] = f"合并: {', '.join(req.graph_names)}"

    out_path = DATA_DIR / f"{safe_output}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    result["name"] = safe_output
    return result
