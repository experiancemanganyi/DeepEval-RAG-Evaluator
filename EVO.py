import streamlit as st
import os
import json
import time
import requests
import threading
from datetime import datetime
from supabase import create_client
import openai as _oa
import deepeval
from supabase import create_client as _sc
from deepeval.synthesizer import Synthesizer
from deepeval.test_case import LLMTestCase
from deepeval.dataset import EvaluationDataset
from deepeval.metrics import (
    AnswerRelevancyMetric, FaithfulnessMetric, HallucinationMetric,
    ContextualRelevancyMetric, BiasMetric, ToxicityMetric,
    ContextualPrecisionMetric, ContextualRecallMetric
)
from deepeval.evaluate import evaluate as de_evaluate
from deepeval.models import DeepEvalBaseLLM

st.set_page_config(
    page_title="E.V.O · LLM Evaluator",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Rajdhani:wght@300;400;500;600;700&family=Inter:wght@300;400;500&display=swap');

:root {
    --bg-base:       #080b14;
    --bg-panel:      #0d1120;
    --bg-card:       #111827;
    --bg-card-hover: #141d2e;
    --border:        #1e2d4a;
    --border-glow:   #3b1f6e;
    --purple-deep:   #1a0d3d;
    --purple-mid:    #6c3fc5;
    --purple-bright: #9b6ef3;
    --purple-neon:   #bf8fff;
    --navy-dark:     #0a0e1a;
    --navy-mid:      #0f1729;
    --navy-accent:   #1c2e52;
    --cyan-accent:   #00d4ff;
    --green-ok:      #10b981;
    --red-err:       #ef4444;
    --amber-warn:    #f59e0b;
    --text-primary:  #e8e8f0;
    --text-secondary:#8892aa;
    --text-muted:    #4a5568;
}

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
    background-color: var(--bg-base);
    color: var(--text-primary);
}

.stApp {
    background: linear-gradient(135deg, #080b14 0%, #0d0a1f 40%, #080b14 100%);
    background-attachment: fixed;
}

.stApp::before {
    content: '';
    position: fixed;
    inset: 0;
    background-image:
        linear-gradient(rgba(107,63,197,0.04) 1px, transparent 1px),
        linear-gradient(90deg, rgba(107,63,197,0.04) 1px, transparent 1px);
    background-size: 40px 40px;
    pointer-events: none;
    z-index: -1;
}

[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0a0c1a 0%, #0d1020 100%);
    border-right: 1px solid var(--border);
    box-shadow: 4px 0 30px rgba(107,63,197,0.08);
}

[data-testid="stSidebar"] .block-container {
    padding-top: 0 !important;
}

.evo-logo {
    font-family: 'Rajdhani', sans-serif;
    font-size: 2.2rem;
    font-weight: 700;
    letter-spacing: 6px;
    background: linear-gradient(135deg, #9b6ef3 0%, #00d4ff 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    text-align: center;
    padding: 1.4rem 0 0.2rem;
}

.evo-subtitle {
    font-family: 'Space Mono', monospace;
    font-size: 0.58rem;
    letter-spacing: 3px;
    color: var(--text-muted);
    text-align: center;
    margin-bottom: 1.2rem;
}

.sidebar-divider {
    height: 1px;
    background: linear-gradient(90deg, transparent, var(--border-glow), transparent);
    margin: 0.6rem 0 1rem;
}

.sidebar-section-label {
    font-family: 'Space Mono', monospace;
    font-size: 0.6rem;
    letter-spacing: 3px;
    color: var(--purple-mid);
    text-transform: uppercase;
    margin: 1rem 0 0.4rem;
    padding-left: 2px;
}

.conn-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.55rem 0.75rem;
    border-radius: 8px;
    margin-bottom: 0.4rem;
    background: var(--bg-card);
    border: 1px solid var(--border);
    transition: border-color 0.2s;
}
.conn-row:hover { border-color: var(--purple-mid); }
.conn-label {
    font-family: 'Rajdhani', sans-serif;
    font-size: 0.88rem;
    font-weight: 500;
    letter-spacing: 1px;
    color: var(--text-secondary);
}
.status-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
}
.status-ok   { background: var(--green-ok);  box-shadow: 0 0 6px var(--green-ok); }
.status-err  { background: var(--red-err);   box-shadow: 0 0 6px var(--red-err); }
.status-idle { background: var(--text-muted); }
.status-testing { background: var(--amber-warn); box-shadow: 0 0 6px var(--amber-warn); animation: pulse 1s infinite; }

@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }

.stTextInput > div > div > input,
.stTextArea > div > div > textarea {
    background: var(--bg-card) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    color: var(--text-primary) !important;
    font-family: 'Space Mono', monospace !important;
    font-size: 0.78rem !important;
}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {
    border-color: var(--purple-mid) !important;
    box-shadow: 0 0 0 2px rgba(107,63,197,0.2) !important;
}
.stTextInput > label, .stTextArea > label, .stSelectbox > label,
.stMultiSelect > label, .stNumberInput > label, .stCheckbox > label span {
    font-family: 'Space Mono', monospace !important;
    font-size: 0.68rem !important;
    letter-spacing: 1.5px !important;
    color: var(--text-secondary) !important;
    text-transform: uppercase !important;
}

