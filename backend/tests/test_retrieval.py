from app.services.retrieval import DocumentRetrieved, DocumentRetriever


def _build_retriever_without_init() -> DocumentRetriever:
    return DocumentRetriever.__new__(DocumentRetriever)


def test_merge_documents_deduplicates_by_id():
    retriever = _build_retriever_without_init()
    docs = [
        DocumentRetrieved(id="F1", page_content="part 1", sp_url="https://a"),
        DocumentRetrieved(id="F1", page_content="part 2", sp_url="https://a"),
        DocumentRetrieved(id="F2", page_content="unique", sp_url="https://b"),
    ]

    merged = retriever.merge_documents(docs)
    merged_by_id = {doc.id: doc for doc in merged}

    assert len(merged) == 2
    assert "part 1" in merged_by_id["F1"].page_content
    assert "part 2" in merged_by_id["F1"].page_content
    assert merged_by_id["F2"].page_content == "unique"
