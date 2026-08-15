import json
import os
import time
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from app.core.graph_agent import TurgotGraphAgent
from app.services.document_upload import (
    MAX_UPLOAD_BYTES,
    MAX_UPLOAD_PAGES,
    estimate_pdf_page_count,
)
from app.services.feedback_store import FeedbackStore
from app.services.pdf import PDFService
from app.services.transcription import TranscriptionService
from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from loguru import logger
from prometheus_client import Counter, Histogram
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

# Environment mode: production disables interactive docs and enforces
# stricter CORS. Set ENVIRONMENT=development locally to relax both.
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")
IS_PRODUCTION = ENVIRONMENT == "production"

# Max size (bytes) accepted for audio transcription uploads.
MAX_AUDIO_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB

# Allowed browser origins for the production frontend.
ALLOWED_ORIGINS = [
    "https://turgotchat.fr",
    "https://www.turgotchat.fr",
    "https://turgot.louischirol.fr",
]

# Session cache for aggregate usage metrics (process-local only).
SEEN_SESSIONS: set[str] = set()

SESSIONS_STARTED_TOTAL = Counter(
    "turgot_sessions_started_total",
    "Total number of unique sessions seen by this backend process.",
)
MESSAGES_TOTAL = Counter(
    "turgot_messages_total",
    "Total number of processed chat messages.",
    ["endpoint"],
)
TOKENS_TOTAL = Counter(
    "turgot_tokens_total",
    "Approximate token usage by direction.",
    ["direction"],
)
QUERY_LATENCY_SECONDS = Histogram(
    "turgot_query_latency_seconds",
    "Query latency in seconds by query type.",
    ["query_type", "endpoint"],
)


def _estimate_tokens(text: str) -> int:
    """Use a lightweight approximation for aggregate token metrics."""
    if not text:
        return 0
    return max(1, len(text) // 4)

def get_client_ip(request: Request) -> str:
    """
    Resolve the real client IP.

    The backend sits behind nginx (reverse proxy on the same host), so
    `request.client.host` is always nginx's own
    loopback connection, not the visitor's IP. Without this, every visitor
    would share a single rate-limit bucket. Nginx sets X-Forwarded-For, so
    use its left-most (original client) entry instead.
    """
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


limiter = Limiter(key_func=get_client_ip)

# Configure logging
logger.remove()  # Remove default handler
logger.add(
    "logs/turgot_backend.log",
    rotation="10 MB",
    retention="30 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
    backtrace=True,
    diagnose=True,
)
# Also add console output for development/debugging
logger.add(
    lambda msg: print(msg, end=""),
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
)


# Models
class QuestionRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: str = Field(..., min_length=1, max_length=200)


class QuestionResponse(BaseModel):
    answer: str
    session_id: str


class PDFRequest(BaseModel):
    text: Optional[str] = Field(None, max_length=50000)
    title: Optional[str] = Field(None, max_length=200)
    session_id: Optional[str] = Field(None, max_length=200)


class PDFResponse(BaseModel):
    pdf_url: str


class ClearSessionRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=200)


class ClearSessionResponse(BaseModel):
    success: bool
    message: str


class LastUpdateResponse(BaseModel):
    last_update: str


class TranscriptionResponse(BaseModel):
    text: str
    success: bool


class FeedbackRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=200)
    message_id: str = Field(..., min_length=1, max_length=200)
    value: int = Field(..., ge=-1, le=1)
    message_excerpt: Optional[str] = Field(None, max_length=500)


class FeedbackResponse(BaseModel):
    success: bool
    message: str


class DocumentUploadResponse(BaseModel):
    success: bool
    filename: str
    pages: int
    message: str


# Global agent instance
agent = None
feedback_store = FeedbackStore()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global agent
    logger.info("Starting Turgot backend...")
    agent = TurgotGraphAgent()
    logger.info("Turgot agent initialized")
    yield
    # Shutdown
    logger.info("Shutting down Turgot backend...")


