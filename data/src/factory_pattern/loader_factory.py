from pathlib import Path

from data.src.factory_pattern.loader import Loader
from data.src.factory_pattern.pdf_loader import PdfLoader
from data.src.factory_pattern.markdown_loader import MarkdownLoader

class LoaderFactory:

    @staticmethod
    def create(uploaded_file) -> Loader:

        extension = Path(uploaded_file.name).suffix.lower()

        if extension == ".pdf":
            return PdfLoader(uploaded_file)
        if extension == ".md":
            return MarkdownLoader(uploaded_file)

        raise ValueError(f"Unsupported file type: {extension}")