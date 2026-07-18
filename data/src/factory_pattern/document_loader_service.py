from data.src.factory_pattern.loader_factory import LoaderFactory


def load_documents(uploaded_files):

    if not uploaded_files:
        return []

    documents = []

    for uploaded_file in uploaded_files:
        loader = LoaderFactory.create(uploaded_file)

        documents.extend(loader.load())

    return documents