import tiktoken
from backend.config import logger


class SmartChunker:

    def __init__(self, model="gpt-4o"):
        self.encoder = tiktoken.encoding_for_model(model)

    def chunk_text(self, text: str, max_tokens: int = 1200):
        tokens = self.encoder.encode(text)
        chunks = []

        for i in range(0, len(tokens), max_tokens):
            chunk = tokens[i:i + max_tokens]
            chunks.append(self.encoder.decode(chunk))

        logger.info(f"Created {len(chunks)} chunks")
        return chunks
