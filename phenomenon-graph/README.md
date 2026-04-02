# Phenomenon Graph Extractor

Automatically build **phenomenon causal graphs** from DBA StackExchange Q&A posts
using any OpenAI-compatible LLM API.

## Quick Start

```bash
pip install -r requirements.txt
```

Place raw Q&A posts as `.txt` files in `data/raw/`.

---

## Model Configuration

All commands accept `--model`, `--api-key`, `--base-url`, and `--extra-headers`.
You can also set defaults in `config.yaml` or via the `LLM_API_KEY` environment variable.

### OpenAI (default)

```bash
python -m src.cli extract data/raw/post1.txt \
  --model gpt-4o \
  --api-key sk-...
```

Or in `config.yaml`:
```yaml
base_url: "https://api.openai.com/v1"
model: "gpt-4o"
api_key: "sk-..."
```

---

### Anthropic (Claude)

Anthropic's API is OpenAI-compatible when accessed via the messages endpoint.
Pass the required `anthropic-version` header:

```bash
python -m src.cli extract data/raw/post1.txt \
  --model claude-sonnet-4-20250514 \
  --api-key sk-ant-... \
  --base-url "https://api.anthropic.com/v1" \
  --extra-headers '{"anthropic-version": "2023-06-01"}'
```

Or in `config.yaml`:
```yaml
base_url: "https://api.anthropic.com/v1"
model: "claude-sonnet-4-20250514"
api_key: "sk-ant-..."
extra_headers:
  anthropic-version: "2023-06-01"
```

> **Note**: `config.yaml` `extra_headers` is not yet loaded automatically —
> pass them via `--extra-headers` on the CLI for now.

---

### Local Ollama

```bash
# Start Ollama first: ollama run llama3
python -m src.cli extract data/raw/post1.txt \
  --model llama3 \
  --api-key ollama \
  --base-url "http://localhost:11434/v1"
```

---

### Any Other OpenAI-Compatible API

```bash
python -m src.cli extract data/raw/post1.txt \
  --model <model-name> \
  --api-key <key> \
  --base-url "https://your-provider.com/v1"
```

---

## CLI Commands

### `extract` — single file

```bash
python -m src.cli extract data/raw/post1.txt \
  --model gpt-4o \
  --api-key $LLM_API_KEY \
  --output data/graphs/post1.json   # optional
```

### `batch` — entire directory

```bash
python -m src.cli batch data/raw/ \
  --model gpt-4o \
  --api-key $LLM_API_KEY \
  --skip-existing
```

### `merge` — combine all graphs

```bash
python -m src.cli merge \
  --input-dir data/graphs/ \
  --output data/merged_graph.json
```

---

## Front-end + API Service (文本抽取 / 上传抽取 / 结果合并 / 流式输出)

启动统一服务（前后端一体）：

```bash
cd phenomenon-graph
uvicorn src.server:app --host 0.0.0.0 --port 8000
```

然后通过局域网 IP 访问：

- 本机: `http://127.0.0.1:8000`
- 其他机器: `http://<你的服务器IP>:8000`

新前端能力：

- 输入文本并直接抽取现象图。
- 上传 `.txt` 文件并抽取。
- 保存本次会话中的每个抽取结果，并可多选后执行 merge。
- 支持流式展示模型输出（作为“思考流”观察窗口），并在结束后自动结构化为图。

主要 API：

- `POST /api/extract`：普通文本抽取。
- `POST /api/extract-file`：上传文本文件抽取。
- `POST /api/extract-stream`：SSE 流式输出 + 最终图。
- `GET /api/graphs`：查看当前服务内存中已有抽取结果。
- `POST /api/merge`：按 graph_id 列表合并。

---

## Visualization

Open `web/index.html` in a browser and load any `.json` file
(single graph or merged graph) via the file picker.

- **Red nodes** = symptom
- **Blue nodes** = intermediate
- **Green nodes** = root\_cause
- **Gold border** = verified hypothesis
- **Edge thickness** ∝ weight (frequency across cases)

---

## Output JSON Schema

```json
{
  "symptom": "slow query after routine maintenance",
  "nodes": [
    { "id": "slow_query", "label": "Slow query after maintenance", "type": "symptom", "verified": true },
    { "id": "stale_stats", "label": "Outdated statistics causing optimizer misestimation", "type": "root_cause", "verified": true }
  ],
  "edges": [
    { "from_id": "stale_stats", "to_id": "slow_query", "relation": "causes", "weight": 1 }
  ],
  "source_file": "data/raw/post1.txt",
  "created_at": "2026-04-02T00:00:00"
}
```

---

## Project Structure

```
phenomenon-graph/
├── src/
│   ├── schema.py      # Pydantic data models
│   ├── prompt.py      # System & user prompt templates
│   ├── extractor.py   # LLM client + JSON parsing
│   ├── graph.py       # Multi-graph merge logic
│   ├── cli.py         # CLI (extract / batch / merge)
│   └── server.py      # FastAPI service for frontend + APIs
├── data/
│   ├── raw/           # Input .txt files
│   └── graphs/        # Output .json files
├── web/
│   └── index.html     # D3.js visualizer + extraction workbench
├── config.yaml
├── requirements.txt
└── README.md
```
