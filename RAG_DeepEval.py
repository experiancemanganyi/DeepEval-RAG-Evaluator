import os
import json
import deepeval
import openai

from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client, Client
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
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

load_dotenv()

SUPABASE_URL    = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY    = os.getenv("SUPABASE_KEY", "")
SUPABASE_TABLE  = os.getenv("SUPABASE_TABLE", "documents_pg")

OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL    = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

CONFIDENT_AI_API_KEY = os.getenv("CONFIDENT_AI_API_KEY", "")
DATASET_ALIAS   = os.getenv("DATASET_ALIAS", "RAG_Eval")

TARGET_QA_PAIRS = int(os.getenv("TARGET_QA_PAIRS", "5"))
OUTPUT_DIR      = os.getenv("OUTPUT_DIR", "RAG_Datasets")
os.makedirs(OUTPUT_DIR, exist_ok=True)


class OpenAIModel(deepeval.models.DeepEvalBaseLLM):
    def __init__(self, model_name: str = OPENAI_MODEL):
        self.model_name = model_name
        self.client = openai.OpenAI(api_key=OPENAI_API_KEY)

    def load_model(self):
        return self.client

    def generate(self, prompt: str) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            print(f"OpenAI error: {e}")
            return ""

    async def a_generate(self, prompt: str) -> str:
        import asyncio
        return await asyncio.to_thread(self.generate, prompt)

    def get_model_name(self) -> str:
        return self.model_name


class SupabaseChunkReader:
    def __init__(self, url: str, key: str, table_name: str):
        self.client: Client = create_client(url, key)
        self.table_name = table_name

    def get_all_documents(self) -> list:
        try:
            response = self.client.table(self.table_name).select("metadata").execute()
            documents = set()
            for row in response.data:
                file_title = row.get("metadata", {}).get("file_title")
                if file_title:
                    documents.add(file_title)
            return sorted(list(documents))
        except Exception as e:
            print(f"Error getting documents: {e}")
            return []

    def get_chunks_by_document(self, file_title: str) -> list:
        try:
            response = (
                self.client.table(self.table_name)
                .select("id, text, metadata")
                .execute()
            )
            return [
                row for row in response.data
                if row.get("metadata", {}).get("file_title") == file_title
            ]
        except Exception as e:
            print(f"Error retrieving chunks: {e}")
            return []

    def extract_chunk_data(self, chunks: list) -> tuple:
        texts, metadata_list = [], []
        for chunk in chunks:
            text = chunk.get("text", "")
            metadata = chunk.get("metadata", {})
            if text:
                texts.append(text)
                metadata_list.append({
                    "chunk_id":   chunk.get("id"),
                    "file_title": metadata.get("file_title"),
                    "source":     metadata.get("source"),
                    "file_id":    metadata.get("file_id"),
                    "lines":      metadata.get("loc", {}).get("lines", {}),
                })
        return texts, metadata_list


def login_confident_ai() -> bool:
    try:
        deepeval.login(CONFIDENT_AI_API_KEY)
        return True
    except Exception as e:
        print(f"Confident AI login failed: {e}")
        return False


def push_goldens_to_cloud(raw_goldens: list, alias: str, overwrite: bool = True) -> bool:
    if not raw_goldens:
        return False
    try:
        if overwrite:
            try:
                dataset = EvaluationDataset()
                dataset.pull(alias=alias)
                print(f"Dataset {alias} exists, will overwrite")
            except:
                pass
        
        dataset = EvaluationDataset()
        for golden in raw_goldens:
            dataset.add_golden(golden)
        dataset.push(alias=alias)
        print(f"Pushed {len(raw_goldens)} goldens to Confident AI (alias: {alias})")
        return True
    except Exception as e:
        print(f"Push failed: {e}")
        return False


def pull_dataset_from_cloud(alias: str) -> EvaluationDataset:
    try:
        dataset = EvaluationDataset()
        dataset.pull(alias=alias)
        return dataset
    except Exception as e:
        print(f"Pull failed: {e}")
        return None


def modify_golden_in_dataset(dataset: EvaluationDataset, golden_index: int, 
                              new_input: str = None, new_expected_output: str = None, 
                              new_context: list = None) -> EvaluationDataset:
    if golden_index >= len(dataset.goldens):
        raise IndexError(f"Golden index {golden_index} out of range")
    
    golden = dataset.goldens[golden_index]
    
    if new_input:
        golden.input = new_input
    if new_expected_output:
        golden.expected_output = new_expected_output
    if new_context is not None:
        golden.context = new_context
    
    return dataset


def replace_goldens_in_cloud(modified_goldens: list, alias: str, overwrite: bool = True) -> bool:
    if not modified_goldens:
        print("No goldens to push")
        return False
    
    try:
        if overwrite:
            try:
                dataset = EvaluationDataset()
                dataset.pull(alias=alias)
                print(f"Dataset {alias} exists, will overwrite")
            except:
                pass
        
        dataset = EvaluationDataset()
        for golden in modified_goldens:
            dataset.add_golden(golden)
        
        dataset.push(alias=alias)
        print(f"Successfully pushed {len(modified_goldens)} goldens to {alias}")
        return True
        
    except Exception as e:
        print(f"Failed to push modified goldens: {e}")
        return False


