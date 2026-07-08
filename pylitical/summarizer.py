import logging
import os

from google import genai
from google.genai import errors, types

logger = logging.getLogger(__name__)


class SummarizerError(Exception):
    """Raised when a summarization request fails."""


DEFAULT_MODEL = "gemini-2.5-flash"

SYSTEM_INSTRUCTION = """You are going to be summarizing bills and resolutions that
are currently being deliberated or have already been enrolled by the Michigan congress.
In the prompt I'm going to pass you the status of the bill or resolution, the name of
the bill or resolution, and the text of the bill. I want you to summarize the text into
as many bullet points as you see fit. Prior to the bullet points also give me the status
and name of the bill or resolution.
"""


class BillSummarizer:
    """Wraps the Gemini API for bill summarization."""

    def __init__(self, api_key=None, model=DEFAULT_MODEL):
        self._client = genai.Client(api_key=api_key or os.environ["GOOGLE_API_KEY"])
        self._model = model

    def summarize(self, bill, bill_text) -> str:
        logger.info("Summarizing %r", bill.name)
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=f"{bill.status}\n{bill.name}\n{bill_text}",
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION
                ),
            )
        except errors.APIError as exc:
            raise SummarizerError(f"Gemini request failed for {bill.name!r}") from exc
        return response.text