# Create FastAPI app
app = FastAPI(
    title="Turgot API",
    description="RAG-powered chatbot for French public administration information",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)

# Rate limiting: protects paid Mistral/Voxtral calls from abuse.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if not IS_PRODUCTION else ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Must register before workers finish startup; agent init in lifespan can take 30s+.
Instrumentator().instrument(app).expose(
    app, endpoint="/metrics", include_in_schema=False
)


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"message": "Turgot API is running"}


@app.post("/chat", response_model=QuestionResponse)
@limiter.limit("15/minute")
async def chat(request: Request, body: QuestionRequest):
    """
    Process a chat message and return Turgot's response.

    Args:
        body: Contains the user message and session ID

    Returns:
        The response from Turgot including the answer and session ID
    """
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    try:
        logger.info(f"Processing question from session {body.session_id}")
        start_time = time.time()
        MESSAGES_TOTAL.labels(endpoint="chat").inc()
        if body.session_id not in SEEN_SESSIONS:
            SESSIONS_STARTED_TOTAL.inc()
            SEEN_SESSIONS.add(body.session_id)
        TOKENS_TOTAL.labels(direction="input").inc(_estimate_tokens(body.message))

        # Get response from agent
        result = agent.ask_turgot_with_metadata(body.message, body.session_id)
        answer = result["answer"]

        end_time = time.time()
        query_type = result.get("query_type", "unknown")
        QUERY_LATENCY_SECONDS.labels(query_type=query_type, endpoint="chat").observe(
            end_time - start_time
        )
        output_tokens = result.get("total_tokens", 0) or _estimate_tokens(answer)
        TOKENS_TOTAL.labels(direction="output").inc(output_tokens)
        logger.info(f"Question processed in {end_time - start_time:.2f} seconds")

        return QuestionResponse(answer=answer, session_id=body.session_id)

    except Exception as e:
        logger.error(f"Error processing question: {str(e)}")
        logger.exception("Full traceback:")
        raise HTTPException(
            status_code=500, detail="Erreur lors du traitement de votre question"
        )


@app.post("/chat-stream")
@limiter.limit("15/minute")
async def chat_stream(request: Request, body: QuestionRequest):
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    logger.info(f"Starting stream for session {body.session_id}")
    start_time = time.time()
    MESSAGES_TOTAL.labels(endpoint="chat_stream").inc()
    if body.session_id not in SEEN_SESSIONS:
        SESSIONS_STARTED_TOTAL.inc()
        SEEN_SESSIONS.add(body.session_id)
    TOKENS_TOTAL.labels(direction="input").inc(_estimate_tokens(body.message))

    def event_generator():
        accumulated_tokens = 0
        try:
            for item in agent.stream_answer(body.message, body.session_id):
                if item.get("type") == "chunk":
                    accumulated_tokens += _estimate_tokens(item.get("content", ""))
                yield f"data: {json.dumps(item)}\n\n"
        except Exception as e:
            logger.error(f"Streaming error: {e}")
            yield f"data: {json.dumps({'type': 'chunk', 'content': 'Désolé, une erreur est survenue. Veuillez réessayer.'})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        finally:
            duration = time.time() - start_time
            QUERY_LATENCY_SECONDS.labels(
                query_type="stream", endpoint="chat_stream"
            ).observe(duration)
            if accumulated_tokens > 0:
                TOKENS_TOTAL.labels(direction="output").inc(accumulated_tokens)
            logger.info(
                f"Stream finished in {duration:.2f} seconds for session {body.session_id}"
            )

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/feedback", response_model=FeedbackResponse)
@limiter.limit("30/minute")
async def submit_feedback(request: Request, body: FeedbackRequest):
    """Persist thumbs up/down feedback for assistant messages."""
    if body.value not in (-1, 1):
        raise HTTPException(status_code=422, detail="value must be -1 or 1")

    try:
        feedback_store.save_feedback(
            session_id=body.session_id,
            message_id=body.message_id,
            value=body.value,
            message_excerpt=body.message_excerpt or "",
        )
        return FeedbackResponse(success=True, message="Feedback enregistré")
    except Exception as e:
        logger.error(f"Error storing feedback: {str(e)}")
        logger.exception("Full traceback:")
        raise HTTPException(
            status_code=500, detail="Erreur lors de l'enregistrement du feedback"
        )


