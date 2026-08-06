from dataclasses import dataclass

from langchain_core.documents import Document


@dataclass(frozen=True)
class CitedSource:
    """A retrieved chunk paired with the label the model is told to cite it by.

    The pairing is stored explicitly, so the meaning of a label never depends on
    this object's position in any list.
    """

    label: str
    document: Document

    @property
    def display_name(self) -> str:
        return self.document.metadata.get("display_name", "unknown source")

    @property
    def chunk_id(self) -> str:
        return self.document.metadata.get("chunk_id", "")
