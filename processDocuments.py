import os
import uuid
import PyPDF2
import pandas as pd

from docx import Document
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
class DocumentProcessor:
    def __init__(self, chunk_size=1000, chunk_overlap=200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        
    def read_file(self, file_path):
        ext = Path(file_path).suffix.lower()
        
        if ext == '.pdf':
            return self._read_pdf(file_path)
        elif ext == '.docx':
            return self._read_docx(file_path)
        elif ext == '.txt':
            return self._read_txt(file_path)
        elif ext in ['.csv', '.xlsx']:
            return self._read_table(file_path)
        else:
            raise ValueError(f"Unsupported file type: {ext}")
    
    def _read_pdf(self, file_path):
        text = ""
        with open(file_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            for page_num, page in enumerate(pdf_reader.pages):
                text += f"\n[Page {page_num + 1}]\n" + page.extract_text()
        return text
    
    def _read_docx(self, file_path):
        doc = Document(file_path)
        return "\n".join([para.text for para in doc.paragraphs if para.text])
    
    def _read_txt(self, file_path):
        with open(file_path, 'r', encoding='utf-8') as file:
            return file.read()
    
    def _read_table(self, file_path):
        if file_path.endswith('.csv'):
            df = pd.read_csv(file_path)
        else:
            df = pd.read_excel(file_path)
        return df.to_string()
    
    def chunk_text(self, text, file_title):
        chunks = []
        words = text.split()
        
        for i in range(0, len(words), self.chunk_size - self.chunk_overlap):
            chunk_words = words[i:i + self.chunk_size]
            chunk_text = ' '.join(chunk_words)
            
            if chunk_text.strip():
                chunks.append({
                    'text': chunk_text,
                    'metadata': {
                        'file_title': file_title,
                        'source': 'local_file',
                        'file_id': str(uuid.uuid4()),
                        'chunk_index': len(chunks),
                        'loc': {
                            'lines': {'from': i, 'to': i + len(chunk_words)}
                        }
                    }
                })
        
        return chunks

class SupabaseChunkLoader:
    def __init__(self, url, key, table_name):
        self.client = create_client(url, key)
        self.table_name = table_name
        print(f" Supabase initialized")
        print(f"  Table: {table_name}")
    
    def insert_chunks(self, chunks):
        try:
            for chunk in chunks:
                data = {
                    'text': chunk['text'],
                    'metadata': chunk['metadata']
                }
                self.client.table(self.table_name).insert(data).execute()
            
            print(f" Inserted {len(chunks)} chunks into Supabase")
            return True
        except Exception as e:
            print(f" Error inserting chunks: {e}")
            return False
    
    def clear_document_chunks(self, file_title):
        try:
            chunks = self.client.table(self.table_name).select("id").filter('metadata->>file_title', 'eq', file_title).execute()
            for chunk in chunks.data:
                self.client.table(self.table_name).delete().eq('id', chunk['id']).execute()
            print(f" Cleared existing chunks for {file_title}")
        except Exception as e:
            print(f" Error clearing chunks: {e}")
