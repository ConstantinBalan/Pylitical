import json


class Bill:
    def __init__(
        self, *, name, status, source_url=None, document_urls=None, summary=None
    ):
        """
        :param name: Bill heading, e.g. "House Bill 5432 of 2024" (required)
        :param status: Report section the bill appeared under, e.g. "Introduced" (required)
        :param source_url: URL of the bill's page on legislature.mi.gov
        :param document_urls: Links to the bill's HTML documents for this status
        :param summary: LLM-generated summary, filled in by the summarizer
        """
        self.name = name
        self.status = status
        self.source_url = source_url
        self.document_urls = document_urls if document_urls is not None else []
        self.summary = summary

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "source_url": self.source_url,
            "document_urls": self.document_urls,
            "summary": self.summary,
        }

    def as_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2)

    def __repr__(self):
        return f"Bill(name={self.name!r}, status={self.status!r})"
