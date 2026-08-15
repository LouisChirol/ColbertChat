import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

from fastapi import HTTPException
from fastapi.responses import FileResponse
from loguru import logger
from markdown_it import MarkdownIt
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image as RLImage
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.platypus.flowables import HRFlowable

from app.services.redis import RedisService

# Initialize markdown parser
md = MarkdownIt()


class PDFService:
    """Service for generating and managing PDF files."""
    
    def __init__(self):
        self.redis_service = RedisService()
        self.temp_dir = Path(tempfile.gettempdir())
    
    def get_turgot_logo(self) -> str:
        """Get the path to the Turgot logo."""
        # Try to find the logo in the frontend public directory
        workspace_root = Path(__file__).parent.parent.parent.parent
        logo_path = workspace_root / "frontend" / "public" / "turgot_v2.png"

        if not logo_path.exists():
            # Fallback to a default logo if not found
            logger.warning("Turgot logo not found, using default")
            fallback_path = workspace_root / "frontend" / "public" / "turgot_avatar.png"
            if fallback_path.exists():
                return str(fallback_path)
            else:
                logger.warning("No logo found, PDF will be generated without logo")
                return ""

        return str(logo_path)
    
    def convert_markdown_to_paragraphs(self, text: str, prefix: str = "") -> List[Tuple[str, str]]:
        """Convert markdown text to a list of (style_name, text) tuples."""
        md = MarkdownIt()
        tokens = md.parse(text)
        paragraphs = []
        current_style = "Normal"
        current_text = []

        for token in tokens:
            if token.type == "inline":
                # Process inline tokens
                for child in token.children or []:
                    if child.type == "text":
                        current_text.append(child.content)
                    elif child.type == "strong":
                        current_text.append(f"<b>{child.content}</b>")
                    elif child.type == "em":
                        current_text.append(f"<i>{child.content}</i>")
                    elif child.type == "code_inline":
                        if current_text:
                            paragraphs.append((current_style, "".join(current_text)))
                            current_text = []
                        paragraphs.append(("InlineCode", child.content))
                    elif child.type == "link_open":
                        current_text.append(f'<a href="{child.attrs.get("href", "")}">')
                    elif child.type == "link_close":
                        current_text.append("</a>")
            elif token.type == "fence":  # Code block
                if current_text:
                    paragraphs.append((current_style, "".join(current_text)))
                    current_text = []
                paragraphs.append(("CodeBlock", token.content))
            elif token.type == "paragraph_open":
                if current_text:
                    paragraphs.append((current_style, "".join(current_text)))
                    current_text = []
            elif token.type == "paragraph_close":
                if current_text:
                    paragraphs.append((current_style, "".join(current_text)))
                    current_text = []
            elif token.type == "heading_open":
                if current_text:
                    paragraphs.append((current_style, "".join(current_text)))
                    current_text = []
                level = int(token.tag[1])
                current_style = f"Heading{level}"
            elif token.type == "heading_close":
                if current_text:
                    paragraphs.append((current_style, "".join(current_text)))
                    current_text = []
                current_style = "Normal"
            elif token.type == "bullet_list_open":
                if current_text:
                    paragraphs.append((current_style, "".join(current_text)))
                    current_text = []
                current_style = "BulletList"
            elif token.type == "ordered_list_open":
                if current_text:
                    paragraphs.append((current_style, "".join(current_text)))
                    current_text = []
                current_style = "OrderedList"
            elif token.type == "list_item_open":
                if current_text:
                    paragraphs.append((current_style, "".join(current_text)))
                    current_text = []
                current_style = "ListItem"
            elif token.type == "list_item_close":
                if current_text:
                    paragraphs.append((current_style, "".join(current_text)))
                    current_text = []
                current_style = "Normal"
            elif token.type == "blockquote_open":
                if current_text:
                    paragraphs.append((current_style, "".join(current_text)))
                    current_text = []
                current_style = "BlockQuote"
            elif token.type == "blockquote_close":
                if current_text:
                    paragraphs.append((current_style, "".join(current_text)))
                    current_text = []
                current_style = "Normal"
            elif token.type == "hr":
                if current_text:
                    paragraphs.append((current_style, "".join(current_text)))
                    current_text = []
                paragraphs.append(("HorizontalRule", ""))

        if current_text:
            paragraphs.append((current_style, "".join(current_text)))

        return paragraphs
    
    def create_pdf_from_markdown(self, markdown_content: str, title: str = "Document Turgot") -> Path:
        """Create a PDF from markdown content."""
        try:
            # Create a temporary file for the PDF
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            pdf_path = self.temp_dir / f"turgot_document_{timestamp}.pdf"

            # Create the PDF document
            doc = SimpleDocTemplate(
                str(pdf_path),
                pagesize=A4,
                rightMargin=72,
                leftMargin=72,
                topMargin=72,
                bottomMargin=72,
            )

            # Create styles
            styles = getSampleStyleSheet()
            self._add_custom_styles(styles)

            # Build the PDF content
            story = []

            # Add logo and title
            logo_path = self.get_turgot_logo()
            if logo_path and os.path.exists(logo_path):
                img = PILImage.open(logo_path)
                img_width, img_height = img.size
                aspect = img_height / float(img_width)
                img_width = 2 * inch
                img_height = img_width * aspect
                story.append(RLImage(logo_path, width=img_width, height=img_height))
                story.append(Spacer(1, 20))

            # Add title
            title_style = ParagraphStyle(
                "Title",
                parent=styles["Heading1"],
                fontSize=24,
                spaceAfter=30,
                alignment=1,  # Center alignment
            )
            story.append(Paragraph(title, title_style))
            story.append(Spacer(1, 20))

            # Convert markdown to paragraphs and add to story
            paragraphs = self.convert_markdown_to_paragraphs(markdown_content)
            
            for style_name, text in paragraphs:
                if not text.strip():
                    continue
                    
                if style_name == "CodeBlock":
                    # Create a table for code blocks to have a nice background
                    table_data = [[Paragraph(text, styles.get(style_name, styles["Code"]))]]
                    table = Table(table_data, colWidths=[doc.width - 40])
                    table.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#F3F4F6")),
                        ('BORDER', (0, 0), (-1, -1), 1, colors.HexColor("#E5E7EB")),
                        ('PADDING', (0, 0), (-1, -1), 6),
                    ]))
                    story.append(table)
                elif style_name == "HorizontalRule":
                    story.append(HRFlowable(width="100%", thickness=1, color=colors.gray))
                else:
                    story.append(Paragraph(text, styles.get(style_name, styles["Normal"])))
                story.append(Spacer(1, 6))

            # Build the PDF
            doc.build(story)
            logger.info(f"PDF created successfully: {pdf_path}")
            return pdf_path

        except Exception as e:
            logger.error(f"Error creating PDF from markdown: {str(e)}")
            raise HTTPException(status_code=500, detail="Error creating PDF")
    
    def _add_custom_styles(self, styles):
        """Add custom styles for PDF generation."""
        styles.add(
            ParagraphStyle(
                name="InlineCode",
                parent=styles["Code"],
                fontName="Courier",
                fontSize=9,
                textColor=colors.HexColor("#1F2937"),
                backColor=colors.HexColor("#F3F4F6"),
                borderWidth=0,
                borderColor=colors.HexColor("#E5E7EB"),
                borderRadius=2,
                borderPadding=2,
            )
        )
        styles.add(
            ParagraphStyle(
                name="CodeBlock",
                parent=styles["Code"],
                fontName="Courier",
                fontSize=9,
                textColor=colors.HexColor("#1F2937"),
                backColor=colors.HexColor("#F3F4F6"),
                borderWidth=1,
                borderColor=colors.HexColor("#E5E7EB"),
                borderRadius=4,
                borderPadding=6,
                spaceBefore=6,
                spaceAfter=6,
            )
        )
    
    def serve_pdf(self, filename: str) -> FileResponse:
        """Serve a PDF file."""
        # Defense in depth against path traversal: only allow a bare filename.
        safe_filename = Path(filename).name
        pdf_path = self.temp_dir / safe_filename
        
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {filename}")
        
        return FileResponse(
            path=str(pdf_path),
            media_type="application/pdf",
            filename=filename
        )
    
    def cleanup_file(self, file_path: Path, delay: int = 0):
        """Delete the file after a delay (in seconds)."""
        def _cleanup():
            if delay > 0:
                time.sleep(delay)
            try:
                if file_path.exists():
                    file_path.unlink()
                    logger.info(f"Deleted PDF file: {file_path}")
            except Exception as e:
                logger.error(f"Error deleting PDF file: {str(e)}")
        _cleanup()


