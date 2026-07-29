import json


class Bill:
    """One legislative item, as shown on one day.

    The same bill appears on several days as it moves through the process, so
    `status` and `action_date` describe *this* appearance, not the bill's whole
    life. That is what makes the daily archive make sense: opening July 3rd
    shows what a bill did on July 3rd.
    """

    # A record type: the long keyword-only signature is the point.
    # pylint: disable=too-many-instance-attributes,too-many-arguments

    def __init__(
        self,
        *,
        name,
        status,
        source_url=None,
        document_urls=None,
        summary=None,
        state=None,
        title=None,
        sponsor=None,
        action_date=None,
        action_description=None,
        classification=None,
    ):
        """
        :param name: Display identifier, e.g. "House Bill 5432" (required)
        :param status: Bucketed stage for this appearance, e.g. "Introduced" (required)
        :param source_url: Canonical page for the bill
        :param document_urls: Links to bill documents
        :param summary: LLM-generated summary, filled in by the summarizer
        :param state: Two-letter jurisdiction code, e.g. "mi"
        :param title: The bill's official title, distinct from its identifier
        :param sponsor: Primary sponsor's name, when known
        :param action_date: ISO date of the action this appearance represents
        :param action_description: The raw action text from the source
        :param classification: "bill", "resolution", etc.
        """
        self.name = name
        self.status = status
        self.source_url = source_url
        self.document_urls = document_urls if document_urls is not None else []
        self.summary = summary
        self.state = state
        self.title = title
        self.sponsor = sponsor
        self.action_date = action_date
        self.action_description = action_description
        self.classification = classification

    @property
    def key(self) -> str:
        """Stable identity for dedupe and for reusing an existing summary."""
        return f"{self.state or '??'}:{self.name}:{self.action_date or ''}"

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "source_url": self.source_url,
            "document_urls": self.document_urls,
            "summary": self.summary,
            "state": self.state,
            "title": self.title,
            "sponsor": self.sponsor,
            "action_date": self.action_date,
            "action_description": self.action_description,
            "classification": self.classification,
        }

    @classmethod
    def from_dict(cls, data) -> "Bill":
        return cls(**{k: v for k, v in data.items() if k in cls.FIELDS})

    def as_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2)

    def __repr__(self):
        return f"Bill(name={self.name!r}, status={self.status!r}, state={self.state!r})"


Bill.FIELDS = frozenset(
    [
        "name",
        "status",
        "source_url",
        "document_urls",
        "summary",
        "state",
        "title",
        "sponsor",
        "action_date",
        "action_description",
        "classification",
    ]
)
