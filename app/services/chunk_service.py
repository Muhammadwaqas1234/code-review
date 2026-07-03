"""Split repository source files into retrieval-sized chunks.

Chunks are created per file and every chunk begins with a ``FILE:`` header,
so a reviewer agent reading a retrieved chunk always knows which file it is
looking at and can cite it in its findings. Splits happen on line
boundaries — never mid-line — and a global cap keeps embedding cost bounded
on huge repositories.
"""

from dataclasses import dataclass

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.repo_service import SourceFile

logger = get_logger("services.chunk")


@dataclass(frozen=True)
class Chunk:
    """One retrieval unit: a slice of a single source file."""

    file_path: str  # repository-relative posix path
    text: str  # includes the FILE header line

    @staticmethod
    def build(file_path: str, body: str) -> "Chunk":
        return Chunk(file_path=file_path, text=f"FILE: {file_path}\n{body}")


class ChunkService:
    @staticmethod
    def chunk_files(files: list[SourceFile]) -> list[Chunk]:
        """Chunk all source files, respecting the global chunk cap."""
        settings = get_settings()
        max_chars = settings.chunk_max_chars
        chunks: list[Chunk] = []
        files_dropped = 0

        for file in files:
            if len(chunks) >= settings.max_chunks:
                files_dropped += 1
                continue

            remaining = settings.max_chunks - len(chunks)
            file_chunks = ChunkService._chunk_one(file, max_chars)
            if len(file_chunks) > remaining:
                file_chunks = file_chunks[:remaining]
            chunks.extend(file_chunks)

        if files_dropped:
            logger.warning(
                "Chunk cap (%d) reached; %d file(s) were not indexed",
                settings.max_chunks,
                files_dropped,
            )
        logger.info("Created %d chunks from %d files", len(chunks), len(files))
        return chunks

    @staticmethod
    def _chunk_one(file: SourceFile, max_chars: int) -> list[Chunk]:
        """Split one file into chunks of at most `max_chars`, on line boundaries."""
        content = file.content
        if len(content) <= max_chars:
            return [Chunk.build(file.path, content)]

        chunks: list[Chunk] = []
        buffer: list[str] = []
        buffer_len = 0

        for line in content.splitlines(keepends=True):
            # A single pathological line longer than the limit is hard-split.
            while len(line) > max_chars:
                if buffer:
                    chunks.append(Chunk.build(file.path, "".join(buffer)))
                    buffer, buffer_len = [], 0
                chunks.append(Chunk.build(file.path, line[:max_chars]))
                line = line[max_chars:]

            if buffer_len + len(line) > max_chars and buffer:
                chunks.append(Chunk.build(file.path, "".join(buffer)))
                buffer, buffer_len = [], 0

            buffer.append(line)
            buffer_len += len(line)

        if buffer:
            chunks.append(Chunk.build(file.path, "".join(buffer)))
        return chunks