.stButton > button {
    background: linear-gradient(135deg, #6c3fc5, #4f2d9e) !important;
    color: #fff !important;
    border: none !important;
    border-radius: 8px !important;
    font-family: 'Rajdhani', sans-serif !important;
    font-size: 0.95rem !important;
    font-weight: 600 !important;
    letter-spacing: 2px !important;
    padding: 0.5rem 1.2rem !important;
    transition: all 0.2s !important;
    text-transform: uppercase !important;
}
.stButton > button:hover {
    background: linear-gradient(135deg, #7d4fd4, #6032bb) !important;
    box-shadow: 0 0 20px rgba(107,63,197,0.5) !important;
    transform: translateY(-1px) !important;
}

.stSelectbox > div > div,
.stMultiSelect > div > div {
    background: var(--bg-card) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    color: var(--text-primary) !important;
}

.stNumberInput > div > div > input {
    background: var(--bg-card) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    color: var(--text-primary) !important;
    font-family: 'Space Mono', monospace !important;
}

.stTabs [data-baseweb="tab-list"] {
    background: var(--bg-panel) !important;
    border-radius: 10px 10px 0 0 !important;
    border-bottom: 1px solid var(--border) !important;
    gap: 0 !important;
}
.stTabs [data-baseweb="tab"] {
    font-family: 'Rajdhani', sans-serif !important;
    font-size: 0.9rem !important;
    font-weight: 600 !important;
    letter-spacing: 2px !important;
    color: var(--text-muted) !important;
    text-transform: uppercase !important;
    padding: 0.6rem 1.4rem !important;
    border-radius: 8px 8px 0 0 !important;
    background: transparent !important;
    border: none !important;
}
.stTabs [aria-selected="true"] {
    color: var(--purple-bright) !important;
    background: linear-gradient(180deg, rgba(107,63,197,0.12), transparent) !important;
    border-bottom: 2px solid var(--purple-bright) !important;
}

.stProgress > div > div > div {
    background: linear-gradient(90deg, var(--purple-mid), var(--cyan-accent)) !important;
    border-radius: 4px !important;
}

.stAlert {
    border-radius: 8px !important;
    border-left: 3px solid !important;
    background: var(--bg-card) !important;
}

.streamlit-expanderHeader {
    background: var(--bg-card) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    font-family: 'Rajdhani', sans-serif !important;
    font-weight: 600 !important;
    letter-spacing: 1px !important;
    color: var(--text-secondary) !important;
}

.evo-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.2rem 1.4rem;
    margin-bottom: 1rem;
    position: relative;
    overflow: hidden;
    transition: border-color 0.2s, box-shadow 0.2s;
}
.evo-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, var(--purple-mid), var(--cyan-accent));
    opacity: 0.6;
}
.evo-card:hover {
    border-color: var(--border-glow);
    box-shadow: 0 0 24px rgba(107,63,197,0.12);
}

.evo-card-title {
    font-family: 'Rajdhani', sans-serif;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 3px;
    color: var(--purple-bright);
    text-transform: uppercase;
    margin-bottom: 0.6rem;
}

.metric-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 0.8rem;
    margin-bottom: 1.2rem;
}
.metric-tile {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1rem;
    text-align: center;
    transition: all 0.2s;
    position: relative;
    overflow: hidden;
}
.metric-tile::after {
    content: '';
    position: absolute;
    bottom: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, var(--purple-mid), var(--cyan-accent));
    transform: scaleX(0);
    transform-origin: left;
    transition: transform 0.3s;
}
.metric-tile:hover::after { transform: scaleX(1); }
.metric-tile:hover { border-color: var(--purple-mid); }

.metric-score {
    font-family: 'Rajdhani', sans-serif;
    font-size: 2.2rem;
    font-weight: 700;
    line-height: 1;
}
.score-pass { color: var(--green-ok); }
.score-warn { color: var(--amber-warn); }
.score-fail { color: var(--red-err); }

.metric-name {
    font-family: 'Space Mono', monospace;
    font-size: 0.6rem;
    letter-spacing: 1.5px;
    color: var(--text-muted);
    margin-top: 0.3rem;
    text-transform: uppercase;
}
.metric-threshold {
    font-size: 0.65rem;
    color: var(--text-muted);
    margin-top: 0.2rem;
}

.log-console {
    background: #050810;
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1rem 1.2rem;
    font-family: 'Space Mono', monospace;
    font-size: 0.72rem;
    line-height: 1.7;
    color: #7c9ab8;
    max-height: 300px;
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-all;
}
.log-ok   { color: var(--green-ok); }
.log-err  { color: var(--red-err); }
.log-info { color: var(--cyan-accent); }
.log-warn { color: var(--amber-warn); }

.page-title {
    font-family: 'Rajdhani', sans-serif;
    font-size: 2rem;
    font-weight: 700;
    letter-spacing: 4px;
    color: var(--text-primary);
    text-transform: uppercase;
    margin-bottom: 0.1rem;
}
.page-tagline {
    font-family: 'Space Mono', monospace;
    font-size: 0.62rem;
    letter-spacing: 2.5px;
    color: var(--text-muted);
    margin-bottom: 1.5rem;
}

