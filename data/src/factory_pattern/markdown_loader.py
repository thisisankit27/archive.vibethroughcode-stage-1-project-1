import os
import tempfile

from langchain_community.document_loaders import UnstructuredMarkdownLoader

from data.src.factory_pattern.loader import Loader


class MarkdownLoader(Loader):

    def __init__(self, uploaded_file):
        self.uploaded_file = uploaded_file

    def load(self):

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=".md",
            mode="wb",
        ) as temp_file:

            temp_file.write(self.uploaded_file.getvalue())
            file_path = temp_file.name

        try:
            loader =UnstructuredMarkdownLoader(file_path)
            return loader.load()

        finally:
            if os.path.exists(file_path):
                os.remove(file_path)