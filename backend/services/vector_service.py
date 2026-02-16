import faiss
import numpy as np
from openai import OpenAI
from backend.config import logger

client = OpenAI()


class VectorService:

    def __init__(self):
        self.index = None
        self.documents = []

    def embed(self, text: str):
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        return np.array(response.data[0].embedding).astype("float32")

    def build_index(self, chunks):
        embeddings = [self.embed(chunk) for chunk in chunks]
        dimension = len(embeddings[0])

        self.index = faiss.IndexFlatL2(dimension)
        self.index.add(np.array(embeddings))

        self.documents = chunks

    def search(self, query: str, k: int = 5):
        query_vector = self.embed(query)
        D, I = self.index.search(np.array([query_vector]), k)
        return [self.documents[i] for i in I[0]]
