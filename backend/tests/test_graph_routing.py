from types import SimpleNamespace

from app.core.graph_agent import GraphState, TurgotGraphAgent


def _build_agent_for_unit_tests() -> TurgotGraphAgent:
    # Bypass __init__ to avoid external service initialization (Redis/LLM/Chroma).
    return TurgotGraphAgent.__new__(TurgotGraphAgent)


def test_route_after_classification_non_administrative():
    agent = _build_agent_for_unit_tests()
    state = GraphState(message="Hi", session_id="s1", is_non_administrative=True)

    assert agent._route_after_classification(state) == "non_administrative"


def test_route_after_classification_simple():
    agent = _build_agent_for_unit_tests()
    state = GraphState(
        message="Question administrative simple",
        session_id="s1",
        is_non_administrative=False,
        needs_rag=False,
    )

    assert agent._route_after_classification(state) == "simple"


def test_route_after_classification_rag():
    agent = _build_agent_for_unit_tests()
    state = GraphState(
        message="Question administrative complexe",
        session_id="s1",
        is_non_administrative=False,
        needs_rag=True,
    )

    assert agent._route_after_classification(state) == "rag"


def test_classify_query_non_administrative_short_circuit():
    agent = _build_agent_for_unit_tests()
    agent._is_non_administrative_question = lambda _: True
    agent.classifier_llm = SimpleNamespace(
        invoke=lambda _: SimpleNamespace(content="OUI")
    )
    state = GraphState(message="Parle-moi de football", session_id="s1")

    result = agent._classify_query(state)

    assert result.is_non_administrative is True
    assert result.needs_rag is False


def test_classify_query_administrative_simple_path():
    agent = _build_agent_for_unit_tests()
    agent._is_non_administrative_question = lambda _: False
    agent.classifier_llm = SimpleNamespace(
        invoke=lambda _: SimpleNamespace(content="NON")
    )
    state = GraphState(message="Comment renouveler ma carte vitale ?", session_id="s1")

    result = agent._classify_query(state)

    assert result.is_non_administrative is False
    assert result.needs_rag is False


def test_classify_query_administrative_rag_path():
    agent = _build_agent_for_unit_tests()
    agent._is_non_administrative_question = lambda _: False
    agent.classifier_llm = SimpleNamespace(
        invoke=lambda _: SimpleNamespace(content="OUI")
    )
    state = GraphState(message="Quels justificatifs pour un passeport ?", session_id="s1")

    result = agent._classify_query(state)

    assert result.is_non_administrative is False
    assert result.needs_rag is True
