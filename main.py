import os
import time
import requests

from processDocuments import DocumentProcessor
from processDocuments import SupabaseChunkLoader
from RAG_DeepEval import generate_goldens_with_synthesizer, OpenAIModel
from RAG_DeepEval import SupabaseChunkReader, SUPABASE_KEY, SUPABASE_TABLE, SUPABASE_URL
from RAG_DeepEval import TARGET_QA_PAIRS, OUTPUT_DIR
from RAG_DeepEval import login_confident_ai, push_goldens_to_cloud, pull_dataset_from_cloud 
from RAG_DeepEval import save_goldens_to_json, DATASET_ALIAS, EvaluationDataset, build_test_cases, run_evaluation, create_pdf_report
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

def upload_documents():
    print("\n Enter document paths (comma-separated):")
    print("   Supported: .pdf, .docx, .txt, .csv, .xlsx")
    paths_input = input("> ").strip()
    
    file_paths = [p.strip() for p in paths_input.split(',') if p.strip()]
    
    if not file_paths:
        print("No files specified")
        return False
    
    print("\n" + "="*60)
    print("DOCUMENT PROCESSING & UPLOAD")
    print("="*60)
    
    processor = DocumentProcessor()
    loader = SupabaseChunkLoader(SUPABASE_URL, SUPABASE_KEY, SUPABASE_TABLE)
    
    for file_path in file_paths:
        file_name = os.path.basename(file_path)
        print(f"\n Processing: {file_name}")
        
        try:
            text = processor.read_file(file_path)
            print(f"   Read {len(text)} characters")
            
            loader.clear_document_chunks(file_name)
            
            chunks = processor.chunk_text(text, file_name)
            print(f"   Created {len(chunks)} chunks")
            
            loader.insert_chunks(chunks)
            
        except Exception as e:
            print(f" Error processing {file_name}: {e}")
    
    return True

def run_evaluation_only():
    max_chunks = 10
    
    print("="*60)
    print("DEEPEVAL SYNTHESIZER + EVALUATION - SUPABASE INTEGRATION")
    print("="*60)
    
    cloud_enabled = login_confident_ai()
    
    print("\n Initializing models and clients...")
    openai_model = OpenAIModel()
    supabase = SupabaseChunkReader(SUPABASE_URL, SUPABASE_KEY, SUPABASE_TABLE)
    
    print("\n Scanning Supabase...")
    documents = supabase.get_all_documents()
    
    if not documents:
        print("\n  No documents found! Check table name, data, and credentials.")
        return
    
    all_results = {}
    
    for doc_name in documents:
        print(f"\n{'='*60}")
        print(f"PROCESSING: {doc_name}")
        print('='*60)
        
        chunks = supabase.get_chunks_by_document(doc_name)
        if not chunks:
            print(f"  No chunks found, skipping...")
            continue
        
        chunk_texts, chunk_metadata = supabase.extract_chunk_data(chunks)
        if not chunk_texts:
            print(f"  No text extracted, skipping...")
            continue
        
        chunks_to_use = chunks[:max_chunks]
        texts_to_use = chunk_texts[:max_chunks]
        metadata_to_use = chunk_metadata[:max_chunks]
        
        print(f"  Using {len(texts_to_use)} chunks")
        
        golden_data, raw_goldens = generate_goldens_with_synthesizer(
            chunks_to_use,
            texts_to_use,
            metadata_to_use,
            TARGET_QA_PAIRS,
            openai_model
        )
        
        if not golden_data:
            print(f"  No goldens generated, skipping...")
            continue
        
        json_file = save_goldens_to_json(golden_data, doc_name, OUTPUT_DIR)
        
        doc_alias = DATASET_ALIAS
        if cloud_enabled and raw_goldens:
            push_goldens_to_cloud(raw_goldens, alias=doc_alias)
        
        def call_n8n_rag(question: str) -> str:
            try:
                time.sleep(2)
                response = requests.post(
                    "https://phiwamandlakashaka.app.n8n.cloud/webhook/59b596cb-ce53-4f07-ada3-72d45ef70462",
                    json={"question": question},
                    timeout=60
                )
                
                if not response.text:
                    return ""
                
                data = response.json()
                
                if isinstance(data, dict) and data.get("code") == 404:
                    print(f"\nWebhook expired! Go to n8n and click 'Execute Workflow' again")
                    input("Press Enter after reactivating...")
                    return call_n8n_rag(question)
                
                if isinstance(data, list) and len(data) > 0:
                    return data[0].get("output", "")
                
                return str(data)
                
            except Exception:
                return ""
        
        if cloud_enabled:
            cloud_dataset = pull_dataset_from_cloud(alias=doc_alias)
        else:
            cloud_dataset = EvaluationDataset()
            for g in raw_goldens:
                cloud_dataset.add_golden(g)
        
        if cloud_dataset and cloud_dataset.goldens:
            cloud_dataset = build_test_cases(cloud_dataset, rag_fn=call_n8n_rag)
            eval_results = run_evaluation(cloud_dataset, openai_model)
        
        if golden_data:
            pdf_report = create_pdf_report(doc_name, golden_data, OUTPUT_DIR)
            print(f" PDF report saved: {pdf_report}")

        all_results[doc_name] = {
            "document": doc_name,
            "total_chunks": len(chunks),
            "chunks_used": len(chunks_to_use),
            "total_qa": len(golden_data),
            "json_file": json_file,
            "cloud_alias": doc_alias if cloud_enabled else "N/A"
        }
    
    print(f"\n{'='*60}")
    print("COMPLETE!")
    print('='*60)
    
    if all_results:
        print(f"\nSTATISTICS:")
        print(f"  Documents processed : {len(all_results)}")
        print(f"  Total Q&A pairs     : {sum(r['total_qa'] for r in all_results.values())}")
        
        for doc_name, r in all_results.items():
            print(f"\n {doc_name}:")
            print(f"  Chunks used : {r['chunks_used']}/{r['total_chunks']}")
            print(f"  Q&A pairs   : {r['total_qa']}")
            print(f"  Local file  : {r['json_file']}")

def main():
    print("\n1. Upload documents only")
    print("2. Run evaluation only")
    print("3. Upload documents then run evaluation")
    choice = input("Select option (1/2/3): ").strip()
    
    if choice == "1":
        upload_documents()
    elif choice == "2":
        run_evaluation_only()
    elif choice == "3":
        if upload_documents():
            run_evaluation_only()
    else:
        print("Invalid choice")