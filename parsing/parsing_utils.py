import re
import os
from PyPDF2 import PdfReader
import docx2txt
from pdfminer.high_level import extract_text
from typing import Optional
from llama.llama_utils import parse_resume_with_llama
from llama_parse import LlamaParse


def extract_email(resume_text: str) -> str:
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    match = re.search(email_pattern, resume_text)
    return match.group(0) if match else "No email found"

def extract_text_from_pdf(file_path: str) -> str:
    try:
        with open(file_path, "rb") as f:
            reader = PdfReader(f)
            text = "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
        return text
    except Exception as e:
        raise Exception(f"Error extracting PDF: {e}")

def extract_text_from_docx(file_path: str) -> str:
    try:
        return docx2txt.process(file_path)
    except Exception as e:
        raise Exception(f"Error extracting DOCX: {e}")

def parse_resume(file_path: str, parser: LlamaParse) -> str:
    """
    Primary parser function. If LlamaParse fails, falls back to pdfminer.
    :param file_path: Resume path
    :param parser: LlamaParse instance
    :return: Resume text
    """
    try:
        if parser:
            return parse_resume_with_llama(file_path, parser)
    except Exception:
        pass
    return extract_text(file_path)

def extract_text(file_path: str) -> str:
    ext = os.path.splitext(file_path)[-1].lower()
    if ext == ".pdf":
        return extract_text_from_pdf(file_path)
    elif ext == ".docx":
        return extract_text_from_docx(file_path)
    # elif ext == ".doc":
    #     return extract_text_from_doc(file_path)
    else:
        raise Exception("Unsupported file type.")