# Backward compatibility functions
def get_turgot_logo() -> str:
    """Backward compatibility function."""
    service = PDFService()
    return service.get_turgot_logo()


def convert_markdown_to_paragraphs(text: str, prefix: str = "") -> List[Tuple[str, str]]:
    """Backward compatibility function."""
    service = PDFService()
    return service.convert_markdown_to_paragraphs(text, prefix)


def create_chat_pdf(session_id: str) -> Path:
    """Create a PDF file from the chat history of a session."""
    # Note: This function is kept for backward compatibility but should be updated
    # to use the new PDFService class methods
    try:
        # Get chat history from Redis
        redis_service = RedisService()
        history = redis_service.get_history(session_id)
        logger.info(f"Fetched {len(history.messages)} messages for session {session_id}")
        if not history.messages:
            raise HTTPException(
                status_code=404, detail="No chat history found for this session"
            )

        # Create a temporary file for the PDF
        temp_dir = Path(tempfile.gettempdir())
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pdf_path = temp_dir / f"turgot_chat_{session_id}_{timestamp}.pdf"

        # Create the PDF document
        doc = SimpleDocTemplate(
            str(pdf_path),
            pagesize=A4,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=72,
        )

        # Create styles
        styles = getSampleStyleSheet()
        styles.add(
            ParagraphStyle(
                name="UserMessage",
                parent=styles["Normal"],
                textColor=colors.HexColor("#1E40AF"),  # Blue-800
                fontSize=10,
                spaceAfter=12,
                leftIndent=20,
            )
        )
        styles.add(
            ParagraphStyle(
                name="AssistantMessage",
                parent=styles["Normal"],
                textColor=colors.HexColor("#1F2937"),  # Gray-800
                fontSize=10,
                spaceAfter=12,
                leftIndent=20,
            )
        )
        styles.add(
            ParagraphStyle(
                name="InlineCode",
                parent=styles["Code"],
                fontName="Courier",
                fontSize=9,
                textColor=colors.HexColor("#1F2937"),  # Gray-800
                backColor=colors.HexColor("#F3F4F6"),  # Gray-100
                borderWidth=0,
                borderColor=colors.HexColor("#E5E7EB"),  # Gray-200
                borderRadius=2,
                borderPadding=2,
            )
        )
        styles.add(
            ParagraphStyle(
                name="CodeBlock",
                parent=styles["Code"],
                fontName="Courier",
                fontSize=9,
                textColor=colors.HexColor("#1F2937"),  # Gray-800
                backColor=colors.HexColor("#F3F4F6"),  # Gray-100
                borderWidth=1,
                borderColor=colors.HexColor("#E5E7EB"),  # Gray-200
                borderRadius=4,
                borderPadding=6,
                spaceBefore=6,
                spaceAfter=6,
            )
        )
        styles.add(
            ParagraphStyle(
                name="Timestamp",
                parent=styles["Normal"],
                textColor=colors.gray,
                fontSize=8,
                spaceAfter=12,
            )
        )
        styles.add(
            ParagraphStyle(
                name="ListItem",
                parent=styles["Normal"],
                leftIndent=20,
                bulletIndent=10,
                spaceBefore=3,
                spaceAfter=3,
            )
        )
        styles.add(
            ParagraphStyle(
                name="NumberedListItem",
                parent=styles["Normal"],
                leftIndent=20,
                bulletIndent=10,
                spaceBefore=3,
                spaceAfter=3,
            )
        )
        styles.add(
            ParagraphStyle(
                name="Blockquote",
                parent=styles["Normal"],
                leftIndent=20,
                rightIndent=20,
                textColor=colors.HexColor("#6B7280"),  # Gray-500
                borderWidth=1,
                borderColor=colors.HexColor("#E5E7EB"),  # Gray-200
                borderPadding=5,
                borderRadius=4,
            )
        )
        styles.add(
            ParagraphStyle(
                name="Link",
                parent=styles["Normal"],
                textColor=colors.HexColor("#2563EB"),  # Blue-600
                underline=True,
            )
        )

        # Build the PDF content
        story = []

        # Add logo and title
        logo_path = get_turgot_logo()
        if logo_path and os.path.exists(logo_path):
            img = PILImage.open(logo_path)
            img_width, img_height = img.size
            aspect = img_height / float(img_width)
            img_width = 2 * inch
            img_height = img_width * aspect
            story.append(RLImage(logo_path, width=img_width, height=img_height))
            story.append(Spacer(1, 20))

        # Add title
        title_style = ParagraphStyle(
            "Title",
            parent=styles["Heading1"],
            fontSize=24,
            spaceAfter=30,
            alignment=1,  # Center alignment
        )
        story.append(Paragraph("Conversation avec Turgot", title_style))
        story.append(Spacer(1, 20))

        # Add disclaimer
        disclaimer_style = ParagraphStyle(
            "Disclaimer",
            parent=styles["Normal"],
            fontSize=9,
            textColor=colors.gray,
            spaceAfter=20,
            alignment=1,  # Center alignment
        )
        story.append(
            Paragraph(
                "Cette conversation est un résumé généré automatiquement. "
                "Les informations fournies doivent être vérifiées auprès des sources officielles.",
                disclaimer_style,
            )
        )
        story.append(Spacer(1, 20))

        # Add messages
        for msg in history.messages:
            logger.info(f"Processing message type: {msg.type}, content length: {len(msg.content) if msg.content else 0}")
            logger.info(f"Message content: {repr(msg.content[:100])}...")  # First 100 chars
            
            # Add timestamp
            timestamp = datetime.now().strftime("%d/%m/%Y %H:%M")
            story.append(Paragraph(timestamp, styles["Timestamp"]))

            # Add message content with markdown support
            if msg.type == "human":
                prefix = "Vous: "
                style_base = "UserMessage"
            else:
                prefix = "Turgot: "
                style_base = "AssistantMessage"

            # Convert markdown to paragraphs
            paragraphs = convert_markdown_to_paragraphs(msg.content, prefix)
            logger.info(f"Converted to {len(paragraphs)} paragraphs")

            # Add each paragraph with appropriate styling
            for i, (style_name, text) in enumerate(paragraphs):
                logger.info(f"  Paragraph {i+1}: style='{style_name}', text='{repr(text[:50])}...'")
                if style_name == "CodeBlock":
                    # Create a table for code blocks to have a nice background
                    table_data = [[Paragraph(text, styles[style_name])]]
                    table = Table(table_data, colWidths=[doc.width - 40])

                    # Define table style for better formatting
                    table.setStyle(
                        TableStyle(
                            [
                                ("BACKGROUND", (0, 0), (-1, -1), colors.lightgrey),
                                ("BORDER", (0, 0), (-1, -1), 1, colors.black),
                                ("PADDING", (0, 0), (-1, -1), 6),
                            ]
                        )
                    )
                    story.append(table)
                elif style_name == "HorizontalRule":
                    story.append(HRFlowable(width="100%", thickness=1, color=colors.gray))
                else:
                    # Use fallback style if the requested style doesn't exist
                    actual_style = styles.get(style_base, styles["Normal"])
                    story.append(Paragraph(f"{prefix}{text}", actual_style))
                story.append(Spacer(1, 6))

        logger.info(f"Total story elements: {len(story)}")

        # Check if story has valid elements
        valid_elements = 0
        for i, element in enumerate(story):
            if element is not None:
                valid_elements += 1
            else:
                logger.warning(f"Story element {i} is None")
        logger.info(f"Valid story elements: {valid_elements}")

        # Build the PDF
        try:
            doc.build(story)
            logger.info(f"PDF built successfully with {len(story)} elements")
        except Exception as build_error:
            logger.error(f"Error building PDF: {str(build_error)}")
            logger.exception("PDF build error traceback:")
            raise HTTPException(status_code=500, detail=f"Error building PDF: {str(build_error)}")

        logger.info(f"PDF created: {pdf_path}")
        
        # Check if the PDF file was actually created and has content
        if pdf_path.exists():
            file_size = pdf_path.stat().st_size
            logger.info(f"PDF file size: {file_size} bytes")
            if file_size == 0:
                logger.error("PDF file is empty (0 bytes)")
                raise HTTPException(status_code=500, detail="Generated PDF file is empty")
        else:
            logger.error("PDF file was not created")
            raise HTTPException(status_code=500, detail="PDF file was not created")
            
        return pdf_path

    except Exception as e:
        logger.error(f"Error creating PDF: {str(e)}")
        logger.exception("Full traceback:")
        raise HTTPException(status_code=500, detail=f"Error creating PDF: {str(e)}")
