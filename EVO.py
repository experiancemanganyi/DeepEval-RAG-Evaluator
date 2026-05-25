import streamlit as st
import os
import json
import time
import requests
import uuid
import tempfile
import PyPDF2
import pandas as pd
import openai
import deepeval
import webbrowser
from io import BytesIO

from datetime import datetime
from supabase import create_client
from deepeval.synthesizer import Synthesizer
from deepeval.test_case import LLMTestCase
from deepeval.dataset import EvaluationDataset
from deepeval.metrics import (
    AnswerRelevancyMetric,
    FaithfulnessMetric,
    HallucinationMetric,
    ContextualRelevancyMetric,
    BiasMetric,
    ToxicityMetric,
    ContextualPrecisionMetric,
    ContextualRecallMetric,
)
from deepeval.evaluate import evaluate
from deepeval.models import DeepEvalBaseLLM
from deepeval.dataset import Golden
from docx import Document
from dotenv import load_dotenv
from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch

load_dotenv()

# PAGE CONFIGURATION
st.set_page_config(
    page_title="E.V.O - LLM Evaluator",
    page_icon="img/logo.png",
    layout="wide",
    initial_sidebar_state="expanded",
)

# CUSTOM CSS STYLING
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

:root {
    --bg-base: #0f172a;
    --bg-panel: #1e293b;
    --bg-card: #334155;
    --border: #475569;
    --primary: #818cf8;
    --primary-light: #a5b4fc;
    --primary-dark: #6366f1;
    --success: #34d399;
    --error: #f87171;
    --warning: #fbbf24;
    --info: #60a5fa;
    --text-primary: #f1f5f9;
    --text-secondary: #cbd5e1;
    --text-muted: #94a3b8;
}

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
    background-color: var(--bg-base);
    color: var(--text-primary);
}

.stApp {
    background-color: var(--bg-base);
}

[data-testid="stSidebar"] {
    background-color: var(--bg-panel);
    border-right: 1px solid var(--border);
}

[data-testid="stButton"] button {
    background-color: var(--primary);
    color: #0f172a;
    border: none;
    border-radius: 8px;
    font-weight: 600;
    transition: all 0.2s;
}

[data-testid="stButton"] button:hover {
    background-color: var(--primary-dark);
    transform: translateY(-1px);
}

[data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea {
    background-color: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text-primary);
}

[data-testid="stFileUploader"] {
    background-color: var(--bg-card);
    border: 1px dashed var(--primary);
    border-radius: 10px;
}

[data-testid="stProgress"] > div > div {
    background-color: #1e293b !important;
    border-radius: 8px !important;
}

[data-testid="stProgress"] > div > div > div {
    background: linear-gradient(90deg, #818cf8, #a5b4fc) !important;
    border-radius: 8px !important;
    box-shadow: 0 0 6px #818cf8 !important;
}

.evo-card {
    background-color: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.2rem;
    margin-bottom: 1rem;
}

.metric-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 1rem;
    margin-bottom: 1.5rem;
}

.metric-tile {
    background-color: var(--bg-panel);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1rem;
    text-align: center;
}

.log-console {
    background-color: #0f172a;
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1rem;
    font-family: monospace;
    font-size: 0.75rem;
    max-height: 400px;
    overflow-y: auto;
    color: var(--text-secondary);
}

.status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    display: inline-block;
}

.status-ok { background-color: var(--success); }
.status-err { background-color: var(--error); }
.status-idle { background-color: var(--text-muted); }
.status-testing { background-color: var(--warning); animation: pulse 1s infinite; }

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
}

.conn-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.5rem 0.75rem;
    background-color: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-bottom: 0.5rem;
}

.logo-text {
    font-size: 2rem;
    font-weight: 700;
    text-align: center;
    color: var(--primary-light);
    margin-bottom: 0.2rem;
}

.page-title {
    font-size: 1.75rem;
    font-weight: 600;
    letter-spacing: -0.5px;
    margin-bottom: 0.25rem;
    color: var(--text-primary);
}

.page-tagline {
    font-size: 0.75rem;
    color: var(--text-secondary);
    margin-bottom: 1.5rem;
}

.home-card {
    background-color: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 2rem;
    text-align: center;
    margin-bottom: 1.5rem;
}

.feature-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 1.5rem;
    margin-top: 2rem;
}

.feature-item {
    background-color: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.5rem;
    text-align: center;
    transition: all 0.2s;
}

.feature-item:hover {
    transform: translateY(-3px);
    border-color: var(--primary);
}

.feature-icon {
    font-size: 2rem;
    margin-bottom: 0.5rem;
}

.feature-title {
    font-size: 1rem;
    font-weight: 600;
    margin-bottom: 0.5rem;
    color: var(--primary-light);
}

.feature-desc {
    font-size: 0.75rem;
    color: var(--text-secondary);
}

.success-badge {
    background-color: rgba(52,211,153,0.15);
    color: var(--success);
    padding: 0.25rem 0.75rem;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 500;
    display: inline-block;
}

.error-badge {
    background-color: rgba(248,113,113,0.15);
    color: var(--error);
    padding: 0.25rem 0.75rem;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 500;
    display: inline-block;
}

.score-pass {
    color: var(--success);
    font-weight: 700;
}

.score-warn {
    color: var(--warning);
    font-weight: 700;
}

.score-fail {
    color: var(--error);
    font-weight: 700;
}

.metric-name {
    font-size: 0.7rem;
    font-weight: 500;
    color: var(--text-secondary);
    text-transform: uppercase;
    margin-top: 0.3rem;
}