def sync_modified_goldens_to_cloud(modified_goldens: list, alias: str, auto_push: bool = True) -> bool:
    if not auto_push:
        print("Auto-push disabled")
        return False
    
    if not modified_goldens:
        print("No goldens to sync")
        return False
    
    try:
        if not login_confident_ai():
            print("Failed to login to Confident AI")
            return False
        
        success = replace_goldens_in_cloud(modified_goldens, alias, overwrite=True)
        
        if success:
            print(f"Auto-pushed {len(modified_goldens)} modified goldens to Confident AI (alias: {alias})")
        else:
            print("Failed to auto-push goldens to Confident AI")
        
        return success
        
    except Exception as e:
        print(f"Error syncing goldens: {e}")
        return False


def save_modified_goldens_to_json(goldens_data: list, original_file_path: str, suffix: str = "_modified") -> str:
    base, ext = os.path.splitext(original_file_path)
    new_path = f"{base}{suffix}{ext}"
    
    with open(new_path, 'w', encoding='utf-8') as f:
        json.dump(goldens_data, f, indent=2, ensure_ascii=False)
    
    print(f"Saved modified goldens to: {new_path}")
    return new_path


def generate_goldens_with_synthesizer(
    chunks: list,
    chunk_texts: list,
    chunk_metadata: list,
    num_goldens: int,
    model: OpenAIModel,
) -> tuple:
    golden_data = []
    try:
        synthesizer = Synthesizer(model=model)
        contexts = [[text] for text in chunk_texts]
        goldens = synthesizer.generate_goldens_from_contexts(
            contexts=contexts,
            max_goldens_per_context=max(1, num_goldens // len(chunk_texts)),
            include_expected_output=True,
        )

        for i, golden in enumerate(goldens):
            chunk_idx = i % len(chunks)
            original_chunk    = chunks[chunk_idx]
            original_metadata = chunk_metadata[chunk_idx]

            context = []
            if hasattr(golden, "context"):
                if isinstance(golden.context, list):
                    context = golden.context
                elif isinstance(golden.context, str):
                    context = [golden.context]

            golden_data.append({
                "question": golden.input,
                "answer":   golden.expected_output,
                "context":  context,
                "metadata": {
                    "chunk_id":          str(original_chunk.get("id")),
                    "file_title":        original_metadata.get("file_title"),
                    "source":            original_metadata.get("source"),
                    "lines":             original_metadata.get("lines"),
                    "generation_method": "deepeval_synthesizer",
                },
            })

        return golden_data, goldens

    except Exception as e:
        print(f"Synthesizer error: {e}")
        return golden_data, []


def build_test_cases(dataset: EvaluationDataset, rag_fn) -> EvaluationDataset:
    for golden in dataset.goldens:
        context = golden.context or []
        try:
            actual = rag_fn(golden.input)
        except Exception as e:
            print(f"RAG call failed: {e}")
            actual = ""

        dataset.add_test_case(LLMTestCase(
            input=golden.input,
            actual_output=actual,
            expected_output=golden.expected_output,
            retrieval_context=context,
            context=context,
        ))
    return dataset


def run_evaluation(dataset: EvaluationDataset, openai_model: OpenAIModel):
    metrics = [
        AnswerRelevancyMetric(model=openai_model,   threshold=0.4, include_reason=True),
        FaithfulnessMetric(model=openai_model,      threshold=0.4, include_reason=True),
        HallucinationMetric(model=openai_model,     threshold=0.3, include_reason=True),
        ContextualRelevancyMetric(model=openai_model, threshold=0.5, include_reason=True),
        BiasMetric(model=openai_model,              threshold=0.5, include_reason=True),
        ToxicityMetric(model=openai_model,          threshold=0.5, include_reason=True),
        ContextualPrecisionMetric(model=openai_model, threshold=0.5, include_reason=True),
        ContextualRecallMetric(model=openai_model,  threshold=0.5, include_reason=True),
    ]
    try:
        return evaluate(test_cases=dataset.test_cases, metrics=metrics)
    except Exception as e:
        print(f"Evaluation error: {e}")
        return None


def save_goldens_to_json(golden_data: list, document_name: str, output_dir: str) -> str:
    clean_name = document_name.replace(".pdf", "").replace(".txt", "").replace(" ", "_")
    doc_dir = os.path.join(output_dir, clean_name)
    os.makedirs(doc_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath  = os.path.join(doc_dir, f"{clean_name}_goldenset_{timestamp}.json")

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(golden_data, f, indent=2, ensure_ascii=False)

    summary = {
        "document":       document_name,
        "total_qa_pairs": len(golden_data),
        "generated_at":   datetime.now().isoformat(),
        "method":         "DeepEval Synthesizer",
    }
    with open(os.path.join(doc_dir, f"{clean_name}_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    return filepath


def create_pdf_report(document_name: str, qa_data: list, output_dir: str) -> str:
    pdf_path = os.path.join(output_dir, f"{document_name}_evaluation_report.pdf")
    doc    = SimpleDocTemplate(pdf_path, pagesize=letter)
    styles = getSampleStyleSheet()
    story  = [
        Paragraph(f"Evaluation Report: {document_name}", styles["Heading1"]),
        Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles["Normal"]),
        Spacer(1, 20),
        Paragraph(f"Total QandA Pairs: {len(qa_data)}", styles["Heading2"]),
        Spacer(1, 10),
    ]
    for idx, qa in enumerate(qa_data[:20], 1):
        story += [
            Paragraph(f"QandA #{idx}", styles["Heading3"]),
            Paragraph(f"Q: {qa['question']}", styles["Normal"]),
            Paragraph(f"A: {qa['answer']}", styles["Normal"]),
            Spacer(1, 10),
        ]
    doc.build(story)
    return pdf_path