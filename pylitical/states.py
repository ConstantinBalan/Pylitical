"""Which states the site covers.

`code` is the URL segment and archive key, `jurisdiction` is what Open States
wants, and `name` is what a reader sees. They differ often enough to be worth
keeping distinct.

Adding a state is a one-line change here, but check two things first: whether
it publishes abstracts to Open States (`probe_openstates.py`), and what it does
to the daily Open States request count -- the default tier allows 500 a day.
"""


class State:
    def __init__(self, code, name, jurisdiction):
        self.code = code
        self.name = name
        self.jurisdiction = jurisdiction

    def __repr__(self):
        return f"State({self.code!r}, {self.name!r})"


SUPPORTED = (State("mi", "Michigan", "Michigan"),)

# Candidates, not yet enabled. Ohio, Indiana and Illinois publish abstracts to
# Open States; Wisconsin and Minnesota do not, so they would depend entirely on
# LegiScan text.
CANDIDATES = (
    State("oh", "Ohio", "Ohio"),
    State("in", "Indiana", "Indiana"),
    State("il", "Illinois", "Illinois"),
    State("wi", "Wisconsin", "Wisconsin"),
)

DEFAULT_STATE = "mi"


def by_code(code):
    for state in SUPPORTED:
        if state.code == code:
            return state
    return None
