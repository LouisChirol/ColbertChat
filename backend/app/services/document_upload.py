import re


MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_UPLOAD_PAGES = 20


def estimate_pdf_page_count(pdf_bytes: bytes) -> int:
    """
    Lightweight page count estimate without persisting files.

    This intentionally avoids adding heavy PDF dependencies for the Phase 4 skeleton.
    """
    decoded = pdf_bytes.decode("latin-1", errors="ignore")
    # Basic PDF marker count. It is approximate but sufficient for a strict guardrail.
    matches = re.findall(r"/Type\s*/Page\b", decoded)
    return max(1, len(matches))
