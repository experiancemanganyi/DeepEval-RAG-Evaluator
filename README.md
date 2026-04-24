# ⚡ E.V.O — LLM Evaluator

> **Evaluate · Validate · Optimize**
> A Streamlit-based RAG evaluation platform powered by DeepEval, Supabase, and OpenAI.

E.V.O lets you upload documents to a Supabase vector store, auto-synthesize Q&A test cases from your chunks, fire them against any RAG pipeline via an n8n webhook, and score the responses across up to 8 LLM quality metrics — all from a single UI.

---

## Features

- **Document ingestion** — upload PDF, DOCX, TXT, CSV, or XLSX files; auto-chunked and stored in Supabase
- **Golden synthesis** — uses DeepEval's `Synthesizer` to generate realistic Q&A pairs from your chunks
- **RAG evaluation** — sends questions to your n8n webhook and scores responses with DeepEval metrics
- **8 built-in metrics** — Answer Relevancy, Faithfulness, Hallucination, Contextual Relevancy/Precision/Recall, Bias, Toxicity
- **Live console** — real-time log output during evaluation runs
- **Export** — download all generated Q&A test cases as JSON
- **Confident AI cloud** *(optional)* — push/pull golden datasets to DeepEval's cloud platform

---

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10+ | 3.11 recommended |
| Supabase project | Free tier is fine |
| OpenAI API key | Used by DeepEval for synthesis & judging |
| n8n instance | Must have a RAG workflow with a webhook trigger |
| Confident AI account | Optional — for cloud dataset storage |

---

## Quick Start

### 1. Clone the repo

```bash
git clone https://github.com/your-username/evo-llm-evaluator.git
cd evo-llm-evaluator
```

### 2. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```


### 5. Set up your Supabase table


### 6. Run the app

```bash
streamlit run EVO.py
```

The app will open at `http://localhost:8501`.

---

## Usage

### Upload Tab
1. Enter your Supabase credentials and table name in the sidebar
2. Go to the **UPLOAD** tab
3. Drag and drop or browse for your documents (PDF, DOCX, TXT, CSV, XLSX)
4. Click **UPLOAD & PROCESS** — documents are chunked and stored in Supabase

### Evaluate Tab
1. Enter your OpenAI API key and n8n webhook URL in the sidebar
2. Select which metrics to run
3. Set the max chunks per document and target Q&A pairs
4. Click **RUN EVALUATION** and watch the console log

### Results Tab
- View per-document metric scores with pass/warn/fail colouring
- Browse the generated Q&A test cases
- Export all results as JSON

---

## CLI Mode

A headless CLI version is also included for use in CI/CD pipelines.

```bash
# Upload documents only
python main.py   # choose option 1

# Run evaluation only
python main.py   # choose option 2

# Upload then evaluate
python main.py   # choose option 3
```

The CLI reads the same `.env` file as the Streamlit app.

---

---

## Environment Variables Reference

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Yes | OpenAI key used by DeepEval for synthesis and judging |
| `SUPABASE_URL` | Yes | Your Supabase project URL |
| `SUPABASE_KEY` | Yes | Supabase service role key (not anon key) |
| `SUPABASE_TABLE` | Yes | Table name where document chunks are stored |
| `N8N_WEBHOOK` | Yes | Full URL of your n8n RAG webhook endpoint |
| `CONFIDENT_AI_API_KEY` | No | API key for Confident AI cloud (deepeval login) |
| `DATASET_ALIAS` | No | Alias used when pushing datasets to Confident AI |

---

## Supported File Types

| Extension | Parser |
|---|---|
| `.pdf` | PyPDF2 |
| `.docx` | python-docx |
| `.txt` | Built-in |
| `.csv` | pandas |
| `.xlsx` | pandas + openpyxl |

---

## Metrics

| Metric | What it measures |
|---|---|
| Answer Relevancy | Is the answer on-topic for the question? |
| Faithfulness | Does the answer stick to the retrieved context? |
| Hallucination | Does the answer contradict the context? |
| Contextual Relevancy | Is the retrieved context relevant to the question? |
| Contextual Precision | Are the most relevant chunks ranked highest? |
| Contextual Recall | Does the context cover the expected answer? |
| Bias | Does the answer show demographic or ideological bias? |
| Toxicity | Does the answer contain harmful language? |

All metrics default to a threshold of `0.5` and use GPT-4o as the judge model.

---