@app.post("/document-upload", response_model=DocumentUploadResponse)
@limiter.limit("2/minute")
async def document_upload(
    request: Request,
    consent_confirmed: bool = Form(...),
    document: UploadFile = File(...),
):
    """
    Phase 4 skeleton endpoint:
    - strict size/page limits
    - in-memory processing only
    - no persistent storage
    """
    try:
        if not consent_confirmed:
            raise HTTPException(
                status_code=400,
                detail="Consentement obligatoire avant l'envoi d'un document",
            )

        filename = document.filename or "document.pdf"
        if not filename.lower().endswith(".pdf"):
            raise HTTPException(
                status_code=415, detail="Seuls les fichiers PDF sont acceptés"
            )

        payload = await document.read()
        if len(payload) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Fichier trop volumineux (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)",
            )

        if not payload.startswith(b"%PDF"):
            raise HTTPException(status_code=400, detail="Fichier PDF invalide")

        page_count = estimate_pdf_page_count(payload)
        if page_count > MAX_UPLOAD_PAGES:
            raise HTTPException(
                status_code=413,
                detail=f"Document trop long (max {MAX_UPLOAD_PAGES} pages)",
            )

        # Intentionally no disk storage and no model call yet (skeleton scope).
        return DocumentUploadResponse(
            success=True,
            filename=filename,
            pages=page_count,
            message=(
                "Document validé pour traitement en mémoire uniquement. "
                "Le pipeline d'analyse sera ajouté dans une prochaine phase."
            ),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during document upload: {str(e)}")
        logger.exception("Full traceback:")
        raise HTTPException(status_code=500, detail="Erreur lors du traitement du document")


@app.post("/generate-pdf", response_model=PDFResponse)
@limiter.limit("10/minute")
async def generate_pdf(
    request: Request, body: PDFRequest, background_tasks: BackgroundTasks
):
    """
    Generate a PDF from markdown text or chat session.

    Args:
        body: Contains either text content and optional title, or session_id
        background_tasks: FastAPI background tasks

    Returns:
        URL to access the generated PDF
    """
    try:
        pdf_service = PDFService()

        # Check if this is a session-based request
        if body.session_id and not body.text:
            # Generate PDF from chat session
            from app.services.pdf import create_chat_pdf

            pdf_path = create_chat_pdf(body.session_id)
        elif body.text:
            # Generate PDF from markdown text
            pdf_path = pdf_service.create_pdf_from_markdown(
                markdown_content=body.text, title=body.title or "Document Turgot"
            )
        else:
            raise HTTPException(
                status_code=422, detail="Either 'text' or 'session_id' must be provided"
            )

        # Schedule cleanup after 1 hour
        background_tasks.add_task(pdf_service.cleanup_file, pdf_path, delay=3600)

        # Return public URL
        pdf_filename = os.path.basename(pdf_path)
        pdf_url = f"/pdfs/{pdf_filename}"

        logger.info(f"Generated PDF: {pdf_filename}")

        return PDFResponse(pdf_url=pdf_url)

    except HTTPException:
        # Re-raise HTTPExceptions as-is (like 404 for no chat history)
        raise
    except Exception as e:
        logger.error(f"Error generating PDF: {str(e)}")
        logger.exception("Full traceback:")
        raise HTTPException(
            status_code=500, detail="Erreur lors de la génération du PDF"
        )


@app.get("/pdfs/{filename}")
async def get_pdf(filename: str):
    """
    Serve generated PDF files.

    Args:
        filename: The PDF filename to serve

    Returns:
        The PDF file content
    """
    try:
        # Defense in depth: strip any directory components even though
        # FastAPI's default path converter already rejects raw slashes.
        safe_filename = os.path.basename(filename)
        pdf_service = PDFService()
        return pdf_service.serve_pdf(safe_filename)

    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="PDF not found")
    except Exception as e:
        logger.error(f"Error serving PDF: {str(e)}")
        raise HTTPException(status_code=500, detail="Error serving PDF")


