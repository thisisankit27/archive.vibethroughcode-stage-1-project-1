import os
import tempfile

from langchain_community.document_loaders import PyPDFLoader

from data.src.factory_pattern.loader import Loader


class PdfLoader(Loader):

    def __init__(self, uploaded_file):
        self.uploaded_file = uploaded_file

    def load(self):

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=".pdf",
            mode="wb",
        ) as temp_file:

            temp_file.write(self.uploaded_file.getvalue())
            file_path = temp_file.name

        try:
            loader = PyPDFLoader(file_path=file_path)
            return loader.load()

        finally:
            if os.path.exists(file_path):
                os.remove(file_path)