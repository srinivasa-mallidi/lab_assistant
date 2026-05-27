"""
Django Management Command: ingest_documents
Usage: python manage.py ingest_documents --dir ./data/sample_docs
       python manage.py ingest_documents --file sop-001.pdf --type sop
"""

import os
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User


class Command(BaseCommand):
    help = "Ingest laboratory documents into the RAG vector store"

    def add_arguments(self, parser):
        parser.add_argument("--dir",  type=str, help="Directory of documents to ingest")
        parser.add_argument("--file", type=str, help="Single file to ingest")
        parser.add_argument("--type", type=str, default="general",
                            choices=["sop", "training", "user_guide", "validation", "kb", "general"],
                            help="Document type")
        parser.add_argument("--user", type=str, default="admin", help="Uploader username")
        parser.add_argument("--clear", action="store_true", help="Clear vector store first")

    def handle(self, *args, **options):
        from apps.agents.document_agent import DocumentAgent
        from apps.documents.models import Document

        agent = DocumentAgent()

        if options["clear"]:
            self.stdout.write(self.style.WARNING("Clearing vector store…"))
            # Re-initialize
            from django.conf import settings
            if settings.VECTOR_STORE_TYPE == "chroma":
                agent.vector_store._collection.delete(where={})
            self.stdout.write(self.style.SUCCESS("Vector store cleared."))

        # Get uploader
        try:
            uploader = User.objects.get(username=options["user"])
        except User.DoesNotExist:
            uploader = User.objects.first()
            self.stdout.write(self.style.WARNING(f"User '{options['user']}' not found, using {uploader}"))

        files_to_process = []

        if options["file"]:
            p = Path(options["file"])
            if not p.exists():
                raise CommandError(f"File not found: {p}")
            files_to_process.append(p)

        if options["dir"]:
            d = Path(options["dir"])
            if not d.exists():
                raise CommandError(f"Directory not found: {d}")
            from django.conf import settings
            exts = settings.ALLOWED_DOCUMENT_TYPES
            files_to_process.extend([f for f in d.rglob("*") if f.suffix.lower() in exts])

        if not files_to_process:
            raise CommandError("No files to process. Use --file or --dir")

        self.stdout.write(f"Processing {len(files_to_process)} files…\n")

        success_count = 0
        fail_count = 0

        for file_path in files_to_process:
            self.stdout.write(f"  📄 {file_path.name}… ", ending="")

            try:
                # Create DB record
                import uuid
                doc = Document.objects.create(
                    title=file_path.stem.replace("-", " ").replace("_", " ").title(),
                    file_name=file_path.name,
                    file_path=str(file_path),
                    document_type=options["type"],
                    uploaded_by=uploader,
                    file_size=file_path.stat().st_size,
                    status="processing",
                )

                result = agent.ingest_document(
                    str(file_path),
                    metadata={
                        "doc_id": str(doc.id),
                        "title": doc.title,
                        "document_type": options["type"],
                        "uploaded_by": uploader.username,
                    }
                )

                doc.status = "active"
                doc.chunks_count = result["chunks_created"]
                doc.save(update_fields=["status", "chunks_count"])

                self.stdout.write(self.style.SUCCESS(f"✓ {result['chunks_created']} chunks"))
                success_count += 1

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"✗ {e}"))
                fail_count += 1

        self.stdout.write("\n" + "=" * 40)
        self.stdout.write(self.style.SUCCESS(f"✓ Success: {success_count} documents"))
        if fail_count:
            self.stdout.write(self.style.ERROR(f"✗ Failed:  {fail_count} documents"))
        self.stdout.write(f"\nVector store stats: {agent.get_collection_stats()}")
