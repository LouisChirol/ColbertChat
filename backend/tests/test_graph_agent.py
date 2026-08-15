from types import SimpleNamespace

from app.core.graph_agent import GraphState, TurgotGraphAgent


def _build_agent_without_init() -> TurgotGraphAgent:
    return TurgotGraphAgent.__new__(TurgotGraphAgent)


def test_route_after_classification_non_admin():
    agent = _build_agent_without_init()
    state = GraphState(
        message="salut",
        session_id="s1",
        is_non_administrative=True,
        needs_rag=False,
    )
    assert agent._route_after_classification(state) == "non_administrative"


def test_route_after_classification_simple():
    agent = _build_agent_without_init()
    state = GraphState(
        message="question simple",
        session_id="s1",
        is_non_administrative=False,
        needs_rag=False,
    )
    assert agent._route_after_classification(state) == "simple"


def test_route_after_classification_rag():
    agent = _build_agent_without_init()
    state = GraphState(
        message="question rag",
        session_id="s1",
        is_non_administrative=False,
        needs_rag=True,
    )
    assert agent._route_after_classification(state) == "rag"


def test_generate_search_query_prefers_retrieval_message():
    agent = _build_agent_without_init()
    captured = {}

    class FakeRetriever:
        def generate_search_query(self, query, history):
            captured["query"] = query
            captured["history"] = history
            return "rewritten"

    agent.retriever = FakeRetriever()
    state = GraphState(
        message="how to renew passport",
        retrieval_message="comment renouveler un passeport",
        session_id="s1",
        history=SimpleNamespace(messages=[]),
    )

    updated = agent._generate_search_query(state)
    assert updated.search_query == "rewritten"
    assert captured["query"] == "comment renouveler un passeport"
