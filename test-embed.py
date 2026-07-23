from langchain_ollama import OllamaEmbeddings

model = OllamaEmbeddings(
    model="embeddinggemma:latest"
)

print("Creating embedding...")

embedding = model.embed_query("hello world")

print(len(embedding))