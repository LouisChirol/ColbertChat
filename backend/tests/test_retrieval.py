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


def test_merge_documents_keeps_same_id_across_sources_separate():
    retriever = _build_retriever_without_init()
    docs = [
        DocumentRetrieved(
            id="ABC123",
            page_content="sp",
            sp_url="https://sp",
            data_source="vosdroits",
        ),
        DocumentRetrieved(
            id="ABC123",
            page_content="bofip",
            sp_url="https://bofip",
            data_source="bofip",
        ),
    ]

    merged = retriever.merge_documents(docs)
    assert len(merged) == 2


def test_apply_source_caps_limits_bofip_hits():
    retriever = _build_retriever_without_init()
    docs = [
        DocumentRetrieved(id="b1", data_source="bofip", page_content="1"),
        DocumentRetrieved(id="b2", data_source="bofip", page_content="2"),
        DocumentRetrieved(id="b3", data_source="bofip", page_content="3"),
        DocumentRetrieved(id="sp1", data_source="vosdroits", page_content="sp"),
    ]

    capped = retriever._apply_source_caps(docs, max_docs=3, bofip_max=2)
    bofip_docs = [doc for doc in capped if doc.data_source == "bofip"]

    assert len(capped) == 3
    assert len(bofip_docs) == 2
    assert capped[0].id == "b1"
    assert capped[1].id == "b2"
    assert capped[2].id == "sp1"