.metric-score {
    font-size: 2rem;
    font-weight: 700;
}
</style>
""", unsafe_allow_html=True)

# SESSION STATE INITIALIZATION
def init_session_state():
    defaults = {
        "supabase_status": "idle",
        "openai_status": "idle",
        "confident_status": "idle",
        "supabase_url": os.getenv("SUPABASE_URL", ""),
        "supabase_key": os.getenv("SUPABASE_KEY", ""),
        "supabase_table": os.getenv("SUPABASE_TABLE", "eval_documents"),
        "openai_key": os.getenv("OPENAI_API_KEY", ""),
        "openai_model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "confident_key": os.getenv("CONFIDENT_AI_API_KEY", ""),
        "webhook_url": os.getenv("RAG_WEBHOOK", ""),
        "logs": [],
        "eval_results": [],
        "goldens": [],
        "raw_goldens": [],
        "running": False,
        "run_complete": False,
        "rag_active": False,
        "target_qa": 5,
        "max_chunks": 10,
        "dataset_alias": "RAG_Eval",
        "uploaded_docs": [],
        "page": "Home",
        "evaluation_success": False,
        "confident_url": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# HELPER FUNCTIONS
def add_log(message, kind="info"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    st.session_state.logs.append((timestamp, kind, message))

def status_dot(status):
    classes = {
        "ok": "status-ok",
        "err": "status-err",
        "idle": "status-idle",
        "testing": "status-testing"
    }
    css_class = classes.get(status, "status-idle")
    return f'<span class="status-dot {css_class}"></span>'

# OPENAI MODEL WRAPPER FOR DEEPEVAL
class OpenAIModel(DeepEvalBaseLLM):
    def __init__(self):
        self.model_name = st.session_state.openai_model
        openai.api_key = st.session_state.openai_key
        self.client = openai.OpenAI(api_key=st.session_state.openai_key)

    def load_model(self):
        return self.client

    def generate(self, prompt):
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            return ""

    async def a_generate(self, prompt):
        import asyncio
        return await asyncio.to_thread(self.generate, prompt)

    def get_model_name(self):
        return self.model_name

# CONFFIDENT AI API FUNCTIONS
def delete_dataset_via_api(alias):
    if not st.session_state.confident_key:
        return False
    try:
        url = f"https://api.confident-ai.com/v1/datasets/{alias}"
        headers = {
            "CONFIDENT_API_KEY": st.session_state.confident_key,
            "Content-Type": "application/json"
        }
        response = requests.delete(url, headers=headers)
        if response.status_code == 200:
            add_log(f"Successfully deleted dataset '{alias}' via API", "ok")
            return True
        elif response.status_code == 404:
            add_log(f"Dataset '{alias}' does not exist", "info")
            return True
        else:
            add_log(f"API delete failed: {response.text}", "err")
            return False
    except Exception as e:
        add_log(f"API delete error: {e}", "err")
        return False

def push_goldens_to_confident_ai(goldens, alias):
    if not st.session_state.confident_key:
        add_log("Confident AI key not configured, skipping push", "warn")
        return False
    if not goldens:
        add_log("No goldens to push", "warn")
        return False
    
    try:
        deepeval.login(st.session_state.confident_key)
        
        delete_dataset_via_api(alias)
        time.sleep(2)
        
        dataset = EvaluationDataset()
        for golden in goldens:
            dataset.add_golden(golden)
        
        dataset.push(alias=alias)
        add_log(f"Successfully pushed {len(goldens)} goldens to Confident AI (alias: {alias})", "ok")
        return True
    except Exception as e:
        add_log(f"Push to Confident AI failed: {e}", "err")
        return False

def open_confident_ai():
    confident_url = "https://app.confident-ai.com"
    webbrowser.open(confident_url)
    add_log(f"Opening Confident AI dashboard", "info")

# REPORT EXPORT FUNCTIONS
def export_results_to_pdf(results, goldens, filename):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []
    
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#4f46e5'),
        alignment=1
    )
    
    story.append(Paragraph("E.V.O Evaluation Report", title_style))
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
    story.append(Spacer(1, 20))
    
    story.append(Paragraph("Evaluation Results", styles['Heading2']))
    story.append(Spacer(1, 10))
    
    if results:
        data = [["Metric", "Average Score", "Threshold", "Status"]]
        for metric_name, scores in results.items():
            if scores:
                avg_score = sum(scores) / len(scores)
                threshold = 0.4
                status = "PASS" if avg_score >= threshold else "FAIL"
                data.append([metric_name, f"{avg_score:.2f}", f"{threshold}", status])
        
        table = Table(data)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4f46e5')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ]))
        story.append(table)
        story.append(Spacer(1, 20))
    
    story.append(Paragraph("Test Cases", styles['Heading2']))
    story.append(Spacer(1, 10))
    
    for idx, golden in enumerate(goldens[:50]):
        story.append(Paragraph(f"Test Case {idx + 1}", styles['Heading3']))
        story.append(Paragraph(f"<b>Question:</b> {golden.get('question', 'N/A')}", styles['Normal']))
        story.append(Paragraph(f"<b>Expected Answer:</b> {golden.get('expected', 'N/A')}", styles['Normal']))
        story.append(Paragraph(f"<b>RAG Response:</b> {golden.get('actual', 'No response')}", styles['Normal']))
        story.append(Spacer(1, 10))
    
    doc.build(story)
    buffer.seek(0)
    return buffer

def export_results_to_docx(results, goldens, filename):
    doc = Document()
    doc.add_heading('E.V.O Evaluation Report', 0)
    doc.add_paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    doc.add_paragraph("")
    
    doc.add_heading('Evaluation Results', level=1)
    if results:
        table = doc.add_table(rows=1, cols=4)
        table.style = 'Table Grid'
        header_cells = table.rows[0].cells
        header_cells[0].text = 'Metric'
        header_cells[1].text = 'Average Score'
        header_cells[2].text = 'Threshold'
        header_cells[3].text = 'Status'
        
        for metric_name, scores in results.items():
            if scores:
                avg_score = sum(scores) / len(scores)
                threshold = 0.4
                status = "PASS" if avg_score >= threshold else "FAIL"
                row_cells = table.add_row().cells
                row_cells[0].text = metric_name
                row_cells[1].text = f"{avg_score:.2f}"
                row_cells[2].text = f"{threshold}"
                row_cells[3].text = status
    
    doc.add_heading('Test Cases', level=1)
    for idx, golden in enumerate(goldens[:50]):
        doc.add_heading(f"Test Case {idx + 1}", level=2)
        doc.add_paragraph(f"Question: {golden.get('question', 'N/A')}")
        doc.add_paragraph(f"Expected Answer: {golden.get('expected', 'N/A')}")
        doc.add_paragraph(f"RAG Response: {golden.get('actual', 'No response')}")
        doc.add_paragraph("")
    
    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

# SIDEBAR CONFIGURATION
with st.sidebar:
    logo_container = st.container()
    with logo_container:
        try:
            logo = Image.open("img/logo.png")
            st.image(logo, width=50)
        except:
            pass
        st.markdown('<div class="logo-text">E.V.O</div>', unsafe_allow_html=True)
        st.markdown('<p style="text-align:center; font-size:0.65rem; color:#94a3b8;">Evaluate Verify Optimize</p>', unsafe_allow_html=True)
    st.markdown("---")

    st.markdown("### Navigation")
    selected_page = st.radio(
        "Navigation",
        ["Home", "Upload Documents", "Generate Goldens", "Modify Goldens", "Run Evaluation", "Results", "Console"],
        label_visibility="collapsed"
    )
    st.session_state.page = selected_page
    
    st.markdown("---")
    st.markdown("### Configuration")
    
    # SUPABASE CONFIGURATION
    with st.expander("Supabase", expanded=False):
        st.session_state.supabase_url = st.text_input("Project URL", value=st.session_state.supabase_url, placeholder="https://xyz.supabase.co")
        st.session_state.supabase_key = st.text_input("Anon Key", value=st.session_state.supabase_key, type="password", placeholder="eyJ...")
        st.session_state.supabase_table = st.text_input("Table Name", value=st.session_state.supabase_table, placeholder="eval_documents")

        if st.button("Test Supabase", use_container_width=True):
            st.session_state.supabase_status = "testing"
            try:
                client = create_client(st.session_state.supabase_url, st.session_state.supabase_key)
                client.table(st.session_state.supabase_table).select("id").limit(1).execute()
                st.session_state.supabase_status = "ok"
                add_log("Supabase connected successfully", "ok")
            except Exception as e:
                st.session_state.supabase_status = "err"
                add_log(f"Supabase error: {e}", "err")
            st.rerun()

        status_text = {"ok": "Connected", "err": "Failed", "idle": "Not tested", "testing": "Testing..."}
        st.markdown(f'<div class="conn-row"><span>{status_text[st.session_state.supabase_status]}</span>{status_dot(st.session_state.supabase_status)}</div>', unsafe_allow_html=True)

    # OPENAI CONFIGURATION
    with st.expander("OpenAI", expanded=False):
        st.session_state.openai_key = st.text_input("API Key", value=st.session_state.openai_key, type="password", placeholder="sk-...")
        st.session_state.openai_model = st.selectbox("Model", ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"], index=0)

        if st.button("Test OpenAI", use_container_width=True):
            st.session_state.openai_status = "testing"
            try:
                client = openai.OpenAI(api_key=st.session_state.openai_key)
                client.models.list()
                st.session_state.openai_status = "ok"
                add_log("OpenAI connected successfully", "ok")
            except Exception as e:
                st.session_state.openai_status = "err"
                add_log(f"OpenAI error: {e}", "err")
            st.rerun()

        st.markdown(f'<div class="conn-row"><span>{status_text[st.session_state.openai_status]}</span>{status_dot(st.session_state.openai_status)}</div>', unsafe_allow_html=True)

    # CONFFIDENT AI CONFIGURATION
    with st.expander("Confident AI", expanded=False):
        st.session_state.confident_key = st.text_input("API Key", value=st.session_state.confident_key, type="password", placeholder="conf-...")

        if st.button("Test Confident AI", use_container_width=True):
            st.session_state.confident_status = "testing"
            try:
                deepeval.login(st.session_state.confident_key)
                st.session_state.confident_status = "ok"
                add_log("Confident AI connected successfully", "ok")
            except Exception as e:
                st.session_state.confident_status = "err"
                add_log(f"Confident AI error: {e}", "err")
            st.rerun()

        st.markdown(f'<div class="conn-row"><span>{status_text[st.session_state.confident_status]}</span>{status_dot(st.session_state.confident_status)}</div>', unsafe_allow_html=True)

    # RAG WEBHOOK CONFIGURATION
    with st.expander("RAG Webhook", expanded=False):
        st.session_state.webhook_url = st.text_input("Webhook URL", value=st.session_state.webhook_url, placeholder="https://.../webhook/...")

        if st.button("Test Webhook", use_container_width=True):
            try:
                response = requests.post(st.session_state.webhook_url, json={"question": "ping"}, timeout=10)
                if response.status_code < 400:
                    st.session_state.rag_active = True
                    add_log("Webhook reachable", "ok")
                else:
                    st.session_state.rag_active = False
                    add_log(f"Webhook returned {response.status_code}", "warn")
            except Exception as e:
                st.session_state.rag_active = False
                add_log(f"Webhook error: {e}", "err")
            st.rerun()

        webhook_status = "Reachable" if st.session_state.rag_active else "Not tested"
        webhook_dot = "ok" if st.session_state.rag_active else "idle"
        st.markdown(f'<div class="conn-row"><span>{webhook_status}</span>{status_dot(webhook_dot)}</div>', unsafe_allow_html=True)

# METRICS CONFIGURATION
METRICS_CONFIG = {
    "Answer Relevancy": {"threshold": 0.4},
    "Faithfulness": {"threshold": 0.4},
    "Contextual Relevancy": {"threshold": 0.5},
    "Hallucination": {"threshold": 0.3},
    "Contextual Precision": {"threshold": 0.5},
    "Contextual Recall": {"threshold": 0.5},
    "Bias": {"threshold": 0.5},
    "Toxicity": {"threshold": 0.5},
}

# HOME PAGE
if st.session_state.page == "Home":
    st.markdown('<div class="page-title">LLM Evaluation Suite</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-tagline">Professional RAG evaluation platform with DeepEval</div>', unsafe_allow_html=True)
    
    st.markdown("""
    <div class="home-card">
        <h1 style="color: #a5b4fc; margin-bottom: 0.5rem;">E.V.O Evaluation Suite</h1>
        <p style="color: #cbd5e1; font-size: 1rem;">Evaluate · Verify · Optimize</p>
        <p style="color: #94a3b8; margin-top: 1rem;">A comprehensive LLM evaluation platform for RAG systems</p>
    </div>
    """, unsafe_allow_html=True)
   
    st.markdown("---")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Documents Uploaded", len(st.session_state.uploaded_docs))
    with col2:
        st.metric("Goldens Generated", len(st.session_state.goldens))
    with col3:
        status = "Ready" if st.session_state.goldens and st.session_state.webhook_url else "Not Ready"
        st.metric("Evaluation Ready", status)
    
    st.markdown("---")
    st.markdown("""
    <div style="text-align: center; padding: 1rem;">
        <p style="color: #94a3b8; font-size: 0.8rem;">Configure your API credentials in the sidebar to get started</p>
    </div>
    """, unsafe_allow_html=True)

# UPLOAD DOCUMENTS PAGE
elif st.session_state.page == "Upload Documents":
    st.markdown('<div class="page-title">Document Upload</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-tagline">Upload documents to Supabase for processing</div>', unsafe_allow_html=True)

    uploaded_files = st.file_uploader(
        "Select files",
        type=["pdf", "docx", "txt", "csv", "xlsx"],
        accept_multiple_files=True
    )

    col1, col2 = st.columns(2)
    with col1:
        chunk_size = st.number_input("Chunk Size (words)", min_value=100, max_value=5000, value=1000, step=100)
    with col2:
        chunk_overlap = st.number_input("Chunk Overlap (words)", min_value=0, max_value=500, value=200, step=50)

    if st.button("Upload and Process Documents", disabled=not uploaded_files, use_container_width=True):
        if not st.session_state.supabase_url or not st.session_state.supabase_key:
            st.error("Configure Supabase credentials first")
        else:
            try:
                sb_client = create_client(st.session_state.supabase_url, st.session_state.supabase_key)
                test = sb_client.table(st.session_state.supabase_table).select("count").limit(1).execute()
                add_log("Supabase connection verified", "ok")
            except Exception as e:
                st.error(f"Supabase connection failed: {e}")
                add_log(f"Supabase connection error: {e}", "err")
                sb_client = None
            
            if sb_client:
                progress_bar = st.progress(0)
                status_text = st.empty()
                total_chunks_uploaded = 0
                success_count = 0
                fail_count = 0

                for idx, file in enumerate(uploaded_files):
                    status_text.markdown(f"Processing: {file.name}")
                    add_log(f"Processing {file.name}", "info")

                    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.name)[1]) as tmp:
                        tmp.write(file.getvalue())
                        tmp_path = tmp.name

                    ext = os.path.splitext(file.name)[1].lower()
                    text_content = ""

                    try:
                        if ext == ".pdf":
                            with open(tmp_path, "rb") as f:
                                reader = PyPDF2.PdfReader(f)
                                for page_num, page in enumerate(reader.pages):
                                    page_text = page.extract_text()
                                    if page_text:
                                        text_content += f"\n[Page {page_num + 1}]\n{page_text}"
                        elif ext == ".docx":
                            doc = Document(tmp_path)
                            text_content = "\n".join([p.text for p in doc.paragraphs if p.text])
                        elif ext == ".txt":
                            with open(tmp_path, "r", encoding="utf-8") as f:
                                text_content = f.read()
                        elif ext in [".csv", ".xlsx"]:
                            df = pd.read_csv(tmp_path) if ext == ".csv" else pd.read_excel(tmp_path)
                            text_content = df.to_string()
                    except Exception as e:
                        add_log(f"Read error for {file.name}: {e}", "err")
                        fail_count += 1
                        continue
                    finally:
                        os.unlink(tmp_path)

                    if not text_content.strip():
                        add_log(f"No text extracted from {file.name}", "warn")
                        fail_count += 1
                        continue

                    words = text_content.split()
                    chunks = []
                    step = max(1, chunk_size - chunk_overlap)

                    for i in range(0, len(words), step):
                        chunk_words = words[i:i + chunk_size]
                        chunk_text = " ".join(chunk_words)
                        if chunk_text.strip():
                            chunks.append(chunk_text)

                    add_log(f"Created {len(chunks)} chunks for {file.name}", "info")

                    for chunk_idx, chunk_text in enumerate(chunks):
                        data = {
                            "text": chunk_text,
                            "metadata": {
                                "file_title": file.name,
                                "source": "streamlit_upload",
                                "file_id": str(uuid.uuid4()),
                                "chunk_index": chunk_idx,
                                "total_chunks": len(chunks)
                            }
                        }
                        
                        try:
                            result = sb_client.table(st.session_state.supabase_table).insert(data).execute()
                            total_chunks_uploaded += 1
                            success_count += 1
                            add_log(f"Inserted chunk {chunk_idx + 1}/{len(chunks)} for {file.name}", "ok")
                        except Exception as e:
                            fail_count += 1
                            add_log(f"Insert error for {file.name} chunk {chunk_idx}: {e}", "err")

                    add_log(f"Completed {file.name}: {len(chunks)} chunks", "ok")
                    progress_bar.progress((idx + 1) / len(uploaded_files))

                status_text.markdown("Upload complete")
                
                if success_count > 0 and fail_count == 0:
                    st.success(f"Successfully processed {len(uploaded_files)} file(s). Uploaded {total_chunks_uploaded} chunks.")
                    st.markdown('<span class="success-badge">UPLOAD SUCCESSFUL</span>', unsafe_allow_html=True)
                elif success_count > 0:
                    st.warning(f"Partially successful. Uploaded {total_chunks_uploaded} chunks with {fail_count} errors.")
                    st.markdown('<span class="error-badge">PARTIAL FAILURE</span>', unsafe_allow_html=True)
                else:
                    st.error(f"Upload failed. No chunks were uploaded.")
                    st.markdown('<span class="error-badge">UPLOAD FAILED</span>', unsafe_allow_html=True)
                
                st.session_state.uploaded_docs = [f.name for f in uploaded_files]
                add_log(f"Upload completed. Total chunks: {total_chunks_uploaded}, Errors: {fail_count}", "ok")

                verify = sb_client.table(st.session_state.supabase_table).select("count").execute()
                add_log(f"Total rows in table after upload: {verify.count}", "info")

    if st.session_state.uploaded_docs:
        st.markdown("### Uploaded Documents")
        for doc in st.session_state.uploaded_docs:
            st.markdown(f"- {doc}")
        
        if st.session_state.supabase_url and st.session_state.supabase_key:
            try:
                sb_client = create_client(st.session_state.supabase_url, st.session_state.supabase_key)
                result = sb_client.table(st.session_state.supabase_table).select("count").execute()
                st.info(f"Total chunks in database: {result.count}")
            except:
                pass

# GENERATE GOLDENS PAGE
elif st.session_state.page == "Generate Goldens":
    st.markdown('<div class="page-title">Generate Goldens</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-tagline">Generate Q&A pairs from uploaded documents using DeepEval Synthesizer</div>', unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        target_qa = st.number_input("Target Q&A Pairs per Document", min_value=1, max_value=50, value=st.session_state.target_qa, step=1)
    with col2:
        max_chunks = st.number_input("Max Chunks per Document", min_value=1, max_value=50, value=st.session_state.max_chunks, step=1)
    
    auto_push = st.checkbox("Auto-push to Confident AI after generation", value=True)

    if st.button("Generate Goldens", use_container_width=True):
        if not st.session_state.supabase_url or not st.session_state.supabase_key:
            st.error("Configure Supabase credentials first")
        elif not st.session_state.openai_key:
            st.error("Configure OpenAI credentials first")
        else:
            sb_client = create_client(st.session_state.supabase_url, st.session_state.supabase_key)
            openai_model = OpenAIModel()

            add_log("Fetching documents from Supabase", "info")

            response = sb_client.table(st.session_state.supabase_table).select("*").execute()
            add_log(f"Total rows in table: {len(response.data)}", "info")

            documents = set()
            for row in response.data:
                metadata = row.get("metadata", {})
                if isinstance(metadata, dict):
                    file_title = metadata.get("file_title")
                    if file_title:
                        documents.add(file_title)

            documents = sorted(documents)
            add_log(f"Unique documents found: {list(documents)}", "info")

            if not documents:
                st.error("No documents found. Upload documents first")
                add_log("No documents found in table", "err")
                st.markdown('<span class="error-badge">GENERATION FAILED - NO DOCUMENTS</span>', unsafe_allow_html=True)
            else:
                st.session_state.goldens = []
                st.session_state.raw_goldens = []
                progress_bar = st.progress(0)
                status_text = st.empty()
                generation_success = True

                for doc_idx, doc_name in enumerate(documents):
                    status_text.markdown(f"Processing: {doc_name}")
                    add_log(f"Generating goldens for {doc_name}", "info")

                    chunks_response = sb_client.table(st.session_state.supabase_table).select("*").execute()
                    chunks = []
                    for row in chunks_response.data:
                        metadata = row.get("metadata", {})
                        if isinstance(metadata, dict):
                            file_title = metadata.get("file_title")
                            if file_title == doc_name:
                                chunks.append(row)
                    
                    chunks = chunks[:max_chunks]

                    if not chunks:
                        add_log(f"No chunks found for {doc_name}", "warn")
                        continue

                    chunk_texts = []
                    for chunk in chunks:
                        text = chunk.get("text", "")
                        if text:
                            chunk_texts.append(text)

                    if not chunk_texts:
                        add_log(f"No text content in chunks for {doc_name}", "warn")
                        continue

                    try:
                        synthesizer = Synthesizer(model=openai_model)
                        contexts = [[text] for text in chunk_texts]
                        max_per_context = max(1, target_qa // len(chunk_texts))
                        goldens = synthesizer.generate_goldens_from_contexts(
                            contexts=contexts,
                            max_goldens_per_context=max_per_context,
                            include_expected_output=True
                        )

                        for golden in goldens:
                            st.session_state.goldens.append({
                                "doc": doc_name,
                                "question": golden.input,
                                "expected": golden.expected_output,
                                "actual": "",
                                "context": golden.context if golden.context else []
                            })
                            st.session_state.raw_goldens.append(golden)

                        add_log(f"Generated {len(goldens)} goldens for {doc_name}", "ok")
                    except Exception as e:
                        add_log(f"Synthesis error for {doc_name}: {e}", "err")
                        generation_success = False

                    progress_bar.progress((doc_idx + 1) / len(documents))

                status_text.markdown("Generation complete")
                
                if generation_success and len(st.session_state.goldens) > 0:
                    st.success(f"Generated {len(st.session_state.goldens)} Q&A pairs")
                    st.markdown('<span class="success-badge">GENERATION SUCCESSFUL</span>', unsafe_allow_html=True)
                else:
                    st.error(f"Generation failed. No goldens were generated.")
                    st.markdown('<span class="error-badge">GENERATION FAILED</span>', unsafe_allow_html=True)
                
                add_log(f"Total goldens generated: {len(st.session_state.goldens)}", "ok")
                
                if auto_push and st.session_state.confident_key and st.session_state.raw_goldens:
                    push_goldens_to_confident_ai(st.session_state.raw_goldens, st.session_state.dataset_alias)

    if st.session_state.goldens:
        st.markdown("### Generated Goldens")
        for idx, golden in enumerate(st.session_state.goldens[:10]):
            with st.expander(f"Q{idx+1}: {golden['question'][:80]}..."):
                st.markdown(f"**Question:** {golden['question']}")
                st.markdown(f"**Expected Answer:** {golden['expected']}")
                if golden['context']:
                    st.markdown(f"**Context:** {golden['context'][0][:200]}...")

# MODIFY GOLDENS PAGE
elif st.session_state.page == "Modify Goldens":
    st.markdown('<div class="page-title">Modify Goldens</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-tagline">Edit generated Q&A pairs before evaluation</div>', unsafe_allow_html=True)

    if st.session_state.goldens:
        doc_filter = st.selectbox("Filter by Document", ["All"] + list(set(g["doc"] for g in st.session_state.goldens)))

        filtered_goldens = st.session_state.goldens
        if doc_filter != "All":
            filtered_goldens = [g for g in st.session_state.goldens if g["doc"] == doc_filter]

        for idx, golden in enumerate(filtered_goldens):
            original_idx = st.session_state.goldens.index(golden)
            
            with st.expander(f"Golden {idx+1}: {golden['question'][:60]}...", expanded=False):
                new_question = st.text_area("Question", value=golden["question"], height=80, key=f"edit_q_{idx}")
                new_expected = st.text_area("Expected Answer", value=golden["expected"], height=100, key=f"edit_e_{idx}")
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button(f"Save", key=f"save_{idx}"):
                        st.session_state.goldens[original_idx]["question"] = new_question
                        st.session_state.goldens[original_idx]["expected"] = new_expected
                        
                        if st.session_state.raw_goldens and idx < len(st.session_state.raw_goldens):
                            st.session_state.raw_goldens[original_idx].input = new_question
                            st.session_state.raw_goldens[original_idx].expected_output = new_expected
                        
                        add_log(f"Modified golden: {new_question[:50]}...", "ok")
                        st.success("Golden updated")
                        st.rerun()
                
                with col2:
                    if st.button(f"Delete", key=f"del_{idx}"):
                        st.session_state.goldens.pop(original_idx)
                        if idx < len(st.session_state.raw_goldens):
                            st.session_state.raw_goldens.pop(original_idx)
                        add_log(f"Deleted golden", "ok")
                        st.rerun()
        
        col_push, col_delete, col_add = st.columns(3)
        with col_push:
            if st.button("Push All Goldens to Confident AI", key="push_all_button", use_container_width=True):
                if st.session_state.confident_key and st.session_state.raw_goldens:
                    with st.spinner("Deleting old dataset and pushing new one..."):
                        success = push_goldens_to_confident_ai(st.session_state.raw_goldens, st.session_state.dataset_alias)
                        if success:
                            st.markdown('<span class="success-badge">PUSH SUCCESSFUL - DATASET REPLACED</span>', unsafe_allow_html=True)
                            add_log(f"Dataset '{st.session_state.dataset_alias}' replaced with {len(st.session_state.raw_goldens)} goldens", "ok")
                        else:
                            st.error("Push failed")
        
        with col_delete:
            if st.button("Delete Dataset from Confident AI", key="delete_dataset_button", use_container_width=True):
                if st.session_state.confident_key:
                    delete_dataset_via_api(st.session_state.dataset_alias)
                    st.success("Dataset deleted from Confident AI")
        
        with col_add:
            if st.button("Add New Test Case", key="add_test_case_button", use_container_width=True):
                st.session_state.goldens.append({
                    "doc": "manual",
                    "question": "",
                    "expected": "",
                    "actual": "",
                    "context": []
                })
                st.rerun()
    else:
        st.info("No goldens available. Generate goldens first.")

# RUN EVALUATION PAGE
elif st.session_state.page == "Run Evaluation":
    st.markdown('<div class="page-title">Run Evaluation</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-tagline">Evaluate RAG system performance using selected metrics</div>', unsafe_allow_html=True)

    st.markdown("### Select Metrics")
    cols = st.columns(4)
    selected_metrics = []
    for i, (metric_name, config) in enumerate(METRICS_CONFIG.items()):
        default = metric_name in ["Answer Relevancy", "Faithfulness", "Contextual Relevancy", "Hallucination"]
        with cols[i % 4]:
            if st.checkbox(metric_name, value=default, key=f"metric_{metric_name}"):
                selected_metrics.append(metric_name)

    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        push_to_cloud = st.checkbox("Push results to Confident AI", value=True)

    ready = (
        st.session_state.goldens and
        st.session_state.webhook_url and
        st.session_state.openai_key and
        selected_metrics
    )

    if not ready:
        missing = []
        if not st.session_state.goldens:
            missing.append("Generate goldens first")
        if not st.session_state.webhook_url:
            missing.append("Configure webhook URL")
        if not st.session_state.openai_key:
            missing.append("Configure OpenAI key")
        if not selected_metrics:
            missing.append("Select at least one metric")
        st.warning(f"Required: {', '.join(missing)}")

    if st.button("Launch Evaluation", disabled=not ready, use_container_width=True):
        st.session_state.running = True
        st.session_state.run_complete = False
        st.session_state.eval_results = []
        st.session_state.evaluation_success = False
        st.rerun()

    if st.session_state.running:
        progress_bar = st.progress(0)
        status_area = st.empty()

        try:
            os.environ["OPENAI_API_KEY"] = st.session_state.openai_key
            openai_model = OpenAIModel()
            add_log("Starting evaluation pipeline", "info")

            if push_to_cloud and st.session_state.confident_key:
                deepeval.login(st.session_state.confident_key)
                add_log("Confident AI authenticated", "ok")

            metrics_list = []
            for metric_name in selected_metrics:
                if metric_name == "Answer Relevancy":
                    metrics_list.append(AnswerRelevancyMetric(model=openai_model, threshold=0.4, include_reason=True))
                elif metric_name == "Faithfulness":
                    metrics_list.append(FaithfulnessMetric(model=openai_model, threshold=0.4, include_reason=True))
                elif metric_name == "Contextual Relevancy":
                    metrics_list.append(ContextualRelevancyMetric(model=openai_model, threshold=0.5, include_reason=True))
                elif metric_name == "Hallucination":
                    metrics_list.append(HallucinationMetric(model=openai_model, threshold=0.3, include_reason=True))
                elif metric_name == "Contextual Precision":
                    metrics_list.append(ContextualPrecisionMetric(model=openai_model, threshold=0.5, include_reason=True))
                elif metric_name == "Contextual Recall":
                    metrics_list.append(ContextualRecallMetric(model=openai_model, threshold=0.5, include_reason=True))
                elif metric_name == "Bias":
                    metrics_list.append(BiasMetric(model=openai_model, threshold=0.5, include_reason=True))
                elif metric_name == "Toxicity":
                    metrics_list.append(ToxicityMetric(model=openai_model, threshold=0.5, include_reason=True))

            def call_rag(question):
                try:
                    time.sleep(0.5)
                    response = requests.post(
                        st.session_state.webhook_url,
                        json={"question": question},
                        timeout=60
                    )
                    if not response.text:
                        return ""
                    data = response.json()
                    if isinstance(data, list) and data:
                        return data[0].get("answer", "") or data[0].get("output", "")
                    if isinstance(data, dict):
                        return data.get("answer", "") or data.get("output", "")
                    return str(data)
                except Exception:
                    return ""

            test_cases = []
            status_area.info("Building test cases and calling RAG endpoint...")

            for idx, golden in enumerate(st.session_state.goldens):
                if not golden["question"].strip() or not golden["expected"].strip():
                    continue
    
                if golden.get("context") is None:
                    golden["context"] = []
    
                context = golden["context"]
                if not isinstance(context, list):
                    context = [context] if context else []
    
                actual_output = call_rag(golden["question"])
                golden["actual"] = actual_output

                test_case = LLMTestCase(
                    input=golden["question"],
                    actual_output=actual_output,
                    expected_output=golden["expected"],
                    context=context,
                    retrieval_context=context
                )
                test_cases.append(test_case)
                progress_bar.progress((idx + 1) / len(st.session_state.goldens))

            status_area.info("Running evaluations...")

            evaluation_result = evaluate(test_cases=test_cases, metrics=metrics_list)

            doc_scores = {}
            for tc in test_cases:
                if hasattr(tc, "metrics_metadata") and tc.metrics_metadata:
                    for metric_name, metric_data in tc.metrics_metadata.items():
                        clean_name = metric_name.replace("Metric", "")
                        if clean_name not in doc_scores:
                            doc_scores[clean_name] = []
                        score = metric_data.get("score") if isinstance(metric_data, dict) else getattr(metric_data, "score", None)
                        if score is not None:
                            doc_scores[clean_name].append(score)

            st.session_state.eval_results = doc_scores
            st.session_state.running = False
            st.session_state.run_complete = True
            st.session_state.evaluation_success = True
            add_log("Evaluation completed successfully", "ok")
            status_area.empty()

        except Exception as e:
            add_log(f"Evaluation error: {e}", "err")
            st.session_state.running = False
            st.session_state.evaluation_success = False
            st.error(f"Evaluation failed: {e}")

        st.rerun()

    if st.session_state.run_complete and st.session_state.eval_results:
        st.success("Evaluation completed successfully")
        st.markdown('<span class="success-badge">EVALUATION SUCCESSFUL</span>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("View Results Below", use_container_width=True):
                st.session_state.page = "Results"
                st.rerun()
        with col2:
            if st.button("Open Confident AI Dashboard", use_container_width=True):
                open_confident_ai()
                st.info("Confident AI dashboard opened in your browser")

# RESULTS PAGE
elif st.session_state.page == "Results":
    st.markdown('<div class="page-title">Evaluation Results</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-tagline">Detailed evaluation scores and insights</div>', unsafe_allow_html=True)

    if st.session_state.evaluation_success:
        st.markdown('<span class="success-badge">EVALUATION COMPLETED SUCCESSFULLY</span>', unsafe_allow_html=True)
        st.markdown("---")

    if not st.session_state.eval_results and not st.session_state.goldens:
        st.markdown('<div class="evo-card"><div class="evo-card-title">No Results Yet</div><p>Run an evaluation first to see results.</p></div>', unsafe_allow_html=True)
    else:
        if st.session_state.eval_results:
            st.markdown('<div class="evo-card"><div class="evo-card-title">Results Dashboard</div>', unsafe_allow_html=True)
            st.markdown('<div class="metric-grid">', unsafe_allow_html=True)

            for metric_name, scores in st.session_state.eval_results.items():
                if scores:
                    avg_score = sum(scores) / len(scores)
                    threshold = METRICS_CONFIG.get(metric_name, {}).get("threshold", 0.5)
                    if avg_score >= threshold * 1.2:
                        score_class = "score-pass"
                        status_text = "PASS"
                    elif avg_score >= threshold:
                        score_class = "score-warn"
                        status_text = "WARNING"
                    else:
                        score_class = "score-fail"
                        status_text = "FAIL"

                    st.markdown(f"""
                    <div class="metric-tile">
                        <div class="metric-score {score_class}">{avg_score:.2f}</div>
                        <div class="metric-name">{metric_name}</div>
                        <div style="font-size:0.7rem; color:#94a3b8;">threshold: {threshold}</div>
                        <div style="font-size:0.7rem; margin-top:0.3rem;">{status_text}</div>
                    </div>
                    """, unsafe_allow_html=True)

            st.markdown('</div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
            
            col_pdf, col_docx, col_confident = st.columns(3)
            with col_pdf:
                pdf_buffer = export_results_to_pdf(st.session_state.eval_results, st.session_state.goldens, "evaluation_report.pdf")
                st.download_button(
                    "Export as PDF",
                    data=pdf_buffer,
                    file_name=f"evo_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
            
            with col_docx:
                docx_buffer = export_results_to_docx(st.session_state.eval_results, st.session_state.goldens, "evaluation_report.docx")
                st.download_button(
                    "Export as DOCX",
                    data=docx_buffer,
                    file_name=f"evo_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True
                )
            
            with col_confident:
                if st.button("Open Confident AI Dashboard", use_container_width=True):
                    open_confident_ai()
                    st.info("Confident AI dashboard opened in your browser")

        if st.session_state.goldens:
            st.markdown("### Generated Q&A with RAG Responses")
            doc_filter = st.selectbox("Filter by Document", ["All"] + list(set(g["doc"] for g in st.session_state.goldens)), key="results_filter")

            display_goldens = st.session_state.goldens
            if doc_filter != "All":
                display_goldens = [g for g in st.session_state.goldens if g["doc"] == doc_filter]

            for idx, golden in enumerate(display_goldens[:30]):
                with st.expander(f"Q{idx+1}: {golden['question'][:100]}..."):
                    st.markdown(f"**Expected Answer:** {golden['expected']}")
                    st.markdown(f"**RAG Response:** {golden['actual'] or 'No response'}")

            if st.session_state.goldens:
                export_data = json.dumps(st.session_state.goldens, indent=2, ensure_ascii=False)
                st.download_button(
                    "Export Goldens as JSON",
                    data=export_data,
                    file_name=f"evo_goldens_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                    mime="application/json"
                )

# CONSOLE PAGE
elif st.session_state.page == "Console":
    st.markdown('<div class="page-title">Console Logs</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-tagline">Real-time processing logs and debugging information</div>', unsafe_allow_html=True)

    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("Refresh", use_container_width=True):
            st.rerun()
    with col2:
        if st.button("Clear Console", use_container_width=True):
            st.session_state.logs = []
            st.rerun()

    log_html = '<div class="log-console">'
    if not st.session_state.logs:
        log_html += '<span style="color: #94a3b8;">No logs yet</span>'
    else:
        for timestamp, kind, message in st.session_state.logs:
            css_class = {
                "ok": "log-ok",
                "err": "log-err",
                "info": "log-info",
                "warn": "log-warn"
            }.get(kind, "log-info")
            log_html += f'<span style="color:#94a3b8;">[{timestamp}]</span> <span class="{css_class}">{message}</span>\n'
    log_html += '</div>'
    st.markdown(log_html, unsafe_allow_html=True)