.tc-row {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 0.9rem 1.1rem;
    margin-bottom: 0.5rem;
    transition: border-color 0.2s;
}
.tc-row:hover { border-color: var(--purple-mid); }
.tc-question {
    font-family: 'Inter', sans-serif;
    font-size: 0.85rem;
    color: var(--text-primary);
    margin-bottom: 0.5rem;
}
.tc-answer {
    font-family: 'Inter', sans-serif;
    font-size: 0.78rem;
    color: var(--text-secondary);
    padding: 0.5rem 0.8rem;
    background: #080b14;
    border-left: 2px solid var(--purple-mid);
    border-radius: 0 6px 6px 0;
}
.badge {
    display: inline-block;
    font-family: 'Space Mono', monospace;
    font-size: 0.58rem;
    letter-spacing: 1px;
    padding: 2px 8px;
    border-radius: 4px;
    margin-right: 4px;
    margin-bottom: 4px;
}
.badge-pass { background: rgba(16,185,129,0.15); color: var(--green-ok); border: 1px solid rgba(16,185,129,0.3); }
.badge-fail { background: rgba(239,68,68,0.15);  color: var(--red-err);  border: 1px solid rgba(239,68,68,0.3); }

[data-testid="stFileUploader"] {
    background: var(--bg-card) !important;
    border: 1px dashed var(--border-glow) !important;
    border-radius: 10px !important;
    padding: 0.5rem !important;
}
[data-testid="stFileUploader"]:hover {
    border-color: var(--purple-bright) !important;
    box-shadow: 0 0 16px rgba(107,63,197,0.15) !important;
}

::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: var(--bg-base); }
::-webkit-scrollbar-thumb { background: var(--border-glow); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--purple-mid); }

