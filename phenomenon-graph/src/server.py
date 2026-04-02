from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from openai import OpenAI
from pydantic import ValidationError

from .cli import _build_llm_config, _load_config
from .extractor import Extractor
from .graph import MergedGraph
from .prompt import SYSTEM_PROMPT, build_user_prompt
from .schema import PhenomenonGraph

WEB_DIR = Path(__file__).resolve().parents[1] / "web"


@dataclass
class SessionState:
    graphs: Dict[str, PhenomenonGraph]


state = SessionState(graphs={})
app = FastAPI(title="Phenomenon Graph Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _make_extractor(
    model: Optional[str],
    api_key: Optional[str],
    base_url: Optional[str],
    extra_headers_json: Optional[str],
    config_path: Optional[str],
) -> Extractor:
    cfg = _load_config(config_path)
    llm_cfg = _build_llm_config(model, api_key, base_url, extra_headers_json, cfg)
    return Extractor(llm_cfg)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/api/extract")
async def extract_graph(
    text: str = Form(...),
    source_name: Optional[str] = Form(default=None),
    model: Optional[str] = Form(default=None),
    api_key: Optional[str] = Form(default=None),
    base_url: Optional[str] = Form(default=None),
    extra_headers: Optional[str] = Form(default=None),
    config_path: Optional[str] = Form(default=None),
) -> Dict[str, Any]:
    extractor = _make_extractor(model, api_key, base_url, extra_headers, config_path)
    graph = extractor.extract(text, source_file=source_name)
    graph_id = f"g_{len(state.graphs) + 1}"
    state.graphs[graph_id] = graph
    return {"graph_id": graph_id, "graph": graph.model_dump(mode="json")}


@app.post("/api/extract-file")
async def extract_graph_from_file(
    file: UploadFile = File(...),
    model: Optional[str] = Form(default=None),
    api_key: Optional[str] = Form(default=None),
    base_url: Optional[str] = Form(default=None),
    extra_headers: Optional[str] = Form(default=None),
    config_path: Optional[str] = Form(default=None),
) -> Dict[str, Any]:
    raw = await file.read()
    text = raw.decode("utf-8", errors="ignore")
    extractor = _make_extractor(model, api_key, base_url, extra_headers, config_path)
    graph = extractor.extract(text, source_file=file.filename)
    graph_id = f"g_{len(state.graphs) + 1}"
    state.graphs[graph_id] = graph
    return {"graph_id": graph_id, "graph": graph.model_dump(mode="json")}


@app.post("/api/extract-stream")
async def extract_stream(
    text: str = Form(...),
    source_name: Optional[str] = Form(default=None),
    model: Optional[str] = Form(default=None),
    api_key: Optional[str] = Form(default=None),
    base_url: Optional[str] = Form(default=None),
    extra_headers: Optional[str] = Form(default=None),
    config_path: Optional[str] = Form(default=None),
):
    cfg = _load_config(config_path)
    llm_cfg = _build_llm_config(model, api_key, base_url, extra_headers, cfg)
    client = OpenAI(
        base_url=llm_cfg.base_url,
        api_key=llm_cfg.api_key,
        default_headers=llm_cfg.extra_headers if llm_cfg.extra_headers else None,
    )
    user_prompt = build_user_prompt(text)

    async def event_generator():
        full_text = ""
        try:
            stream = client.chat.completions.create(
                model=llm_cfg.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
                stream=True,
            )

            for chunk in stream:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    full_text += delta
                    payload = json.dumps({"type": "thinking", "delta": delta}, ensure_ascii=False)
                    yield f"data: {payload}\n\n"

            extractor = Extractor(llm_cfg)
            graph = extractor._parse_response(full_text)
            graph.source_file = source_name
            graph_id = f"g_{len(state.graphs) + 1}"
            state.graphs[graph_id] = graph
            done_payload = json.dumps(
                {"type": "result", "graph_id": graph_id, "graph": graph.model_dump(mode="json")},
                ensure_ascii=False,
            )
            yield f"data: {done_payload}\n\n"
        except ValidationError as exc:
            err_payload = json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False)
            yield f"data: {err_payload}\n\n"
        except Exception as exc:  # noqa: BLE001
            err_payload = json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False)
            yield f"data: {err_payload}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/graphs")
def list_graphs() -> Dict[str, Any]:
    return {
        "graphs": [
            {
                "graph_id": gid,
                "symptom": g.symptom,
                "source_file": g.source_file,
                "node_count": len(g.nodes),
                "edge_count": len(g.edges),
            }
            for gid, g in state.graphs.items()
        ]
    }


@app.post("/api/merge")
async def merge_graphs(graph_ids: List[str]) -> JSONResponse:
    if not graph_ids:
        raise HTTPException(status_code=400, detail="graph_ids cannot be empty")

    merged = MergedGraph()
    missing = []
    for gid in graph_ids:
        graph = state.graphs.get(gid)
        if not graph:
            missing.append(gid)
            continue
        merged.add_graph(graph)

    if missing:
        raise HTTPException(status_code=404, detail=f"Unknown graph IDs: {', '.join(missing)}")

    return JSONResponse(
        {
            "graph": merged.to_dict(),
            "summary": merged.summary(),
        }
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.server:app", host="0.0.0.0", port=8000, reload=False)
