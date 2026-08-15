from typing import Any, Callable, Dict, List, Tuple

from loguru import logger

try:
    from mistral_common.protocol.instruct.messages import (
        AssistantMessage,
        SystemMessage,
        UserMessage,
    )
    from mistral_common.protocol.instruct.request import ChatCompletionRequest
    from mistral_common.tokens.tokenizers.mistral import MistralTokenizer

    MISTRAL_TOKENIZER_AVAILABLE = True
except ImportError:
    logger.warning(
        "mistral-common not available, falling back to approximate token counting"
    )
    MISTRAL_TOKENIZER_AVAILABLE = False


class TokenCounter:
    """Token counter for Mistral AI models."""

    def __init__(self, model_name: str = "mistral-medium-latest"):
        self.model_name = model_name
        self.tokenizer = None

        if MISTRAL_TOKENIZER_AVAILABLE:
            try:
                # Use v3 tokenizer for latest models
                self.tokenizer = MistralTokenizer.v3()
                logger.info(f"Initialized Mistral tokenizer v3 for {model_name}")
            except Exception as e:
                logger.warning(f"Failed to initialize Mistral tokenizer: {e}")
                self.tokenizer = None

        # Fallback token estimation (approximate)
        self.chars_per_token = 4  # Average characters per token for Western languages

    def count_tokens_in_text(self, text: str) -> int:
        """Count tokens in a single text string."""
        if not text:
            return 0

        if self.tokenizer:
            try:
                # Use official tokenizer for accurate count
                tokens = self.tokenizer.encode_chat_completion(
                    ChatCompletionRequest(
                        messages=[UserMessage(content=text)],
                        model=self.model_name,
                    )
                ).tokens
                return len(tokens)
            except Exception as e:
                logger.warning(f"Error using Mistral tokenizer: {e}")

        # Fallback to character-based estimation
        return max(1, len(text) // self.chars_per_token)

    def count_tokens_in_messages(self, messages: List[Dict[str, Any]]) -> int:
        """Count total tokens in a list of messages."""
        if not messages:
            return 0

        if self.tokenizer:
            try:
                # Convert messages to Mistral format
                mistral_messages = []
                for msg in messages:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")

                    if role == "system":
                        mistral_messages.append(SystemMessage(content=content))
                    elif role == "assistant":
                        mistral_messages.append(AssistantMessage(content=content))
                    else:  # user or any other role
                        mistral_messages.append(UserMessage(content=content))

                # Count tokens using official tokenizer
                tokens = self.tokenizer.encode_chat_completion(
                    ChatCompletionRequest(
                        messages=mistral_messages,
                        model=self.model_name,
                    )
                ).tokens
                return len(tokens)
            except Exception as e:
                logger.warning(f"Error counting tokens in messages: {e}")

        # Fallback: sum individual message tokens
        total_tokens = 0
        for msg in messages:
            content = msg.get("content", "")
            total_tokens += self.count_tokens_in_text(content)
            # Add small overhead for role/formatting tokens
            total_tokens += 10

        return total_tokens

    def estimate_message_tokens(self, role: str, content: str) -> int:
        """Estimate tokens for a single message including role overhead."""
        content_tokens = self.count_tokens_in_text(content)
        # Add overhead for role, formatting, and control tokens
        role_overhead = 10 if role == "system" else 5
        return content_tokens + role_overhead


class MessageTrimmer:
    """Trims message history to fit within token limits."""

    def __init__(self, token_counter: TokenCounter, max_tokens: int = 30000):
        self.token_counter = token_counter
        self.max_tokens = max_tokens
        self.reserved_tokens = 2000  # Reserve tokens for system prompt, context, etc.
        self.available_tokens = max_tokens - self.reserved_tokens

        logger.info(
            f"Initialized MessageTrimmer with {max_tokens} max tokens, {self.available_tokens} available for history"
        )

    def trim_messages(
        self,
        messages: List[Dict[str, Any]],
        system_messages: List[Dict[str, Any]] = None,
        context_text: str = "",
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Trim messages to fit within token limit.

        Strategy:
        1. Always keep system messages (highest priority)
        2. Always keep the latest user message (current query)
        3. Trim from the start of history, keeping recent context
        4. Preserve conversation pairs when possible

        Args:
            messages: List of conversation messages
            system_messages: List of system messages (always kept)
            context_text: Additional context text to account for

        Returns:
            Tuple of (trimmed_messages, total_tokens_used)
        """
        if not messages:
            return [], 0

        # Calculate tokens for system messages and context
        system_tokens = 0
        if system_messages:
            system_tokens = self.token_counter.count_tokens_in_messages(system_messages)

        context_tokens = (
            self.token_counter.count_tokens_in_text(context_text) if context_text else 0
        )

        # Calculate available tokens for conversation history
        available_for_history = self.available_tokens - system_tokens - context_tokens

        if available_for_history <= 0:
            logger.warning(
                "No tokens available for conversation history after system messages and context"
            )
            return [], system_tokens + context_tokens

        # Start from the end (most recent) and work backwards
        trimmed_messages = []
        current_tokens = 0

        # Process messages in reverse order (newest first)
        for i, message in enumerate(reversed(messages)):
            message_tokens = self.token_counter.estimate_message_tokens(
                message.get("role", "user"), message.get("content", "")
            )

            # Check if adding this message would exceed the limit
            if current_tokens + message_tokens > available_for_history:
                # If this is the first message (latest), we must include it
                if i == 0:
                    logger.warning(
                        f"Latest message ({message_tokens} tokens) exceeds available space ({available_for_history} tokens)"
                    )
                    # Truncate the message content to fit
                    message_copy = message.copy()
                    available_for_message = (
                        available_for_history - 10
                    )  # Reserve for role overhead
                    if available_for_message > 0:
                        content = message.get("content", "")
                        # Rough truncation based on character ratio
                        chars_to_keep = (
                            available_for_message * self.token_counter.chars_per_token
                        )
                        if len(content) > chars_to_keep:
                            truncated_content = content[: int(chars_to_keep)] + "..."
                            message_copy["content"] = truncated_content
                            logger.info(
                                f"Truncated latest message from {len(content)} to {len(truncated_content)} characters"
                            )

                    trimmed_messages.append(message_copy)
                    current_tokens = available_for_history
                else:
                    # Stop adding older messages
                    logger.info(
                        f"Stopped trimming at message {i}, would exceed token limit"
                    )
                break

            trimmed_messages.append(message)
            current_tokens += message_tokens

        # Reverse back to original order
        trimmed_messages.reverse()

        total_tokens = system_tokens + context_tokens + current_tokens

        logger.info("Message trimming completed:")
        logger.info(f"  Original messages: {len(messages)}")
        logger.info(f"  Trimmed messages: {len(trimmed_messages)}")
        logger.info(f"  System tokens: {system_tokens}")
        logger.info(f"  Context tokens: {context_tokens}")
        logger.info(f"  History tokens: {current_tokens}")
        logger.info(f"  Total tokens: {total_tokens}/{self.max_tokens}")

        return trimmed_messages, total_tokens

    def trim_messages_with_summary(
        self,
        messages: List[Dict[str, Any]],
        system_messages: List[Dict[str, Any]] = None,
        context_text: str = "",
        summarizer: Callable[[List[Dict[str, Any]]], str] | None = None,
        summary_role: str = "system",
    ) -> Tuple[List[Dict[str, Any]], int, bool]:
        """
        Trim messages and optionally summarize dropped history.

        Returns:
            Tuple of (trimmed_messages, total_tokens_used, summary_added)
        """
        trimmed_messages, total_tokens = self.trim_messages(
            messages=messages, system_messages=system_messages, context_text=context_text
        )

        dropped_count = max(0, len(messages) - len(trimmed_messages))
        if dropped_count == 0 or not summarizer:
            return trimmed_messages, total_tokens, False

        dropped_messages = messages[:dropped_count]
        try:
            summary = summarizer(dropped_messages)
        except Exception as e:
            logger.warning(f"Failed to summarize dropped messages: {e}")
            return trimmed_messages, total_tokens, False

        summary = (summary or "").strip()
        if not summary:
            return trimmed_messages, total_tokens, False

        summary_message = {
            "role": summary_role,
            "content": (
                "Résumé des échanges précédents (mémoire conversationnelle):\n"
                f"{summary}"
            ),
        }

        summary_tokens = self.token_counter.estimate_message_tokens(
            summary_role, summary_message["content"]
        )
        # Keep latest context over summary if there is no space left.
        if total_tokens + summary_tokens > self.max_tokens:
            logger.info("Skipping memory summary because token budget is exhausted")
            return trimmed_messages, total_tokens, False

        merged_messages = [summary_message, *trimmed_messages]
        return merged_messages, total_tokens + summary_tokens, True

    def get_token_stats(self, messages: List[Dict[str, Any]]) -> Dict[str, int]:
        """Get detailed token statistics for a list of messages."""
        if not messages:
            return {"total": 0, "by_role": {}}

        stats = {"total": 0, "by_role": {}}

        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")
            tokens = self.token_counter.estimate_message_tokens(role, content)

            stats["total"] += tokens
            stats["by_role"][role] = stats["by_role"].get(role, 0) + tokens

        return stats


# Convenience functions for easy usage
def create_token_counter(model_name: str = "mistral-medium-latest") -> TokenCounter:
    """Create a token counter instance."""
    return TokenCounter(model_name)


def create_message_trimmer(
    max_tokens: int = 30000, model_name: str = "mistral-medium-latest"
) -> MessageTrimmer:
    """Create a message trimmer instance."""
    token_counter = create_token_counter(model_name)
    return MessageTrimmer(token_counter, max_tokens)


def count_tokens(text: str, model_name: str = "mistral-medium-latest") -> int:
    """Quick function to count tokens in text."""
    counter = create_token_counter(model_name)
    return counter.count_tokens_in_text(text)


def trim_messages_to_limit(
    messages: List[Dict[str, Any]],
    max_tokens: int = 30000,
    model_name: str = "mistral-medium-latest",
) -> Tuple[List[Dict[str, Any]], int]:
    """Quick function to trim messages to token limit."""
    trimmer = create_message_trimmer(max_tokens, model_name)
    return trimmer.trim_messages(messages)
