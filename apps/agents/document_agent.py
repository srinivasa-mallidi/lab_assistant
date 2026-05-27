"""
Document Agent
Handles RAG retrieval from ingested laboratory documents (SOPs, manuals, guides).
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma, FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import (
    PyPDFLoader,
    Docx2txtLoader,
    TextLoader,                        # was TextFileLoader — correct name
    UnstructuredPowerPointLoader,
)
from langchain.schema import Document

from django.conf import settings

logger = logging.getLogger("lab_assistant")


@dataclass
class RAGResult:
    chunks: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    formatted_context: str = ""
    num_results: int = 0


class DocumentAgent:
    """
    RAG agent that:
    1. Ingests PDF/DOCX/PPTX documents into vector store
    2. Performs semantic search on user queries
    3. Returns relevant chunks with source citations
    """

    def __init__(self):
        self.embeddings = self._init_embeddings()
        self.vector_store = self._init_vector_store()
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.RAG_CONFIG["chunk_size"],
            chunk_overlap=settings.RAG_CONFIG["chunk_overlap"],
            separators=["\n\n", "\n", ".", "!", "?", ",", " ", ""],
        )

    def _init_embeddings(self) -> HuggingFaceEmbeddings:
        return HuggingFaceEmbeddings(
            model_name=settings.EMBEDDING_MODEL,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )

    def _init_vector_store(self):
        store_type = settings.VECTOR_STORE_TYPE

        if store_type == "chroma":
            persist_dir = str(settings.CHROMA_PERSIST_DIR)
            Path(persist_dir).mkdir(parents=True, exist_ok=True)
            return Chroma(
                collection_name="lab_documents",
                embedding_function=self.embeddings,
                persist_directory=persist_dir,
            )
        elif store_type == "faiss":
            faiss_path = settings.FAISS_INDEX_DIR / "index.faiss"
            if faiss_path.exists():
                return FAISS.load_local(
                    str(settings.FAISS_INDEX_DIR),
                    self.embeddings,
                    allow_dangerous_deserialization=True,
                )
            # Return empty FAISS; will be populated on first ingest
            return None
        else:
            raise ValueError(f"Unsupported vector store type: {store_type}")

    def ingest_document(self, file_path: str, metadata: dict = None) -> dict:
        """
        Ingest a document file into the vector store.
        Supports: PDF, DOCX, PPTX, TXT, MD
        Returns: dict with chunk count and document ID
        """
        path = Path(file_path)
        suffix = path.suffix.lower()
        metadata = metadata or {}

        # Load document
        try:
            if suffix == ".pdf":
                loader = PyPDFLoader(file_path)
            elif suffix == ".docx":
                loader = Docx2txtLoader(file_path)
            elif suffix in (".pptx", ".ppt"):
                loader = UnstructuredPowerPointLoader(file_path)
            elif suffix in (".txt", ".md"):
                loader = TextLoader(file_path, encoding="utf-8")
            else:
                raise ValueError(f"Unsupported file type: {suffix}")

            raw_docs = loader.load()
        except Exception as e:
            logger.error(f"Failed to load document {file_path}: {e}")
            raise

        # Enrich metadata
        for doc in raw_docs:
            doc.metadata.update({
                "source_file": path.name,
                "file_type": suffix,
                "document_type": metadata.get("document_type", "general"),
                "title": metadata.get("title", path.stem),
                "uploaded_by": metadata.get("uploaded_by", "system"),
                "doc_id": metadata.get("doc_id", str(path.stem)),
            })

        # Split into chunks
        chunks = self.text_splitter.split_documents(raw_docs)
        logger.info(f"Split {path.name} into {len(chunks)} chunks")

        # Add to vector store
        if settings.VECTOR_STORE_TYPE == "chroma":
            self.vector_store.add_documents(chunks)
        elif settings.VECTOR_STORE_TYPE == "faiss":
            if self.vector_store is None:
                self.vector_store = FAISS.from_documents(chunks, self.embeddings)
            else:
                self.vector_store.add_documents(chunks)
            self.vector_store.save_local(str(settings.FAISS_INDEX_DIR))

        return {
            "chunks_created": len(chunks),
            "document_title": metadata.get("title", path.stem),
            "file_name": path.name,
        }

    async def retrieve(self, context) -> RAGResult:
        """Retrieve relevant chunks for the user's query."""
        if self.vector_store is None:
            logger.warning("Vector store is empty - no documents ingested yet")
            return RAGResult(
                formatted_context="No documents have been ingested into the knowledge base yet."
            )

        query = context.message
        top_k = settings.RAG_CONFIG["top_k_results"]
        threshold = settings.RAG_CONFIG["similarity_threshold"]

        try:
            # Similarity search with scores
            results_with_scores = self.vector_store.similarity_search_with_score(
                query, k=top_k
            )

            # Filter by similarity threshold
            filtered = [
                (doc, score)
                for doc, score in results_with_scores
                if score >= threshold
            ]

            if not filtered:
                return RAGResult(
                    formatted_context="No relevant documentation found for this query."
                )

            # Build result
            chunks = []
            sources = []
            context_parts = []

            seen_sources = set()

            for i, (doc, score) in enumerate(filtered):
                chunks.append({
                    "content": doc.page_content,
                    "metadata": doc.metadata,
                    "score": float(score),
                })

                # Deduplicate sources
                source_key = doc.metadata.get("source_file", "Unknown")
                if source_key not in seen_sources:
                    seen_sources.add(source_key)
                    sources.append({
                        "title": doc.metadata.get("title", source_key),
                        "file": source_key,
                        "doc_type": doc.metadata.get("document_type", "Document"),
                        "page": doc.metadata.get("page", "N/A"),
                    })

                # Format for context injection
                context_parts.append(
                    f"[Source {i+1}: {doc.metadata.get('title', source_key)}, "
                    f"Page {doc.metadata.get('page', 'N/A')}]\n"
                    f"{doc.page_content}"
                )

            formatted = "\n\n---\n\n".join(context_parts)

            return RAGResult(
                chunks=chunks,
                sources=sources,
                formatted_context=formatted,
                num_results=len(filtered),
            )

        except Exception as e:
            logger.error(f"RAG retrieval error: {e}", exc_info=True)
            return RAGResult(
                formatted_context=f"Error retrieving knowledge base content: {str(e)}"
            )

    def get_collection_stats(self) -> dict:
        """Return vector store statistics."""
        try:
            if settings.VECTOR_STORE_TYPE == "chroma":
                count = self.vector_store._collection.count()
                return {"vector_store": "chroma", "document_chunks": count}
            else:
                return {"vector_store": "faiss", "document_chunks": "N/A"}
        except Exception as e:
            return {"vector_store": settings.VECTOR_STORE_TYPE, "error": str(e)}

    def delete_document(self, doc_id: str) -> bool:
        """Remove all chunks for a given document ID from the vector store."""
        try:
            if settings.VECTOR_STORE_TYPE == "chroma":
                self.vector_store._collection.delete(
                    where={"doc_id": doc_id}
                )
                return True
        except Exception as e:
            logger.error(f"Failed to delete document {doc_id}: {e}")
        return False