@app.post("/clear-session", response_model=ClearSessionResponse)
@limiter.limit("20/minute")
async def clear_session(request: Request, body: ClearSessionRequest):
    """
    Clear the chat history for a specific session.

    Args:
        body: Contains the session ID to clear

    Returns:
        Success status and message
    """
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    try:
        logger.info(f"Clearing session history for session {body.session_id}")

        # Clear the session history using the Redis service
        agent.redis_service.clear_session_history(body.session_id)

        return ClearSessionResponse(
            success=True, message=f"Session {body.session_id} cleared successfully"
        )

    except Exception as e:
        logger.error(f"Error clearing session: {str(e)}")
        logger.exception("Full traceback:")
        raise HTTPException(
            status_code=500, detail="Erreur lors de la suppression de la session"
        )


@app.post("/transcribe", response_model=TranscriptionResponse)
@limiter.limit("10/minute")
async def transcribe_audio(request: Request, audio: bytes = File(...)):
    """
    Transcribe audio to text using Voxtral API.

    Args:
        audio: Raw audio file data

    Returns:
        Transcribed text
    """
    if len(audio) > MAX_AUDIO_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Audio file too large (max {MAX_AUDIO_UPLOAD_BYTES // (1024 * 1024)} MB)",
        )

    try:
        logger.info("Starting audio transcription")

        # Initialize transcription service
        transcription_service = TranscriptionService()

        # Transcribe audio (assuming MP3 format for now)
        transcribed_text = transcription_service.transcribe_audio(audio, "mp3")

        logger.info(f"Transcription completed: {len(transcribed_text)} characters")

        return TranscriptionResponse(text=transcribed_text, success=True)

    except HTTPException:
        # Re-raise HTTPExceptions as-is
        raise
    except Exception as e:
        logger.error(f"Error during transcription: {str(e)}")
        logger.exception("Full traceback:")
        raise HTTPException(
            status_code=500, detail="Erreur lors de la transcription audio"
        )


@app.get("/last-update", response_model=LastUpdateResponse)
async def get_last_update():
    """
    Get the last update date of the database.

    Returns:
        The last update date from the database
    """
    try:
        # Read the last update file from the database directory
        from pathlib import Path

        # Get the database path (same logic as in retrieval service)
        if os.path.exists("/.dockerenv"):  # Docker environment
            last_update_path = Path("/app/database/last_update.txt")
        else:  # Local development
            workspace_root = Path(__file__).parent.parent.parent.parent
            last_update_path = workspace_root / "database" / "last_update.txt"

        if last_update_path.exists():
            with open(last_update_path, "r", encoding="utf-8") as f:
                last_update = f.read().strip()
        else:
            logger.warning(f"Last update file not found at {last_update_path}")
            last_update = "Date non disponible"

        return LastUpdateResponse(last_update=last_update)

    except Exception as e:
        logger.error(f"Error reading last update: {str(e)}")
        logger.exception("Full traceback:")
        raise HTTPException(
            status_code=500,
            detail="Erreur lors de la lecture de la date de mise à jour",
        )


if __name__ == "__main__":
    # Configure logging
    logger.info("Starting Turgot API server...")

    # Run the server
    uvicorn.run(
        "app.api.main:app", host="0.0.0.0", port=8000, reload=True, log_level="info"
    )
