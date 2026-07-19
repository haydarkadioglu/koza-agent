import os
import glob
from pathlib import Path

try:
    import chromadb
    from chromadb.config import Settings
    from pypdf import PdfReader
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False

BRAIN_DIR = os.path.expanduser("~/.koza/brain")
DB_DIR = os.path.join(BRAIN_DIR, ".vectordb")

class BrainManager:
    def __init__(self):
        if not CHROMA_AVAILABLE:
            raise RuntimeError("ChromaDB is not installed.")
        os.makedirs(BRAIN_DIR, exist_ok=True)
        os.makedirs(DB_DIR, exist_ok=True)
        
        self.client = chromadb.PersistentClient(path=DB_DIR)
        self.collection = self.client.get_or_create_collection(
            name="koza_brain",
            metadata={"hnsw:space": "cosine"}
        )

    def extract_text_from_pdf(self, file_path: str) -> str:
        text = ""
        try:
            reader = PdfReader(file_path)
            for page in reader.pages:
                text += page.extract_text() + "\n"
        except Exception as e:
            print(f"Error extracting PDF {file_path}: {e}")
        return text

    def extract_text(self, file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".pdf":
            return self.extract_text_from_pdf(file_path)
        elif ext in [".txt", ".md", ".csv", ".json", ".py", ".js", ".ts", ".html"]:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                print(f"Error extracting text from {file_path}: {e}")
        return ""

    def chunk_text(self, text: str, chunk_size=1000, overlap=200):
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunks.append(text[start:end])
            start += (chunk_size - overlap)
        return chunks

    def sync_brain_folder(self):
        """Scans the brain folder for new files and indexes them."""
        if not CHROMA_AVAILABLE:
            return "ChromaDB not available."
        
        indexed_files = set()
        results = self.collection.get(include=["metadatas"])
        if results and "metadatas" in results and results["metadatas"]:
            for meta in results["metadatas"]:
                if meta and "source" in meta:
                    indexed_files.add(meta["source"])

        new_files = 0
        for root, _, files in os.walk(BRAIN_DIR):
            if ".vectordb" in root:
                continue
            for file in files:
                file_path = os.path.join(root, file)
                if file_path in indexed_files:
                    continue
                
                text = self.extract_text(file_path)
                if not text.strip():
                    continue
                
                chunks = self.chunk_text(text)
                ids = [f"{file_path}_{i}" for i in range(len(chunks))]
                metadatas = [{"source": file_path, "chunk": i} for i in range(len(chunks))]
                
                # Add to chroma (it handles embeddings automatically using sentence-transformers default)
                self.collection.add(
                    documents=chunks,
                    metadatas=metadatas,
                    ids=ids
                )
                new_files += 1

        return f"Synced {new_files} new files into Koza Brain."

    def search_brain(self, query: str, n_results: int = 5):
        """Searches the local knowledge base for the query."""
        if not CHROMA_AVAILABLE:
            return "ChromaDB not available."
        
        results = self.collection.query(
            query_texts=[query],
            n_results=n_results
        )
        
        output = []
        if results and "documents" in results and results["documents"]:
            docs = results["documents"][0]
            metas = results["metadatas"][0]
            for doc, meta in zip(docs, metas):
                output.append(f"--- Source: {meta.get('source', 'Unknown')} ---\n{doc}\n")
        
        if not output:
            return "No relevant information found in Koza Brain."
            
        return "\n".join(output)

# Instantiate a global manager if possible
brain_manager = None
try:
    if CHROMA_AVAILABLE:
        brain_manager = BrainManager()
except Exception as e:
    print("Failed to initialize BrainManager:", e)

def get_brain_manager():
    global brain_manager
    if brain_manager is None and CHROMA_AVAILABLE:
        brain_manager = BrainManager()
    return brain_manager

def brain_sync_folder() -> str:
    """Scan the ~/.koza/brain directory and index new files."""
    mgr = get_brain_manager()
    if not mgr:
        return "ChromaDB not available. Install it first."
    return mgr.sync_brain_folder()

def brain_search(query: str, count: int = 5) -> str:
    """Search the Koza Brain for information."""
    mgr = get_brain_manager()
    if not mgr:
        return "ChromaDB not available. Install it first."
    return mgr.search_brain(query, n_results=count)

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "brain_sync_folder",
            "description": "Scan the ~/.koza/brain directory and index new documents into the local knowledge base.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "brain_search",
            "description": "Search the Koza Brain (local knowledge base) for information from user documents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The question or keywords to search for"},
                    "count": {"type": "integer", "default": 5, "description": "Number of results to return"},
                },
                "required": ["query"],
            },
        },
    },
]

HANDLERS = {
    "brain_sync_folder": lambda **_: brain_sync_folder(),
    "brain_search": lambda query, count=5: brain_search(query, count=count),
}

