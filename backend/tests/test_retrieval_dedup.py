from types import SimpleNamespace

from app.services.retrieval import DocumentRetriever


def _doc(doc_id: str, content: str, source: str = "vosdroits"):
    return SimpleNamespace(
        page_content=content,
        metadata={
            "ID": doc_id,
            "source_file": f"{doc_id}.xml",
            "spUrl": f"https://example.org/{doc_id}",
            "data_source": source,
        },
    )


def _build_retriever_for_unit_tests() -> DocumentRetriever:
    # Bypass __init__ to avoid loading embeddings/Chroma from disk and network.
    retriever = DocumentRetriever.__new__(DocumentRetriever)
    retriever.reranker = None
    retriever.bofip_vector_store = None
    return retriever


def test_merge_documents_merges_same_id_chunks():
    retriever = _build_retriever_for_unit_tests()
    docs = [
        SimpleNamespace(
            id="A1",
            source_file="A1.xml",
            sp_url="https://example.org/A1",
            page_content="Chunk 1",
            data_source="vosdroits",
        ),
        SimpleNamespace(
            id="A1",
            source_file="A1.xml",
            sp_url="https://example.org/A1",
            page_content="Chunk 2",
            data_source="vosdroits",
        ),
    ]

    merged = retriever.merge_documents(docs)

    assert len(merged) == 1
    assert "Chunk 1" in merged[0].page_content
    assert "Chunk 2" in merged[0].page_content


def test_retrieve_documents_deduplicates_and_applies_max_docs():
    retriever = _build_retriever_for_unit_tests()
    retriever.vector_store = SimpleNamespace(
        similarity_search=lambda query, k: [
            _doc("A1", "Chunk 1"),
            _doc("A1", "Chunk 2"),
            _doc("B2", "Chunk 3"),
        ]
    )

    result = retriever.retrieve_documents("passeport", top_k=20, max_docs=1)

    assert len(result) == 1
    assert result[0].id == "A1"
    assert "Chunk 1" in result[0].page_content
    assert "Chunk 2" in result[0].page_content


def test_retrieve_documents_merges_bofip_and_service_public():
    retriever = _build_retriever_for_unit_tests()
    retriever.vector_store = SimpleNamespace(
        similarity_search=lambda query, k: [_doc("SP1", "SP chunk")]
    )
    retriever.bofip_vector_store = SimpleNamespace(
        similarity_search=lambda query, k: [
            SimpleNamespace(
                page_content="BOFiP chunk",
                metadata={
                    "document_id": "BOF-1",
                    "canonical_url": "https://bofip.impots.gouv.fr/bofip/BOF-1",
                    "title": "Titre fiscal",
                    "source_file": "records/BOF-1.json",
                    "data_source": "bofip",
                },
            )
        ]
    )

    result = retriever.retrieve_documents("impôt sur le revenu", top_k=20, max_docs=2)

    assert len(result) == 2
    sources = {doc.data_source for doc in result}
    assert sources == {"vosdroits", "bofip"}
