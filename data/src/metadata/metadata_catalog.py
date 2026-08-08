import json
from langchain_core.documents import Document

from data.src.config import CATALOG_PATH

class MetadataCatalog:
    _catalog = []
    _existing_ids = set()

    @classmethod
    def _load(cls):
        if cls._catalog:
            return
        
        CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)

        # Load existing catalog
        if CATALOG_PATH.exists():
            with CATALOG_PATH.open("r", encoding="utf-8") as file:
                cls._catalog = json.load(file)
        else:
            cls._catalog = []

        # Existing document IDs
        cls._existing_ids = {
            document["document_id"]
            for document in cls._catalog
        }

    @classmethod
    def _persist(cls):

        # Persist catalog
        with CATALOG_PATH.open("w", encoding="utf-8") as file:
            json.dump(
                cls._catalog,
                file,
                indent=4,
                ensure_ascii=False,
            )

    @classmethod
    def register(cls, loaded_documents: list[Document]) -> None:
        
        cls._load()
        # Register one entry per uploaded document
        for document in loaded_documents:

            document_id = document.metadata["document_id"]

            if document_id in cls._existing_ids:
                continue

            cls._catalog.append(
                {
                    "document_id": document_id,
                    "display_name": document.metadata["display_name"],
                    "source": document.metadata.get("source", ""),
                }
            )

            cls._existing_ids.add(document_id)

            cls._persist()

    @classmethod
    def list_documents(cls):
        cls._load()
        return cls._catalog