import os
import re
import time
from typing import Any, List, Literal

from app.core.prompts import (
    CLASSIFICATION_PROMPT,
    OUT_OF_SCOPE_RESPONSE_PROMPT,
    OUTPUT_PROMPT,
    RAG_CLASSIFICATION_PROMPT,
    TURGOT_PROMPT,
)
from app.services.redis import RedisService
from app.services.retrieval import DocumentRetrieved, DocumentRetriever
from app.utils.tokens import create_message_trimmer
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_mistralai import ChatMistralAI
from langgraph.graph import END, StateGraph
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

load_dotenv()

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
if not MISTRAL_API_KEY:
    raise ValueError("MISTRAL_API_KEY environment variable is not set")

# RAG parameters
TOP_K_RETRIEVAL = 20
TOP_N_SOURCES = 8

# Token limits
MAX_TOKENS = 32000
RESERVED_TOKENS = 8000


class GraphState(BaseModel):
    """State shared across all nodes in the graph."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Input
    message: str
    session_id: str
    detected_language: str = "fr"
    retrieval_message: str = ""

    # History and context
    history: Any = None
    history_messages: List[Any] = Field(default_factory=list)

    # Classification
    needs_rag: bool = False
    is_non_administrative: bool = False

    # RAG components
    search_query: str = ""
    documents: List[DocumentRetrieved] = Field(default_factory=list)
    context: str = ""
    sources: List[dict] = Field(default_factory=list)

    # Token management
    trimmed_history: List[Any] = Field(default_factory=list)
    total_tokens: int = 0

    # Response
    answer: str = ""
    formatted_response: str = ""

    # Error handling
    error: str | None = None


class TurgotGraphAgent:
    """LangGraph-based implementation of the Turgot agent."""

    def __init__(self):
        # Initialize services
        self.redis_service = RedisService()
        self.retriever = DocumentRetriever()

        # Initialize message trimmer
        self.message_trimmer = create_message_trimmer(
            max_tokens=MAX_TOKENS - RESERVED_TOKENS, model_name="mistral-medium-latest"
        )

        # Initialize LLMs
        self.llm = ChatMistralAI(
            model="mistral-medium-latest",
            temperature=0,
            max_retries=2,
            timeout=120,
            api_key=MISTRAL_API_KEY,
        )

        self.classifier_llm = ChatMistralAI(
            model="mistral-small-latest",
            temperature=0,
            max_retries=2,
            api_key=MISTRAL_API_KEY,
        )

        # Build the graph
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow."""
        workflow = StateGraph(GraphState)

        # Add all nodes
        workflow.add_node("load_history", self._load_history)
        workflow.add_node("detect_language", self._detect_language)
        workflow.add_node("classify_query", self._classify_query)
        workflow.add_node(
            "generate_non_administrative_response",
            self._generate_non_administrative_response,
        )
        workflow.add_node("generate_simple_response", self._generate_simple_response)
        workflow.add_node("generate_search_query", self._generate_search_query)
        workflow.add_node("retrieve_documents", self._retrieve_documents)
        workflow.add_node("format_context", self._format_context)
        workflow.add_node("generate_rag_response", self._generate_rag_response)
        workflow.add_node("format_response", self._format_response)
        workflow.add_node("store_messages", self._store_messages)

        # Define the flow
        workflow.set_entry_point("load_history")
        workflow.add_edge("load_history", "detect_language")
        workflow.add_edge("detect_language", "classify_query")

        # Conditional routing after classification
        workflow.add_conditional_edges(
            "classify_query",
            self._route_after_classification,
            {
                "non_administrative": "generate_non_administrative_response",
                "simple": "generate_simple_response",
                "rag": "generate_search_query",
            },
        )

        # Non-administrative response path
        workflow.add_edge("generate_non_administrative_response", "store_messages")

        # Simple response path
        workflow.add_edge("generate_simple_response", "format_response")

        # RAG response path
        workflow.add_edge("generate_search_query", "retrieve_documents")
        workflow.add_edge("retrieve_documents", "format_context")
        workflow.add_edge("format_context", "generate_rag_response")
        workflow.add_edge("generate_rag_response", "format_response")
        workflow.add_edge("format_response", "store_messages")

        # End
        workflow.add_edge("store_messages", END)

        return workflow.compile()

    def _load_history(self, state: GraphState) -> GraphState:
        """Load conversation history from Redis."""
        try:
            logger.debug(f"Loading history for session: {state.session_id}")

            history = self.redis_service.get_history(state.session_id)
            history_messages = history.messages if hasattr(history, "messages") else []

            logger.debug(f"Loaded {len(history_messages)} history messages")

            return state.model_copy(
                update={
                    "history": history,
                    "history_messages": history_messages,
                    "error": None,
                }
            )
        except Exception as e:
            logger.error(f"Error loading history: {str(e)}")
            return state.model_copy(
                update={
                    "history": None,
                    "history_messages": [],
                    "error": f"Failed to load history: {str(e)}",
                }
            )

    def _detect_language(self, state: GraphState) -> GraphState:
        """Detect input language and prepare retrieval query language."""
        try:
            prompt = (
                "Détecte la langue dominante du message utilisateur. "
                "Réponds uniquement avec un code ISO 639-1 en minuscule "
                "(fr, en, es, it, de, pt, etc.)."
            )
            result = self.classifier_llm.invoke(
                [SystemMessage(content=prompt), HumanMessage(content=state.message)]
            )
            language = (result.content or "fr").strip().lower()[:2]
            if not language.isalpha():
                language = "fr"

            retrieval_message = state.message
            if language != "fr":
                retrieval_message = self._translate_to_french(state.message, language)

            return state.model_copy(
                update={
                    "detected_language": language,
                    "retrieval_message": retrieval_message,
                    "error": None,
                }
            )
        except Exception as e:
            logger.warning(f"Language detection failed, defaulting to French: {e}")
            return state.model_copy(
                update={
                    "detected_language": "fr",
                    "retrieval_message": state.message,
                    "error": None,
                }
            )

    def _classify_query(self, state: GraphState) -> GraphState:
        """Classify whether the query is non-administrative or needs RAG."""
        try:
            logger.debug(f"Classifying query: {state.message[:50]}...")

            # FIRST: Check if it's non-administrative
            is_non_administrative = self._is_non_administrative_question(state.message)

            if is_non_administrative:
                logger.info(
                    f"Query classified as non-administrative: {state.message[:50]}..."
                )
                return state.model_copy(
                    update={
                        "needs_rag": False,
                        "is_non_administrative": True,
                        "error": None,
                    }
                )

            # SECOND: If administrative, check if RAG is needed
            messages = [
                SystemMessage(content=RAG_CLASSIFICATION_PROMPT),
                HumanMessage(
                    content=f"Question: {state.retrieval_message or state.message}"
                ),
            ]

            # Add recent history context if available (last 2 messages max)
            if state.history_messages:
                recent_history = state.history_messages[-2:]
                history_context = "\n".join(
                    [
                        f"{msg.type}: {msg.content[:100]}..."
                        if len(msg.content) > 100
                        else f"{msg.type}: {msg.content}"
                        for msg in recent_history
                    ]
                )
                messages.insert(
                    1, HumanMessage(content=f"Contexte récent: {history_context}")
                )

            result = self.classifier_llm.invoke(messages)
            classification = result.content.strip().upper()
            needs_rag = classification == "OUI"

            logger.info(
                f"Administrative query classification result: {classification} -> needs_rag={needs_rag}"
            )

            return state.model_copy(
                update={
                    "needs_rag": needs_rag,
                    "is_non_administrative": False,
                    "error": None,
                }
            )

        except Exception as e:
            logger.error(f"Error in classification: {str(e)}")
            # Default to RAG if classification fails (safer approach)
            logger.warning("Defaulting to RAG=True due to classification error")
            return state.model_copy(
                update={
                    "needs_rag": True,
                    "is_non_administrative": False,
                    "error": None,  # Don't treat this as a fatal error
                }
            )

    def _route_after_classification(
        self, state: GraphState
    ) -> Literal["non_administrative", "simple", "rag"]:
        """Route based on classification results."""
        if state.is_non_administrative:
            return "non_administrative"
        elif not state.needs_rag:
            return "simple"
        else:
            return "rag"

    def _generate_non_administrative_response(self, state: GraphState) -> GraphState:
        """Generate a friendly out-of-scope response using the LLM."""
        try:
            logger.info("Generating friendly out-of-scope response")

            # Use the LLM to generate a friendly, contextual response
            prompt = OUT_OF_SCOPE_RESPONSE_PROMPT.format(question=state.message)
            messages = [
                SystemMessage(content=prompt),
                SystemMessage(
                    content=self._response_language_instruction(state.detected_language)
                ),
            ]

            response = self.llm.invoke(messages)
            answer = response.content

            return state.model_copy(
                update={"answer": answer, "formatted_response": answer, "error": None}
            )

        except Exception as e:
            logger.error(f"Error generating out-of-scope response: {str(e)}")
            fallback_answer = "Bonjour ! Je suis Turgot, votre assistant pour les démarches administratives françaises. Comment puis-je vous aider aujourd'hui ? 😊"
            return state.model_copy(
                update={
                    "answer": fallback_answer,
                    "formatted_response": fallback_answer,
                    "error": f"Out-of-scope response generation failed: {str(e)}",
                }
            )

    def _generate_simple_response(self, state: GraphState) -> GraphState:
        """Generate a simple response without RAG."""
        try:
            logger.info("Generating simple response without RAG")

            # Convert history to dict format for token trimming
            history_dicts = self._convert_to_message_dicts(state.history_messages)

            # Trim messages to fit token limit
            trimmed_history_dicts, total_tokens, _ = (
                self.message_trimmer.trim_messages_with_summary(
                history_dicts,
                system_messages=[{"role": "system", "content": TURGOT_PROMPT}],
                context_text="Tu réponds sans utiliser de documents de référence. Sois naturel et utile.",
                summarizer=self._summarize_history,
            )
            )

            # Convert back to LangChain format
            trimmed_history = self._convert_to_langchain_messages(trimmed_history_dicts)

            logger.info(
                f"Simple response: using {total_tokens} tokens ({len(trimmed_history)} messages)"
            )

            # Generate normal administrative response
            messages = [
                SystemMessage(content=TURGOT_PROMPT),
                SystemMessage(
                    content="Tu réponds sans utiliser de documents de référence. Sois naturel et utile."
                ),
                SystemMessage(
                    content=self._response_language_instruction(state.detected_language)
                ),
                *trimmed_history,
                HumanMessage(content=state.message),
            ]

            response = self.llm.invoke(messages)
            answer = response.content

            return state.model_copy(
                update={
                    "answer": answer,
                    "trimmed_history": trimmed_history,
                    "total_tokens": total_tokens,
                    "error": None,
                }
            )

        except Exception as e:
            logger.error(f"Error generating simple response: {str(e)}")
            fallback_answer = "Bonjour ! Je suis Turgot, votre assistant pour les démarches administratives françaises. Comment puis-je vous aider aujourd'hui ? 😊"
            return state.model_copy(
                update={
                    "answer": fallback_answer,
                    "error": f"Simple response generation failed: {str(e)}",
                }
            )

    def _is_non_administrative_question(self, message: str) -> bool:
        """Determine if a question is non-administrative."""
        try:
            # Create classification messages
            messages = [
                SystemMessage(content=CLASSIFICATION_PROMPT),
                HumanMessage(content=f"Question: {message}"),
            ]

            result = self.classifier_llm.invoke(messages)
            classification = result.content.strip().upper()

            # If classification says "NON", it's non-administrative
            is_non_administrative = classification == "NON"
            logger.info(
                f"Non-administrative classification for '{message[:50]}...': {classification} -> is_non_administrative={is_non_administrative}"
            )

            return is_non_administrative

        except Exception as e:
            logger.error(f"Error in non-administrative classification: {str(e)}")
            # Default to False if classification fails (safer approach)
            logger.warning(
                "Defaulting to administrative=True due to classification error"
            )
            return False

    def _generate_search_query(self, state: GraphState) -> GraphState:
        """Generate a search query for RAG retrieval."""
        try:
            logger.debug("Generating search query for RAG")

            query = self.retriever.generate_search_query(
                state.retrieval_message or state.message, state.history
            )
            logger.debug(f"Generated search query: {query}")

            return state.model_copy(update={"search_query": query, "error": None})

        except Exception as e:
            logger.error(f"Error generating search query: {str(e)}")
            # Fallback to original message
            return state.model_copy(
                update={
                    "search_query": state.message,
                    "error": f"Search query generation failed, using original message: {str(e)}",
                }
            )

    def _retrieve_documents(self, state: GraphState) -> GraphState:
        """Retrieve documents using the search query."""
        try:
            logger.debug(f"Retrieving documents for query: {state.search_query}")

            docs = self.retriever.retrieve_documents(
                state.search_query, top_k=TOP_K_RETRIEVAL, max_docs=TOP_N_SOURCES
            )

            logger.info(f"Retrieved {len(docs)} documents")

            return state.model_copy(update={"documents": docs, "error": None})

        except Exception as e:
            logger.error(f"Error retrieving documents: {str(e)}")
            return state.model_copy(
                update={
                    "documents": [],
                    "error": f"Document retrieval failed: {str(e)}",
                }
            )

    def _format_context(self, state: GraphState) -> GraphState:
        """Format retrieved documents into context for the LLM."""
        try:
            docs = state.documents

            if not docs:
                context = "Aucun document pertinent n'a été trouvé pour cette question."
                sources = []
            else:
                context = "CONTEXTE - Documents officiels trouvés :\n\n"
                sources = []

                # Group documents by data source for better organization
                vosdroits_docs = [doc for doc in docs if doc.data_source == "vosdroits"]
                entreprendre_docs = [
                    doc for doc in docs if doc.data_source == "entreprendre"
                ]
                other_docs = [
                    doc
                    for doc in docs
                    if doc.data_source not in ["vosdroits", "entreprendre"]
                ]

                # Add documents from vosdroits (particuliers)
                if vosdroits_docs:
                    context += "👤 DOCUMENTS POUR PARTICULIERS (vosdroits) :\n"
                    for doc in vosdroits_docs:
                        context += f"Document {doc.id} (URL: {doc.sp_url}):\n"
                        context += "Extraits pertinents:\n"
                        context += f"{doc.page_content}\n"
                        context += "---\n\n"

                        # Extract valid sources
                        if doc.sp_url is not None and doc.sp_url.strip():
                            title = (
                                doc.source_file.split("/")[-1].replace(".xml", "")
                                if doc.source_file
                                else doc.sp_url
                            )
                            sources.append(
                                {
                                    "url": doc.sp_url,
                                    "title": title,
                                    "excerpt": (doc.page_content or "")[:220],
                                    "data_source": doc.data_source or "other",
                                }
                            )

                # Add documents from entreprendre (professionnels)
                if entreprendre_docs:
                    context += "💼 DOCUMENTS POUR PROFESSIONNELS (entreprendre) :\n"
                    for doc in entreprendre_docs:
                        context += f"Document {doc.id} (URL: {doc.sp_url}):\n"
                        context += "Extraits pertinents:\n"
                        context += f"{doc.page_content}\n"
                        context += "---\n\n"

                        # Extract valid sources
                        if doc.sp_url is not None and doc.sp_url.strip():
                            title = (
                                doc.source_file.split("/")[-1].replace(".xml", "")
                                if doc.source_file
                                else doc.sp_url
                            )
                            sources.append(
                                {
                                    "url": doc.sp_url,
                                    "title": title,
                                    "excerpt": (doc.page_content or "")[:220],
                                    "data_source": doc.data_source or "other",
                                }
                            )

                # Add other documents if any
                if other_docs:
                    context += "📄 AUTRES DOCUMENTS :\n"
                    for doc in other_docs:
                        context += f"Document {doc.id} (URL: {doc.sp_url}):\n"
                        context += "Extraits pertinents:\n"
                        context += f"{doc.page_content}\n"
                        context += "---\n\n"

                        # Extract valid sources
                        if doc.sp_url is not None and doc.sp_url.strip():
                            title = (
                                doc.source_file.split("/")[-1].replace(".xml", "")
                                if doc.source_file
                                else doc.sp_url
                            )
                            sources.append(
                                {
                                    "url": doc.sp_url,
                                    "title": title,
                                    "excerpt": (doc.page_content or "")[:220],
                                    "data_source": doc.data_source or "other",
                                }
                            )

                context += "INSTRUCTION: Basez votre réponse UNIQUEMENT sur les informations contenues dans ces documents. "
                context += "Si les documents contiennent des informations contradictoires ou incomplètes, mentionnez-le clairement. "
                context += "Adaptez votre réponse selon le type de public concerné (particuliers vs professionnels)."

            logger.debug(f"Formatted context with {len(sources)} sources")

            return state.model_copy(
                update={"context": context, "sources": sources, "error": None}
            )

        except Exception as e:
            logger.error(f"Error formatting context: {str(e)}")
            return state.model_copy(
                update={
                    "context": "Erreur lors du formatage du contexte.",
                    "sources": [],
                    "error": f"Context formatting failed: {str(e)}",
                }
            )

    def _generate_rag_response(self, state: GraphState) -> GraphState:
        """Generate response using RAG context."""
        try:
            logger.info("Generating RAG-based response")

            # Prepare system messages
            system_messages = [
                {"role": "system", "content": TURGOT_PROMPT},
                {"role": "system", "content": OUTPUT_PROMPT},
            ]

            # Convert history to dict format for token trimming
            history_dicts = self._convert_to_message_dicts(state.history_messages)

            # Add current user message to history for trimming calculation
            all_messages = history_dicts + [{"role": "user", "content": state.message}]

            # Trim messages to fit token limit
            trimmed_messages, total_tokens, _ = (
                self.message_trimmer.trim_messages_with_summary(
                    all_messages,
                    system_messages=system_messages,
                    context_text=state.context,
                    summarizer=self._summarize_history,
                )
            )

            # Convert back to LangChain format and reconstruct message list
            trimmed_langchain = self._convert_to_langchain_messages(
                trimmed_messages[:-1]  # Exclude current message
            )

            # Build final message list
            messages = [
                SystemMessage(content=TURGOT_PROMPT),
                SystemMessage(content=OUTPUT_PROMPT),
                SystemMessage(
                    content=self._response_language_instruction(state.detected_language)
                ),
                *trimmed_langchain,  # Use trimmed history
                HumanMessage(content=state.message),
                HumanMessage(content=state.context),
            ]

            logger.info(
                f"RAG response: using {total_tokens} tokens ({len(trimmed_messages)} trimmed messages)"
            )

            # Generate answer
            start_time = time.time()
            llm_response = self.llm.invoke(messages)
            end_time = time.time()

            logger.debug(
                f"Response generation took {end_time - start_time:.2f} seconds"
            )

            answer = llm_response.content

            # Handle case where no documents were found
            if not state.documents:
                answer = (
                    "Note: Je n'ai pas trouvé d'informations spécifiques dans ma base de données "
                    "pour répondre à votre question. Je vais donc répondre en me basant sur mes "
                    "connaissances générales. Veuillez noter que cette réponse n'est pas "
                    "nécessairement spécifique au contexte français ou aux services publics français.\n\n"
                ) + answer

            return state.model_copy(
                update={
                    "answer": answer,
                    "trimmed_history": trimmed_langchain,
                    "total_tokens": total_tokens,
                    "error": None,
                }
            )

        except Exception as e:
            logger.error(f"Error generating RAG response: {str(e)}")
            fallback_answer = (
                "Désolé, une erreur est survenue lors de la génération de la réponse."
            )
            return state.model_copy(
                update={
                    "answer": fallback_answer,
                    "error": f"RAG response generation failed: {str(e)}",
                }
            )

    def _format_response(self, state: GraphState) -> GraphState:
        """Format the final response with sources."""
        try:
            answer = state.answer

            # Strip code blocks
            formatted_answer = self._strip_code_blocks(answer.strip())

            # Add attention section if there are sources
            if state.sources and len(state.sources) > 0:
                attention_text = "\n\n### Attention\nCette réponse n'est pas exhaustive, prenez le temps de lire en détail les sources proposées.\n"
                formatted_answer += attention_text

            return state.model_copy(
                update={"formatted_response": formatted_answer, "error": None}
            )

        except Exception as e:
            logger.error(f"Error formatting response: {str(e)}")
            return state.model_copy(
                update={
                    "formatted_response": state.answer
                    or "Erreur lors du formatage de la réponse.",
                    "error": f"Response formatting failed: {str(e)}",
                }
            )

    def _store_messages(self, state: GraphState) -> GraphState:
        """Store the conversation messages in Redis."""
        try:
            logger.debug("Storing messages in Redis")

            # Store user message
            self.redis_service.store_message(
                state.session_id, {"role": "user", "content": state.message}
            )

            # Store assistant response
            response_to_store = state.formatted_response or state.answer or ""
            self.redis_service.store_message(
                state.session_id, {"role": "assistant", "content": response_to_store}
            )

            logger.debug("Messages stored successfully")

            return state.model_copy(update={"error": None})

        except Exception as e:
            logger.error(f"Error storing messages: {str(e)}")
            # Don't fail the entire flow if storage fails
            return state.model_copy(
                update={"error": f"Message storage failed: {str(e)}"}
            )

    def _convert_to_message_dicts(self, langchain_messages: list) -> list[dict]:
        """Convert LangChain messages to simple dictionaries for token counting."""
        message_dicts = []
        for msg in langchain_messages:
            if hasattr(msg, "type") and hasattr(msg, "content"):
                role = "user" if msg.type == "human" else msg.type
                message_dicts.append({"role": role, "content": msg.content})
        return message_dicts

    def _convert_to_langchain_messages(self, message_dicts: list[dict]) -> list:
        """Convert message dictionaries back to LangChain messages."""
        langchain_messages = []
        for msg in message_dicts:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                langchain_messages.append(SystemMessage(content=content))
            else:  # user, assistant, or other
                langchain_messages.append(HumanMessage(content=content))

        return langchain_messages

    def _translate_to_french(self, message: str, source_language: str) -> str:
        """Translate a user query to French for retrieval."""
        try:
            translate_prompt = (
                "Traduis la requête suivante en français pour une recherche documentaire. "
                "Préserve les détails administratifs. Réponds uniquement avec la traduction."
            )
            translated = self.classifier_llm.invoke(
                [
                    SystemMessage(content=translate_prompt),
                    HumanMessage(
                        content=f"Langue source: {source_language}\nRequête: {message}"
                    ),
                ]
            )
            return (translated.content or message).strip()
        except Exception as e:
            logger.warning(f"Query translation failed, using original message: {e}")
            return message

    def _response_language_instruction(self, language: str) -> str:
        """Build a concise answer-language instruction."""
        return (
            f"La langue détectée de l'utilisateur est '{language}'. "
            "Réponds strictement dans cette langue, tout en conservant les citations "
            "des sources en français."
        )

    def _summarize_history(self, messages: list[dict]) -> str:
        """Summarize dropped conversation turns with mistral-small."""
        if not messages:
            return ""

        max_messages = messages[-20:]
        history_text = "\n".join(
            [f"{msg.get('role', 'user')}: {msg.get('content', '')}" for msg in max_messages]
        )
        summary_prompt = (
            "Résume les échanges ci-dessous en mémoire conversationnelle utile pour "
            "un assistant administratif français. "
            "Conserve faits, préférences utilisateur, contraintes, étapes déjà faites "
            "et questions en attente. Réponse en 8 puces maximum."
        )
        result = self.classifier_llm.invoke(
            [
                SystemMessage(content=summary_prompt),
                HumanMessage(content=history_text),
            ]
        )
        return (result.content or "").strip()

    def _strip_code_blocks(self, text: str) -> str:
        """Remove Markdown code block formatting from a string."""
        # Remove triple backtick code blocks
        text = re.sub(r"```[a-zA-Z]*\n?", "", text)
        text = text.replace("```", "")
        # Remove single backtick inline code
        text = text.replace("`", "")
        return text.strip()

    def ask_turgot(self, message: str, session_id: str) -> str:
        """
        Main entry point for the agent. Maintains the same API as the original agent.

        Args:
            message: User's message
            session_id: Session identifier for conversation history

        Returns:
            Generated response string
        """
        metadata = self.ask_turgot_with_metadata(message, session_id)
        return metadata["answer"]

    def ask_turgot_with_metadata(self, message: str, session_id: str) -> dict[str, Any]:
        """Process a request and return the answer plus lightweight metadata."""
        try:
            logger.info(
                f"Processing request for session {session_id}: {message[:50]}..."
            )

            # Initialize state
            initial_state = GraphState(message=message, session_id=session_id)

            # Execute the graph
            result = self.graph.invoke(initial_state)

            # Log any errors that occurred during processing
            if result.get("error"):
                logger.warning(f"Errors during processing: {result['error']}")

            # Return the formatted response
            response = result.get("formatted_response", result.get("answer", ""))
            if not response:
                logger.error("No response generated, using fallback")
                response = "Désolé, une erreur est survenue lors de la génération de la réponse."

            if result.get("is_non_administrative"):
                query_type = "non_administrative"
            elif result.get("needs_rag"):
                query_type = "rag"
            else:
                query_type = "simple"

            logger.info("Request processed successfully")
            return {
                "answer": response,
                "query_type": query_type,
                "total_tokens": int(result.get("total_tokens") or 0),
            }

        except Exception as e:
            logger.error(f"Critical error in ask_turgot: {str(e)}")
            logger.exception("Full traceback:")
            return {
                "answer": "Désolé, une erreur critique est survenue lors de la génération de la réponse.",
                "query_type": "error",
                "total_tokens": 0,
            }

    def stream_answer(self, message: str, session_id: str):
        """
        Stream only the assistant's answer as it is generated.

        Yields dictionaries suitable for SSE payloads on the API side:
        - {"type": "chunk", "content": "..."}
        - {"type": "sources", "sources": ["..."]}
        - {"type": "done"}
        """
        try:
            # Load history
            history = self.redis_service.get_history(session_id)
            history_messages = history.messages if hasattr(history, "messages") else []
            detected_language = "fr"
            retrieval_message = message
            try:
                language_detect = self.classifier_llm.invoke(
                    [
                        SystemMessage(
                            content=(
                                "Détecte la langue dominante du message et réponds "
                                "uniquement avec le code ISO 639-1 en minuscule."
                            )
                        ),
                        HumanMessage(content=message),
                    ]
                )
                detected_language = (language_detect.content or "fr").strip().lower()[:2]
                if not detected_language.isalpha():
                    detected_language = "fr"
                if detected_language != "fr":
                    retrieval_message = self._translate_to_french(
                        message, detected_language
                    )
            except Exception as lang_err:
                logger.warning(f"Stream language detection failed: {lang_err}")

            # Determine path: non-admin / simple / rag
            is_non_admin = self._is_non_administrative_question(message)
            needs_rag = True
            if is_non_admin:
                needs_rag = False
            else:
                # RAG classification similar to _classify_query
                messages_cls = [
                    SystemMessage(content=RAG_CLASSIFICATION_PROMPT),
                    HumanMessage(content=f"Question: {retrieval_message}"),
                ]
                if history_messages:
                    recent_history = history_messages[-2:]
                    history_context = "\n".join(
                        [
                            f"{msg.type}: {msg.content[:100]}..."
                            if len(msg.content) > 100
                            else f"{msg.type}: {msg.content}"
                            for msg in recent_history
                        ]
                    )
                    messages_cls.insert(
                        1, HumanMessage(content=f"Contexte récent: {history_context}")
                    )
                result = self.classifier_llm.invoke(messages_cls)
                needs_rag = result.content.strip().upper() == "OUI"

            final_sources: list[dict] = []

            # Build messages to stream
            if is_non_admin:
                prompt = OUT_OF_SCOPE_RESPONSE_PROMPT.format(question=message)
                stream_messages = [
                    SystemMessage(content=prompt),
                    SystemMessage(
                        content=self._response_language_instruction(detected_language)
                    ),
                ]
            elif not needs_rag:
                # Simple path: trim history and build messages
                history_dicts = self._convert_to_message_dicts(history_messages)
                trimmed_history_dicts, _, _ = (
                    self.message_trimmer.trim_messages_with_summary(
                        history_dicts,
                        system_messages=[{"role": "system", "content": TURGOT_PROMPT}],
                        context_text="Tu réponds sans utiliser de documents de référence. Sois naturel et utile.",
                        summarizer=self._summarize_history,
                    )
                )
                trimmed_history = self._convert_to_langchain_messages(
                    trimmed_history_dicts
                )
                stream_messages = [
                    SystemMessage(content=TURGOT_PROMPT),
                    SystemMessage(
                        content="Tu réponds sans utiliser de documents de référence. Sois naturel et utile."
                    ),
                    SystemMessage(
                        content=self._response_language_instruction(detected_language)
                    ),
                    *trimmed_history,
                    HumanMessage(content=message),
                ]
            else:
                # RAG path: retrieve and format context
                search_query = retrieval_message
                try:
                    search_query = self.retriever.generate_search_query(
                        retrieval_message, history
                    )
                    logger.debug(
                        f"Streaming path generated search query: {search_query}"
                    )
                except Exception as rewrite_err:
                    logger.warning(
                        f"Streaming path query rewrite failed; using raw message: {rewrite_err}"
                    )

                docs = self.retriever.retrieve_documents(
                    search_query, top_k=TOP_K_RETRIEVAL, max_docs=TOP_N_SOURCES
                )
                # Format context + collect sources (inline to avoid dependency on _format_context internal string shape)
                context_lines = ["CONTEXTE - Documents officiels trouvés :\n\n"]
                sources: list[dict] = []
                vosdroits_docs = [
                    d for d in docs if getattr(d, "data_source", None) == "vosdroits"
                ]
                entreprendre_docs = [
                    d for d in docs if getattr(d, "data_source", None) == "entreprendre"
                ]
                other_docs = [
                    d
                    for d in docs
                    if getattr(d, "data_source", None)
                    not in ["vosdroits", "entreprendre"]
                ]
                if vosdroits_docs:
                    context_lines.append(
                        "👤 DOCUMENTS POUR PARTICULIERS (vosdroits) :\n"
                    )
                    for doc in vosdroits_docs:
                        context_lines.append(
                            f"Document {doc.id} (URL: {doc.sp_url}):\n"
                        )
                        context_lines.append("Extraits pertinents:\n")
                        context_lines.append(f"{doc.page_content}\n")
                        context_lines.append("---\n\n")
                        if getattr(doc, "sp_url", None):
                            title = (
                                doc.source_file.split("/")[-1].replace(".xml", "")
                                if getattr(doc, "source_file", None)
                                else doc.sp_url
                            )
                            sources.append(
                                {
                                    "url": doc.sp_url,
                                    "title": title,
                                    "excerpt": (doc.page_content or "")[:220],
                                    "data_source": doc.data_source or "other",
                                }
                            )
                if entreprendre_docs:
                    context_lines.append(
                        "💼 DOCUMENTS POUR PROFESSIONNELS (entreprendre) :\n"
                    )
                    for doc in entreprendre_docs:
                        context_lines.append(
                            f"Document {doc.id} (URL: {doc.sp_url}):\n"
                        )
                        context_lines.append("Extraits pertinents:\n")
                        context_lines.append(f"{doc.page_content}\n")
                        context_lines.append("---\n\n")
                        if getattr(doc, "sp_url", None):
                            title = (
                                doc.source_file.split("/")[-1].replace(".xml", "")
                                if getattr(doc, "source_file", None)
                                else doc.sp_url
                            )
                            sources.append(
                                {
                                    "url": doc.sp_url,
                                    "title": title,
                                    "excerpt": (doc.page_content or "")[:220],
                                    "data_source": doc.data_source or "other",
                                }
                            )
                if other_docs:
                    context_lines.append("📄 AUTRES DOCUMENTS :\n")
                    for doc in other_docs:
                        context_lines.append(
                            f"Document {doc.id} (URL: {doc.sp_url}):\n"
                        )
                        context_lines.append("Extraits pertinents:\n")
                        context_lines.append(f"{doc.page_content}\n")
                        context_lines.append("---\n\n")
                        if getattr(doc, "sp_url", None):
                            title = (
                                doc.source_file.split("/")[-1].replace(".xml", "")
                                if getattr(doc, "source_file", None)
                                else doc.sp_url
                            )
                            sources.append(
                                {
                                    "url": doc.sp_url,
                                    "title": title,
                                    "excerpt": (doc.page_content or "")[:220],
                                    "data_source": doc.data_source or "other",
                                }
                            )
                context_lines.append(
                    "INSTRUCTION: Basez votre réponse UNIQUEMENT sur les informations contenues dans ces documents. "
                )
                context_lines.append(
                    "Si les documents contiennent des informations contradictoires ou incomplètes, mentionnez-le clairement. "
                )
                context_lines.append(
                    "Adaptez votre réponse selon le type de public concerné (particuliers vs professionnels)."
                )
                context_text = "".join(context_lines)
                final_sources = sources

                # Trim history against context and build messages
                system_messages = [
                    {"role": "system", "content": TURGOT_PROMPT},
                    {"role": "system", "content": OUTPUT_PROMPT},
                ]
                history_dicts = self._convert_to_message_dicts(history_messages)
                all_messages = history_dicts + [{"role": "user", "content": message}]
                trimmed_messages, _, _ = (
                    self.message_trimmer.trim_messages_with_summary(
                        all_messages,
                        system_messages=system_messages,
                        context_text=context_text,
                        summarizer=self._summarize_history,
                    )
                )
                trimmed_langchain = self._convert_to_langchain_messages(
                    trimmed_messages[:-1]
                )
                stream_messages = [
                    SystemMessage(content=TURGOT_PROMPT),
                    SystemMessage(content=OUTPUT_PROMPT),
                    SystemMessage(
                        content=self._response_language_instruction(detected_language)
                    ),
                    *trimmed_langchain,
                    HumanMessage(content=message),
                    HumanMessage(content=context_text),
                ]

            # Stream tokens
            final_tokens: list[str] = []
            for chunk in self.llm.stream(stream_messages):
                token = getattr(chunk, "content", None) or ""
                if token:
                    final_tokens.append(token)
                    yield {"type": "chunk", "content": token}

            full_answer = "".join(final_tokens).strip()

            # Store messages with attention note if sources exist
            try:
                self.redis_service.store_message(
                    session_id, {"role": "user", "content": message}
                )
                if final_sources:
                    attention_text = "\n\n### Attention\nCette réponse n'est pas exhaustive, prenez le temps de lire en détail les sources proposées.\n"
                    to_store = full_answer + attention_text
                else:
                    to_store = full_answer
                self.redis_service.store_message(
                    session_id, {"role": "assistant", "content": to_store}
                )
            except Exception as store_err:
                logger.warning(f"Failed to store streamed messages: {store_err}")

            if final_sources:
                yield {"type": "sources", "sources": final_sources}

            yield {"type": "done"}

        except Exception as e:
            logger.error(f"Error in stream_answer: {e}")
            yield {
                "type": "chunk",
                "content": "Désolé, une erreur est survenue. Veuillez réessayer.",
            }
            yield {"type": "done"}
