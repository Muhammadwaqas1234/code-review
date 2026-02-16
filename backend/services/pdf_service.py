from pypdf import PdfReader
from backend.config import logger


class PDFService:

    @staticmethod
    def read_roles(file_path: str) -> str:
        logger.info("Reading roles PDF...")

        reader = PdfReader(file_path)
        text = ""

        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"

        logger.info("Roles extracted successfully")
        return text
