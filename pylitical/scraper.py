import functools
import logging
import time
from datetime import datetime
from multiprocessing import Pool

import requests
from bs4 import BeautifulSoup

from .bill import Bill

logger = logging.getLogger(__name__)

BASE_URL = "https://legislature.mi.gov"
DAILY_REPORT_URL = f"{BASE_URL}/Bills/DailyReport"

STATUS_SECTIONS = ("Introduced", "Passed by Chamber", "Enrolled", "Adopted")
STATUS_DOCUMENT_KEYWORDS = {
    "Introduced": ("Introduced",),
    "Passed by Chamber": ("Passed by the House", "Passed by the Senate"),
    "Enrolled": ("Concurred", "Enrolled"),
    "Adopted": ("Adopted",),
}


FETCH_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5
PAGE_DELAY_SECONDS = 1
USER_AGENT = "Pylitical/1.0 (+https://github.com/ConstantinBalan/Pylitical)"


@functools.lru_cache(maxsize=1)
def _session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session


class ScraperError(Exception):
    """Raised when a page cannot be fetched."""


class BotChallengeError(ScraperError):
    """The site served a bot-protection interstitial instead of content.

    This is deliberately fatal rather than fail-soft. The challenge page returns
    HTTP 200, so without this check BeautifulSoup parses it happily, finds none
    of the elements we look for, and the run reports "0 bills" -- identical to a
    genuine day with no legislative activity. That would quietly publish an
    empty site and send no digest, with nothing in the logs to explain why.
    """


# Structural markers from the Radware Bot Manager interstitial. Anchored on the
# title and the challenge form's action rather than the word "captcha" alone,
# so ordinary bill text mentioning it cannot trip this.
_CHALLENGE_MARKERS = (
    "<title>validation request</title>",
    "user validation required",
    "/captcha_resp",
)

# The interstitial is ~1KB; real pages are far larger. Only inspecting the head
# of the document keeps this from scanning entire bill documents.
_CHALLENGE_SCAN_BYTES = 4000


def _looks_like_bot_challenge(html_text) -> bool:
    head = html_text[:_CHALLENGE_SCAN_BYTES].lower()
    return any(marker in head for marker in _CHALLENGE_MARKERS)


class BillScraper:

    def __init__(self, base_url=BASE_URL, daily_report_url=DAILY_REPORT_URL):
        self.base_url = base_url
        self.daily_report_url = daily_report_url

    def find(self, start_date=None, end_date=None) -> list:
        report_url = self._report_url_for_range(start_date, end_date)
        logger.info("Fetching daily report: %s", report_url)
        bill_urls_by_status = self._parse_report(self._get(report_url))

        bills = []
        with Pool(processes=len(STATUS_SECTIONS)) as pool:
            results = pool.starmap(self._bills_for_status, bill_urls_by_status.items())
        for status_bills in results:
            bills.extend(status_bills)
        return bills

    def get_bill_text(self, bill) -> str:
        texts = []
        for url in bill.document_urls:
            soup = BeautifulSoup(self._get(url), "html.parser")
            texts.append(soup.get_text())
        return "\n".join(texts)

    def _get(self, url) -> str:
        last_exc = None
        for attempt in range(1, FETCH_ATTEMPTS + 1):
            try:
                response = _session().get(url, timeout=30)
                response.raise_for_status()
                # Not retried: the block is by client IP, so hammering it would
                # neither help nor be a decent thing to do to a public site.
                if _looks_like_bot_challenge(response.text):
                    raise BotChallengeError(
                        f"legislature.mi.gov served a bot-protection challenge for {url}. "
                        "Scraped results would be empty and misleading, so this run is "
                        "stopping instead of publishing nothing."
                    )
                return response.text
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                if attempt < FETCH_ATTEMPTS:
                    logger.warning("Fetch failed (%s); retrying %s", exc, url)
                    time.sleep(RETRY_DELAY_SECONDS * attempt)
        raise ScraperError(f"Failed to fetch {url}") from last_exc

    def _report_url_for_range(self, start_date, end_date) -> str:
        if not start_date and not end_date:
            return self.daily_report_url
        if end_date and not start_date:
            raise ValueError("end_date was provided without a start_date.")

        parsed_start = datetime.strptime(start_date, "%Y-%m-%d")
        parsed_end = datetime.strptime(end_date, "%Y-%m-%d")
        if parsed_start >= parsed_end:
            raise ValueError("start_date must be before end_date.")

        return f"{self.daily_report_url}?dateFrom={start_date}&dateTo={end_date}"

    def _parse_report(self, report_html) -> dict:
        soup = BeautifulSoup(report_html, "html.parser")
        bill_urls_by_status = {status: [] for status in STATUS_SECTIONS}

        for status in STATUS_SECTIONS:
            title_element = soup.find("h3", string=status)
            if not title_element:
                logger.info("Report has no %r section", status)
                continue
            # On the MI site the section's table is the heading's next sibling.
            table_element = title_element.find_next_sibling()
            tbody = table_element.find("tbody") if table_element else None
            if not tbody:
                continue
            for table_row in tbody.find_all("tr"):
                first_cell = table_row.find("td")
                if first_cell and first_cell.find("a"):
                    href = first_cell.find("a")["href"]
                    bill_urls_by_status[status].append(self.base_url + href)

        return bill_urls_by_status

    def _bills_for_status(self, status, bill_page_urls) -> list:
        bills = []
        for index, bill_url in enumerate(bill_page_urls):
            if index:
                time.sleep(PAGE_DELAY_SECONDS)
            try:
                bill = self._parse_bill_page(status, bill_url, self._get(bill_url))
            except BotChallengeError:
                # Being challenged invalidates the whole run, not one page.
                raise
            except ScraperError:
                # One dead page shouldn't sink the whole section.
                logger.exception("Skipping %s", bill_url)
                continue
            if bill:
                bills.append(bill)
            else:
                logger.warning("No %r document found on %s; skipping", status, bill_url)
        logger.info("Found %d bill(s) under %r", len(bills), status)
        return bills

    def _parse_bill_page(self, status, bill_url, bill_html):
        soup = BeautifulSoup(bill_html, "html.parser")

        name_header = soup.find("h1", id="BillHeading")
        documents_div = soup.find("div", class_="billDocuments")
        if not name_header or not documents_div:
            return None

        keywords = STATUS_DOCUMENT_KEYWORDS[status]
        document_urls = []
        for doc_row in documents_div.find_all("div", class_="billDocRow"):
            text_div = doc_row.find("div", class_="text")
            strong_text = text_div.find("strong") if text_div else None
            if not strong_text:
                continue
            if not any(keyword in strong_text.get_text() for keyword in keywords):
                continue
            html_div = doc_row.find("div", class_="html")
            link = html_div.find("a") if html_div else None
            if link and link.get("href"):
                document_urls.append(self.base_url + link["href"])

        if not document_urls:
            return None
        return Bill(
            name=name_header.get_text().strip(),
            status=status,
            source_url=bill_url,
            document_urls=document_urls,
        )