footer { visibility: hidden; }
.block-container { padding-top: 2rem !important; padding-bottom: 2rem !important; }
</style>
""", unsafe_allow_html=True)


def _init():
    defaults = dict(
        supabase_status="idle",
        openai_status="idle",
        confident_status="idle",
        supabase_url="",
        supabase_key="",
        supabase_table="documents_pg",
        openai_key="",
        openai_model="gpt-4o-mini",
        confident_key="",
        webhook_url="",
        logs=[],
        eval_results=[],
        goldens=[],
        running=False,
        run_complete=False,
        n8n_active=False,
        target_qa=5,
        max_chunks=10,
        dataset_alias="RAG_Eval",
    )
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init()

def add_log(msg: str, kind="info"):
    ts = datetime.now().strftime("%H:%M:%S")
    st.session_state.logs.append((ts, kind, msg))

def status_dot(status: str) -> str:
    cls = {"ok": "status-ok", "err": "status-err", "idle": "status-idle", "testing": "status-testing"}.get(status, "status-idle")
    return f'<span class="status-dot {cls}"></span>'

with st.sidebar:
    st.markdown('<div class="evo-logo">E·V·O</div>', unsafe_allow_html=True)
    st.markdown('<div class="evo-subtitle">Evaluate Verify Optimize</div>', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)

    st.markdown('<div class="sidebar-section-label">⬡ Supabase</div>', unsafe_allow_html=True)
    st.session_state.supabase_url   = st.text_input("PROJECT URL", value=st.session_state.supabase_url, type="default", placeholder="https://xyz.supabase.co")
    st.session_state.supabase_key   = st.text_input("ANON KEY",    value=st.session_state.supabase_key,   type="password", placeholder="eyJ...")
    st.session_state.supabase_table = st.text_input("TABLE NAME",  value=st.session_state.supabase_table,  placeholder="documents_pg")

    col_sb, _ = st.columns([1, 1])
    with col_sb:
        if st.button("TEST", key="test_sb"):
            st.session_state.supabase_status = "testing"
            try:
                c = create_client(st.session_state.supabase_url, st.session_state.supabase_key)
                c.table(st.session_state.supabase_table).select("id").limit(1).execute()
                st.session_state.supabase_status = "ok"
                add_log("Supabase connection OK", "ok")
            except Exception as e:
                st.session_state.supabase_status = "err"
                add_log(f"Supabase error: {e}", "err")
            st.rerun()

    sb_label = {"ok":"CONNECTED","err":"FAILED","idle":"NOT TESTED","testing":"TESTING..."}[st.session_state.supabase_status]
    st.markdown(
        f'<div class="conn-row"><span class="conn-label">{sb_label}</span>{status_dot(st.session_state.supabase_status)}</div>',
        unsafe_allow_html=True
    )

    st.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)

    st.markdown('<div class="sidebar-section-label">⬡ OpenAI Model</div>', unsafe_allow_html=True)
    st.session_state.openai_key   = st.text_input("API KEY",  value=st.session_state.openai_key, type="password", placeholder="sk-...")
    st.session_state.openai_model = st.selectbox("MODEL", ["gpt-4o-mini","gpt-4o","gpt-4-turbo","gpt-3.5-turbo"],
                                                  index=["gpt-4o-mini","gpt-4o","gpt-4-turbo","gpt-3.5-turbo"].index(st.session_state.openai_model))
    col_oa, _ = st.columns([1, 1])
    with col_oa:
        if st.button("TEST", key="test_oa"):
            st.session_state.openai_status = "testing"
            try:
                import openai as _oa
                client = _oa.OpenAI(api_key=st.session_state.openai_key)
                client.models.list()
                st.session_state.openai_status = "ok"
                add_log("OpenAI connection OK", "ok")
            except Exception as e:
                st.session_state.openai_status = "err"
                add_log(f"OpenAI error: {e}", "err")
            st.rerun()

    oa_label = {"ok":"CONNECTED","err":"FAILED","idle":"NOT TESTED","testing":"TESTING..."}[st.session_state.openai_status]
    st.markdown(
        f'<div class="conn-row"><span class="conn-label">{oa_label}</span>{status_dot(st.session_state.openai_status)}</div>',
        unsafe_allow_html=True
    )

    st.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)

    st.markdown('<div class="sidebar-section-label">⬡ Confident AI</div>', unsafe_allow_html=True)
    st.session_state.confident_key = st.text_input("API KEY", value=st.session_state.confident_key, type="password", placeholder="conf-...")
    col_ca, _ = st.columns([1, 1])
    with col_ca:
        if st.button("TEST", key="test_ca"):
            st.session_state.confident_status = "testing"
            try:
                import deepeval
                deepeval.login(st.session_state.confident_key)
                st.session_state.confident_status = "ok"
                add_log("Confident AI login OK", "ok")
            except Exception as e:
                st.session_state.confident_status = "err"
                add_log(f"Confident AI error: {e}", "err")
            st.rerun()

    ca_label = {"ok":"CONNECTED","err":"FAILED","idle":"NOT TESTED","testing":"TESTING..."}[st.session_state.confident_status]
    st.markdown(
        f'<div class="conn-row"><span class="conn-label">{ca_label}</span>{status_dot(st.session_state.confident_status)}</div>',
        unsafe_allow_html=True
    )

    st.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)

    st.markdown('<div class="sidebar-section-label">⬡ n8n RAG Webhook</div>', unsafe_allow_html=True)
    st.session_state.webhook_url = st.text_input("WEBHOOK URL", value=st.session_state.webhook_url, placeholder="https://…/webhook/…")
    col_wh, _ = st.columns([1, 1])
    with col_wh:
        if st.button("PING", key="ping_wh"):
            try:
                r = requests.post(st.session_state.webhook_url, json={"question": "ping"}, timeout=10)
                if r.status_code < 400:
                    st.session_state.n8n_active = True
                    add_log("n8n webhook reachable", "ok")
                else:
                    st.session_state.n8n_active = False
                    add_log(f"n8n returned {r.status_code}", "warn")
            except Exception as e:
                st.session_state.n8n_active = False
                add_log(f"n8n unreachable: {e}", "err")
            st.rerun()

    n8n_dot = "ok" if st.session_state.n8n_active else "idle"
    n8n_txt = "REACHABLE" if st.session_state.n8n_active else "NOT TESTED"
    st.markdown(
        f'<div class="conn-row"><span class="conn-label">{n8n_txt}</span>{status_dot(n8n_dot)}</div>',
        unsafe_allow_html=True
    )


st.markdown('<div class="page-title">LLM Evaluation Suite</div>', unsafe_allow_html=True)

tab_modify, tab_upload, tab_eval, tab_results, tab_logs = st.tabs([
    "  MODIFY GOLDENS",
    "  UPLOAD DOCS",
    "  RUN EVALUATION",
    "  RESULTS",
    "  CONSOLE",
])

# Modify Goldens Tab
with tab_modify:
    st.markdown('<div class="evo-card"><div class="evo-card-title">Modify Goldens and Auto-Push to Confident AI</div>', unsafe_allow_html=True)
    st.markdown("Edit generated Q&A pairs and automatically sync changes to Confident AI cloud.")
    st.markdown('</div>', unsafe_allow_html=True)
    
    if st.session_state.goldens:
        st.markdown("### Select Golden to Modify")
        
        docs_available = list(set(g["doc"] for g in st.session_state.goldens))
        filter_doc_modify = st.selectbox("Filter by document", ["All"] + docs_available, key="modify_doc_filter")
        
        display_goldens = st.session_state.goldens if filter_doc_modify == "All" else [g for g in st.session_state.goldens if g["doc"] == filter_doc_modify]
        
        golden_options = [f"Q{i+1}: {g['question'][:80]}..." for i, g in enumerate(display_goldens)]
        selected_golden_idx = st.selectbox("Select golden to edit", range(len(golden_options)), format_func=lambda x: golden_options[x])
        
        if selected_golden_idx is not None:
            selected_golden = display_goldens[selected_golden_idx]
            
            st.markdown("---")
            st.markdown("### Edit Golden")
            
            new_question = st.text_area("Question", value=selected_golden["question"], height=100)
            new_expected = st.text_area("Expected Answer", value=selected_golden["expected"], height=150)
            
            st.markdown("**Context (read-only):**")
            st.code(selected_golden["context"][0][:500] if selected_golden["context"] else "No context", language="text")
            
            col_save, col_cancel = st.columns(2)
            with col_save:
                if st.button("Save Changes", type="primary"):
                    selected_golden["question"] = new_question
                    selected_golden["expected"] = new_expected
                    
                    for i, g in enumerate(st.session_state.goldens):
                        if g["doc"] == selected_golden["doc"] and g["question"] == golden_options[selected_golden_idx].split(": ")[1].replace("...", ""):
                            st.session_state.goldens[i] = selected_golden
                            break
                    
                    with st.spinner("Pushing goldens to Confident AI..."):
                        from RAG_DeepEval import sync_modified_goldens_to_cloud, login_confident_ai
                        
                        cloud_ready_goldens = []
                        for g in st.session_state.goldens:
                            from deepeval.golden import Golden
                            golden = Golden(
                                input=g["question"],
                                expected_output=g["expected"],
                                context=g["context"] if g["context"] else []
                            )
                            cloud_ready_goldens.append(golden)
                        
                        alias = st.session_state.dataset_alias
                        if st.session_state.confident_key:
                            login_confident_ai()
                            success = sync_modified_goldens_to_cloud(cloud_ready_goldens, alias, auto_push=True)
                            
                            if success:
                                st.success(f"Golden modified and auto-pushed to Confident AI (alias: {alias})")
                                add_log(f"Modified golden and auto-pushed to Confident AI: {new_question[:50]}...", "ok")
                            else:
                                st.error("Failed to push to Confident AI")
                                add_log("Failed to auto-push modified goldens to Confident AI", "err")
                        else:
                            st.warning("Confident AI API key not configured. Changes saved locally only.")
                            add_log("Confident AI key missing - golden saved locally only", "warn")
                    
                    st.rerun()
            
            with col_cancel:
                if st.button("Cancel"):
                    st.rerun()
        
        st.markdown("---")
        
        st.markdown("### Batch Operations")
        col_batch1, col_batch2 = st.columns(2)
        
        with col_batch1:
            if st.button("Push ALL Goldens to Confident AI (Overwrite)"):
                with st.spinner("Pushing all goldens to Confident AI..."):
                    from RAG_DeepEval import sync_modified_goldens_to_cloud, login_confident_ai
                    
                    cloud_ready_goldens = []
                    for g in st.session_state.goldens:
                        from deepeval.golden import Golden
                        golden = Golden(
                            input=g["question"],
                            expected_output=g["expected"],
                            context=g["context"] if g["context"] else []
                        )
                        cloud_ready_goldens.append(golden)
                    
                    alias = st.session_state.dataset_alias
                    if st.session_state.confident_key:
                        login_confident_ai()
                        success = sync_modified_goldens_to_cloud(cloud_ready_goldens, alias, auto_push=True)
                        
                        if success:
                            st.success(f"Pushed {len(cloud_ready_goldens)} goldens to Confident AI")
                            add_log(f"Batch pushed {len(cloud_ready_goldens)} goldens to Confident AI", "ok")
                        else:
                            st.error("Failed to push goldens")
                            add_log("Batch push failed", "err")
                    else:
                        st.warning("Confident AI API key not configured")
        
        with col_batch2:
            if st.button("Pull Latest from Confident AI"):
                with st.spinner("Pulling goldens from Confident AI..."):
                    from RAG_DeepEval import pull_dataset_from_cloud, login_confident_ai
                    
                    alias = st.session_state.dataset_alias
                    if st.session_state.confident_key:
                        login_confident_ai()
                        dataset = pull_dataset_from_cloud(alias)
                        
                        if dataset and dataset.goldens:
                            st.session_state.goldens = []
                            for golden in dataset.goldens:
                                st.session_state.goldens.append({
                                    "doc": filter_doc_modify if filter_doc_modify != "All" else "unknown",
                                    "question": golden.input,
                                    "expected": golden.expected_output,
                                    "actual": "",
                                    "context": golden.context if golden.context else []
                                })
                            st.success(f"Pulled {len(st.session_state.goldens)} goldens from Confident AI")
                            add_log(f"Pulled {len(st.session_state.goldens)} goldens from Confident AI", "ok")
                            st.rerun()
                        else:
                            st.warning("No goldens found in cloud")
                            add_log("Pull from Confident AI returned no data", "warn")
                    else:
                        st.warning("Confident AI API key not configured")
    
    else:
        st.info("No goldens found. Run an evaluation first to generate Q&A pairs.")

# Tab 1: Upload documents
with tab_upload:
    st.markdown('<div class="evo-card"><div class="evo-card-title">Document Ingestion</div>', unsafe_allow_html=True)
    st.markdown("Upload documents to be chunked and stored in Supabase for evaluation.")
    st.markdown('</div>', unsafe_allow_html=True)

    uploaded = st.file_uploader(
        "DROP FILES HERE",
        type=["pdf","docx","txt","csv","xlsx"],
        accept_multiple_files=True,
        help="Supported: .pdf .docx .txt .csv .xlsx"
    )

    col_ci, col_co = st.columns(2)
    with col_ci:
        chunk_size = st.number_input("CHUNK SIZE (words)", min_value=100, max_value=5000, value=1000, step=100)
    with col_co:
        chunk_overlap = st.number_input("CHUNK OVERLAP (words)", min_value=0, max_value=500, value=200, step=50)

    if st.button("UPLOAD AND CHUNK DOCUMENTS", disabled=not uploaded):
        if not st.session_state.supabase_url or not st.session_state.supabase_key:
            st.error("Configure Supabase credentials in the sidebar first.")
        else:
            import uuid, tempfile
            from supabase import create_client
            try:
                import PyPDF2
                from docx import Document as DocxDoc
                import pandas as pd
            except ImportError as ie:
                st.error(f"Missing dependency: {ie}")
                st.stop()

            sb_client = create_client(st.session_state.supabase_url, st.session_state.supabase_key)
            progress = st.progress(0)
            status_txt = st.empty()

            for idx, uf in enumerate(uploaded):
                file_name = uf.name
                status_txt.markdown(f"Processing **{file_name}**…")
                add_log(f"Reading {file_name}", "info")

                with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_name)[1]) as tmp:
                    tmp.write(uf.getvalue())
                    tmp_path = tmp.name

                ext = os.path.splitext(file_name)[1].lower()
                text = ""
                try:
                    if ext == ".pdf":
                        with open(tmp_path, "rb") as f:
                            reader = PyPDF2.PdfReader(f)
                            for pn, pg in enumerate(reader.pages):
                                text += f"\n[Page {pn+1}]\n" + (pg.extract_text() or "")
                    elif ext == ".docx":
                        doc = DocxDoc(tmp_path)
                        text = "\n".join(p.text for p in doc.paragraphs if p.text)
                    elif ext == ".txt":
                        with open(tmp_path, "r", encoding="utf-8") as f:
                            text = f.read()
                    elif ext in [".csv", ".xlsx"]:
                        df = pd.read_csv(tmp_path) if ext == ".csv" else pd.read_excel(tmp_path)
                        text = df.to_string()
                except Exception as re:
                    add_log(f"Read error {file_name}: {re}", "err")
                    continue

                words = text.split()
                chunks = []
                step = max(1, chunk_size - chunk_overlap)
                for i in range(0, len(words), step):
                    cw = words[i:i+chunk_size]
                    ct = " ".join(cw)
                    if ct.strip():
                        chunks.append({
                            "text": ct,
                            "metadata": {
                                "file_title": file_name,
                                "source": "streamlit_upload",
                                "file_id": str(uuid.uuid4()),
                                "chunk_index": len(chunks),
                                "loc": {"lines": {"from": i, "to": i+len(cw)}}
                            }
                        })

                add_log(f"{file_name}: {len(chunks)} chunks created", "info")

                try:
                    existing = sb_client.table(st.session_state.supabase_table).select("id").execute()
                    add_log(f"Cleared old chunks for {file_name}", "info")
                except:
                    pass

                for ch in chunks:
                    try:
                        sb_client.table(st.session_state.supabase_table).insert({
                            "text": ch["text"],
                            "metadata": ch["metadata"]
                        }).execute()
                    except Exception as ie2:
                        add_log(f"Insert error: {ie2}", "err")
                        break

                add_log(f"Inserted {len(chunks)} chunks for {file_name}", "ok")
                progress.progress((idx + 1) / len(uploaded))

            status_txt.markdown("All documents processed.")
            st.success(f"Uploaded and chunked {len(uploaded)} file(s) into Supabase.")


METRIC_OPTS = {
    "Answer Relevancy":      {"cls": "AnswerRelevancyMetric",      "threshold": 0.4},
    "Faithfulness":          {"cls": "FaithfulnessMetric",         "threshold": 0.4},
    "Contextual Relevancy":  {"cls": "ContextualRelevancyMetric",  "threshold": 0.5},
    "Hallucination":         {"cls": "HallucinationMetric",        "threshold": 0.3},
    "Contextual Precision":  {"cls": "ContextualPrecisionMetric",  "threshold": 0.5},
    "Contextual Recall":     {"cls": "ContextualRecallMetric",     "threshold": 0.5},
    "Bias":                  {"cls": "BiasMetric",                 "threshold": 0.5},
    "Toxicity":              {"cls": "ToxicityMetric",             "threshold": 0.5},
}

with tab_eval:
    st.markdown('<div class="evo-card"><div class="evo-card-title">Evaluation Configuration</div>', unsafe_allow_html=True)
    st.markdown("Select metrics, configure parameters, then fire the evaluation.")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("**SELECT METRICS TO EVALUATE**")
    cols_m = st.columns(4)
    selected_metrics = []
    for i, (m_name, _) in enumerate(METRIC_OPTS.items()):
        default_on = m_name in ["Answer Relevancy", "Faithfulness", "Contextual Relevancy", "Hallucination"]
        with cols_m[i % 4]:
            if st.checkbox(m_name, value=default_on, key=f"metric_{m_name}"):
                selected_metrics.append(m_name)

    st.markdown("---")
    col_e1, col_e2, col_e3 = st.columns(3)
    with col_e1:
        st.session_state.target_qa = st.number_input("TARGET Q&A PAIRS / DOC", min_value=1, max_value=50, value=st.session_state.target_qa)
    with col_e2:
        st.session_state.max_chunks = st.number_input("MAX CHUNKS / DOC", min_value=1, max_value=100, value=st.session_state.max_chunks)
    with col_e3:
        st.session_state.dataset_alias = st.text_input("DATASET ALIAS", value=st.session_state.dataset_alias)

    cloud_push = st.checkbox("Push dataset to Confident AI cloud", value=True)

    st.markdown("---")

    ready = (
        st.session_state.supabase_url and
        st.session_state.supabase_key and
        st.session_state.openai_key and
        st.session_state.webhook_url and
        len(selected_metrics) > 0
    )
    if not ready:
        missing = []
        if not st.session_state.supabase_url: missing.append("Supabase URL")
        if not st.session_state.supabase_key: missing.append("Supabase Key")
        if not st.session_state.openai_key: missing.append("OpenAI Key")
        if not st.session_state.webhook_url: missing.append("n8n Webhook URL")
        if not selected_metrics: missing.append("at least 1 metric")
        st.warning(f"Configure in sidebar before running: {', '.join(missing)}")

    if st.button("LAUNCH EVALUATION", disabled=not ready or st.session_state.running):
        st.session_state.running = True
        st.session_state.run_complete = False
        st.session_state.eval_results = []
        st.session_state.goldens = []
        st.session_state.logs = []
        st.rerun()

    if st.session_state.running:
        add_log("Starting evaluation pipeline…", "info")
        progress_bar = st.progress(0)
        status_area = st.empty()

        try:
            class _OAModel(DeepEvalBaseLLM):
                def __init__(self):
                    self.model_name = st.session_state.openai_model
                    _oa.api_key = st.session_state.openai_key
                    self.client = _oa.OpenAI(api_key=st.session_state.openai_key)
                def load_model(self): return self.client
                def generate(self, prompt):
                    try:
                        r = self.client.chat.completions.create(
                            model=self.model_name,
                            messages=[{"role":"user","content":prompt}],
                            temperature=0.7
                        )
                        return r.choices[0].message.content or ""
                    except Exception as e:
                        return ""
                async def a_generate(self, prompt):
                    import asyncio
                    return await asyncio.to_thread(self.generate, prompt)
                def get_model_name(self): return self.model_name

            oai_model = _OAModel()

            if cloud_push and st.session_state.confident_key:
                try:
                    deepeval.login(st.session_state.confident_key)
                    add_log("Confident AI authenticated", "ok")
                except Exception as ce:
                    add_log(f"Confident AI login failed: {ce}", "warn")

            sb = _sc(st.session_state.supabase_url, st.session_state.supabase_key)
            status_area.info("Scanning Supabase for documents…")

            resp = sb.table(st.session_state.supabase_table).select("metadata").execute()
            doc_set = set()
            for row in resp.data:
                ft = row.get("metadata", {}).get("file_title")
                if ft: doc_set.add(ft)
            documents = sorted(doc_set)

            if not documents:
                add_log("No documents found in Supabase!", "err")
                st.session_state.running = False
                st.rerun()

            add_log(f"Found {len(documents)} document(s): {', '.join(documents)}", "info")

            METRIC_MAP = {
                "Answer Relevancy":     lambda m: AnswerRelevancyMetric(model=m, threshold=0.4, include_reason=True),
                "Faithfulness":         lambda m: FaithfulnessMetric(model=m, threshold=0.4, include_reason=True),
                "Contextual Relevancy": lambda m: ContextualRelevancyMetric(model=m, threshold=0.5, include_reason=True),
                "Hallucination":        lambda m: HallucinationMetric(model=m, threshold=0.3, include_reason=True),
                "Contextual Precision": lambda m: ContextualPrecisionMetric(model=m, threshold=0.5, include_reason=True),
                "Contextual Recall":    lambda m: ContextualRecallMetric(model=m, threshold=0.5, include_reason=True),
                "Bias":                 lambda m: BiasMetric(model=m, threshold=0.5, include_reason=True),
                "Toxicity":             lambda m: ToxicityMetric(model=m, threshold=0.5, include_reason=True),
            }
            metrics_list = [METRIC_MAP[n](oai_model) for n in selected_metrics if n in METRIC_MAP]

            def call_rag(question: str) -> str:
                try:
                    time.sleep(1)
                    r = requests.post(st.session_state.webhook_url, json={"question": question}, timeout=60)
                    if not r.text: return ""
                    data = r.json()
                    if isinstance(data, list) and data:
                        return data[0].get("output", "")
                    return str(data)
                except Exception:
                    return ""

            all_eval_results = []
            synthesizer = Synthesizer(model=oai_model)

            for doc_idx, doc_name in enumerate(documents):
                add_log(f"Processing: {doc_name}", "info")
                status_area.info(f"Processing document {doc_idx+1}/{len(documents)}: {doc_name}")

                all_rows = sb.table(st.session_state.supabase_table).select("id,text,metadata").execute()
                chunks = [r for r in all_rows.data if r.get("metadata", {}).get("file_title") == doc_name]
                chunks = chunks[:st.session_state.max_chunks]

                if not chunks:
                    add_log(f"No chunks for {doc_name}, skipping", "warn")
                    continue

                chunk_texts = [c.get("text","") for c in chunks]

                add_log(f"Synthesizing {st.session_state.target_qa} Q&A pairs from {len(chunks)} chunks…", "info")

                contexts = [[t] for t in chunk_texts]
                max_per = max(1, st.session_state.target_qa // len(chunk_texts))
                goldens = synthesizer.generate_goldens_from_contexts(
                    contexts=contexts,
                    max_goldens_per_context=max_per,
                    include_expected_output=True
                )
                add_log(f"Generated {len(goldens)} goldens for {doc_name}", "ok")

                test_cases = []
                for g in goldens:
                    question = g.input
                    expected = g.expected_output
                    context  = g.context if isinstance(g.context, list) else ([g.context] if g.context else [])
                    actual   = call_rag(question)
                    tc = LLMTestCase(
                        input=question,
                        actual_output=actual,
                        expected_output=expected,
                        retrieval_context=context,
                        context=context
                    )
                    test_cases.append(tc)
                    st.session_state.goldens.append({
                        "doc": doc_name,
                        "question": question,
                        "expected": expected,
                        "actual": actual,
                        "context": context
                    })

                add_log(f"Running metrics on {len(test_cases)} test cases…", "info")

                eval_result = de_evaluate(test_cases=test_cases, metrics=metrics_list)

                doc_scores = {"doc": doc_name, "metrics": {}, "test_cases": len(test_cases)}
                for tc in test_cases:
                    if hasattr(tc, "metrics_metadata") and tc.metrics_metadata:
                        for mname, mdata in tc.metrics_metadata.items():
                            clean = mname.replace("Metric", "")
                            if clean not in doc_scores["metrics"]:
                                doc_scores["metrics"][clean] = []
                            score = mdata.get("score") if isinstance(mdata, dict) else getattr(mdata, "score", None)
                            if score is not None:
                                doc_scores["metrics"][clean].append(score)
                    else:
                        for metric in metrics_list:
                            clean = type(metric).__name__.replace("Metric", "")
                            if clean not in doc_scores["metrics"]:
                                doc_scores["metrics"][clean] = []
                            if hasattr(metric, "score") and metric.score is not None:
                                doc_scores["metrics"][clean].append(metric.score)

                all_eval_results.append(doc_scores)
                add_log(f"Evaluation complete for {doc_name}", "ok")
                progress_bar.progress((doc_idx + 1) / len(documents))

            st.session_state.eval_results = all_eval_results
            st.session_state.running = False
            st.session_state.run_complete = True
            add_log("Full evaluation pipeline complete!", "ok")

        except Exception as ex:
            add_log(f"Pipeline error: {ex}", "err")
            st.session_state.running = False

        st.rerun()

    if st.session_state.run_complete:
        st.success("Evaluation complete — see the RESULTS tab.")


with tab_results:
    if not st.session_state.eval_results and not st.session_state.goldens:
        st.markdown(
            '<div class="evo-card" style="text-align:center; padding: 3rem;">'
            '<div class="evo-card-title" style="font-size:1.2rem; margin-bottom:0.5rem;">No results yet</div>'
            '<span style="color:var(--text-muted); font-size:0.85rem;">Run an evaluation first to see results here.</span>'
            '</div>',
            unsafe_allow_html=True
        )
    else:
        for doc_result in st.session_state.eval_results:
            doc_name = doc_result["doc"]
            st.markdown(f'<div class="evo-card"><div class="evo-card-title">Document: {doc_name}</div>', unsafe_allow_html=True)
            st.markdown(f"**{doc_result['test_cases']} test cases evaluated**")

            tiles_html = '<div class="metric-grid">'
            for mname, scores in doc_result["metrics"].items():
                if scores:
                    avg = sum(scores) / len(scores)
                    threshold = METRIC_OPTS.get(mname, {}).get("threshold", 0.5)
                    if avg >= threshold * 1.2:
                        cls = "score-pass"
                    elif avg >= threshold:
                        cls = "score-warn"
                    else:
                        cls = "score-fail"

                    tiles_html += f"""
                    <div class="metric-tile">
                        <div class="metric-score {cls}">{avg:.2f}</div>
                        <div class="metric-name">{mname}</div>
                        <div class="metric-threshold">threshold >= {threshold}</div>
                    </div>"""

            tiles_html += '</div>'
            st.markdown(tiles_html, unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

        if st.session_state.goldens:
            st.markdown("---")
            st.markdown("### Generated Q&A Test Cases")
            docs_available = list(set(g["doc"] for g in st.session_state.goldens))
            filter_doc = st.selectbox("Filter by document", ["All"] + docs_available, key="results_doc_filter")

            show_goldens = st.session_state.goldens if filter_doc == "All" else [g for g in st.session_state.goldens if g["doc"] == filter_doc]

            for i, g in enumerate(show_goldens[:50]):
                with st.expander(f"Q{i+1}: {g['question'][:90]}..."):
                    st.markdown(f"**Expected:** {g['expected']}")
                    st.markdown(f"**RAG Response:** {g['actual'] or '*No response*'}")
                    if g["context"]:
                        st.markdown(f"**Context:** {g['context'][0][:300]}...")

        if st.session_state.goldens:
            export_data = json.dumps(st.session_state.goldens, indent=2, ensure_ascii=False)
            st.download_button(
                "EXPORT Q&A JSON",
                data=export_data,
                file_name=f"evo_eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json"
            )


with tab_logs:
    col_refresh, col_clear, _ = st.columns([1, 1, 5])
    with col_refresh:
        if st.button("REFRESH"): st.rerun()
    with col_clear:
        if st.button("CLEAR"):
            st.session_state.logs = []
            st.rerun()

    KIND_CSS = {"ok":"log-ok","err":"log-err","info":"log-info","warn":"log-warn"}
    log_html = '<div class="log-console">'
    if not st.session_state.logs:
        log_html += '<span style="color:var(--text-muted)">— no output yet —</span>'
    else:
        for ts, kind, msg in st.session_state.logs:
            cls = KIND_CSS.get(kind, "")
            log_html += f'<span style="color:var(--text-muted)">[{ts}]</span> <span class="{cls}">{msg}</span>\n'
    log_html += '</div>'
    st.markdown(log_html, unsafe_allow_html=True)