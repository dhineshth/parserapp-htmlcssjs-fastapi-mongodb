import os
from llama_parse import LlamaParse
from typing import Optional

def initialize_llama_parser(result_type: str = "json") -> Optional[LlamaParse]:
    """
    Initializes LlamaParse with the given result type.
    :param result_type: 'json' or 'text'
    :return: LlamaParse object or None
    """
    try:
        api_key = os.getenv("LLAMA_CLOUD_API_KEY")
        if not api_key:
            raise ValueError("LLAMA_CLOUD_API_KEY not found in environment variables.")
        return LlamaParse(
            api_key=api_key,
            result_type=result_type,
            verbose=True
        )
    except Exception as e:
        raise Exception(f"LlamaParse initialization failed: {str(e)}")


def parse_resume_with_llama(file_path: str, parser: LlamaParse) -> Optional[str]:
    """
    Parse the resume using a given LlamaParse parser.
    :param file_path: Path to resume PDF
    :param parser: LlamaParse instance
    :return: Extracted text
    """
    try:
        documents = parser.load_data(file_path)
        if documents:
            return documents[0].text
        else:
            raise Exception("No documents returned from parser.")
    except Exception as e:
        raise Exception(f"LlamaParse failed: {str(e)}")
