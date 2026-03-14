"""
ivasms.py — IVASMS web scraping client.
Handles login, session management and all API payloads.
"""

import re
import logging
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

from config import IVASMS_EMAIL, IVASMS_PASSWORD

logger = logging.getLogger("ivasms-bot.client")

BASE_HEADERS = {
    "Host": "www.ivasms.com",
    "Cache-Control": "max-age=0",
    "Sec-Ch-Ua": '"Not)A;Brand";v="8", "Chromium";v="138"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/138.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;"
        "q=0.8,application/signed-exchange;v=b3;q=0.7"
    ),
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-GB,en;q=0.9",
    "Priority": "u=0, i",
    "Connection": "keep-alive",
}


class IVASMSClient:
    """Stateful IVASMS scraping client. One instance per session."""

    def __init__(self):
        self.session = requests.Session()
        self.csrf_token: str | None = None

    # ── Auth ──────────────────────────────────────────────────────────────────

    def login(self) -> None:
        """Full login flow: GET /login → POST /login → GET /sms/received (CSRF)."""
        token = self._get_login_token()
        self._post_credentials(token)
        self._get_csrf_token()
        logger.info("Login successful.")

    def _get_login_token(self) -> str:
        url = "https://www.ivasms.com/login"
        # Minimal browser-like headers — avoid triggering bot detection
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        resp = self.session.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        logger.debug(f"Login page status: {resp.status_code}, URL: {resp.url}")

        # Try multiple patterns — IVASMS has changed this before
        patterns = [
            r'<input[^>]+name=["\']_token["\'][^>]+value=["\']([^"\']+)["\']',
            r'<input[^>]+value=["\']([^"\']+)["\'][^>]+name=["\']_token["\']',
            r'_token["\']\s*:\s*["\']([^"\']+)["\']',
            r'csrf[_-]?token["\']?\s*[=:]\s*["\']([^"\']{20,})["\']\s*',
            r'<meta[^>]+name=["\']csrf-token["\'][^>]+content=["\']([^"\']+)["\']',
        ]
        for pattern in patterns:
            match = re.search(pattern, resp.text, re.IGNORECASE)
            if match:
                token = match.group(1)
                logger.debug(f"Found _token via pattern: {pattern[:40]}...")
                return token

        # Last resort: BeautifulSoup scan
        soup = BeautifulSoup(resp.text, "html.parser")
        for inp in soup.find_all("input", {"name": "_token"}):
            val = inp.get("value", "")
            if val:
                logger.debug("Found _token via BeautifulSoup fallback.")
                return val

        # Dump a snippet to logs so you can see what the page actually returned
        snippet = resp.text[:800].replace("\n", " ")
        logger.error(f"Login page snippet: {snippet}")
        raise ValueError(
            f"Could not find _token on /login page (HTTP {resp.status_code}). "
            "The page may be blocking bots or has changed its HTML. "
            "Check logs for the page snippet."
        )

    def _post_credentials(self, token: str) -> None:
        url = "https://www.ivasms.com/login"
        headers = {
            **BASE_HEADERS,
            "Content-Type": "application/x-www-form-urlencoded",
            "Sec-Fetch-Site": "same-origin",
            "Referer": "https://www.ivasms.com/login",
            "Origin": "https://www.ivasms.com",
        }
        data = {
            "_token": token,
            "email": IVASMS_EMAIL,
            "password": IVASMS_PASSWORD,
            "remember": "on",
            "g-recaptcha-response": "",
            "submit": "register",
        }
        resp = self.session.post(url, headers=headers, data=data, timeout=30, allow_redirects=True)
        resp.raise_for_status()
        logger.debug(f"Post-login URL: {resp.url}")
        if "/login" in resp.url:
            # Check if it's a "wrong password" page vs a redirect loop
            if "invalid" in resp.text.lower() or "credentials" in resp.text.lower():
                raise ValueError("Login failed — wrong email or password.")
            raise ValueError("Login failed — redirected back to /login. May need CAPTCHA solving.")

    def _get_csrf_token(self) -> None:
        url = "https://www.ivasms.com/portal/sms/received"
        headers = {
            **BASE_HEADERS,
            "Sec-Fetch-Site": "same-origin",
            "Referer": "https://www.ivasms.com/portal",
        }
        resp = self.session.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        match = re.search(r'<meta name="csrf-token" content="([^"]+)">', resp.text)
        if not match:
            raise ValueError("Could not find CSRF token after login.")
        self.csrf_token = match.group(1)

    # ── Statistics ────────────────────────────────────────────────────────────

    def fetch_statistics(self, from_date: str, to_date: str) -> list[dict]:
        """Fetch SMS range statistics for a date range."""
        boundary = "----WebKitFormBoundaryhkp0qMozYkZV6Ham"
        url = "https://www.ivasms.com/portal/sms/received/getsms"
        headers = {
            **BASE_HEADERS,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": "https://www.ivasms.com/portal/sms/received",
            "Origin": "https://www.ivasms.com",
        }
        data = (
            f"--{boundary}\r\n"
            "Content-Disposition: form-data; name=\"from\"\r\n\r\n"
            f"{from_date}\r\n"
            f"--{boundary}\r\n"
            "Content-Disposition: form-data; name=\"to\"\r\n\r\n"
            f"{to_date}\r\n"
            f"--{boundary}\r\n"
            "Content-Disposition: form-data; name=\"_token\"\r\n\r\n"
            f"{self.csrf_token}\r\n"
            f"--{boundary}--\r\n"
        )
        resp = self.session.post(url, headers=headers, data=data, timeout=30)
        resp.raise_for_status()
        return self._parse_statistics(resp.text)

    @staticmethod
    def _parse_statistics(html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        ranges = []

        no_sms = soup.find("p", id="messageFlash")
        if no_sms and "You do not have any SMS" in no_sms.text:
            return ranges

        for card in soup.find_all("div", class_="card card-body mb-1 pointer"):
            cols = card.find_all("div", class_=re.compile(r"col-sm-\d+|col-\d+"))
            if len(cols) < 5:
                continue
            try:
                range_name = cols[0].text.strip()
                count = int(cols[1].find("p").text.strip() or 0)
                paid = int(cols[2].find("p").text.strip() or 0)
                unpaid = int(cols[3].find("p").text.strip() or 0)
                rev_span = cols[4].find("span", class_="currency_cdr")
                revenue = rev_span.text.strip() if rev_span else "0.0"
                onclick = card.get("onclick", "")
                rid_match = re.search(r"getDetials\('([^']+)'\)", onclick)
                range_id = rid_match.group(1) if rid_match else range_name
                ranges.append({
                    "range_name": range_name,
                    "range_id": range_id,
                    "count": count,
                    "paid": paid,
                    "unpaid": unpaid,
                    "revenue": revenue,
                })
            except Exception as e:
                logger.warning(f"Failed to parse range card: {e}")

        return ranges

    # ── Available Numbers (account inventory) ────────────────────────────────

    def fetch_available_numbers(self) -> list[dict]:
        """Fetch all virtual numbers assigned to this account from /portal/numbers."""
        url = "https://www.ivasms.com/portal/numbers"
        headers = {
            **BASE_HEADERS,
            "Sec-Fetch-Site": "same-origin",
            "Referer": "https://www.ivasms.com/portal",
        }
        resp = self.session.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        return self._parse_available_numbers(resp.text)

    @staticmethod
    def _parse_available_numbers(html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        numbers = []

        # Try table rows first (most common layout)
        table = soup.find("table")
        if table:
            rows = table.find_all("tr")
            headers_row = rows[0] if rows else None
            col_headers = []
            if headers_row:
                col_headers = [th.text.strip().lower() for th in headers_row.find_all(["th", "td"])]

            for row in rows[1:]:
                cols = row.find_all("td")
                if not cols:
                    continue
                entry = {}
                for i, col in enumerate(cols):
                    key = col_headers[i] if i < len(col_headers) else f"col_{i}"
                    entry[key] = col.text.strip()
                # Normalise common field names
                number = (
                    entry.get("number")
                    or entry.get("phone number")
                    or entry.get("msisdn")
                    or (cols[0].text.strip() if cols else "")
                )
                status = (
                    entry.get("status")
                    or entry.get("state")
                    or "—"
                )
                country = (
                    entry.get("country")
                    or entry.get("range")
                    or "—"
                )
                expires = (
                    entry.get("expiry")
                    or entry.get("expire")
                    or entry.get("expires")
                    or entry.get("expiration")
                    or "—"
                )
                if number:
                    numbers.append({
                        "number": number,
                        "status": status,
                        "country": country,
                        "expires": expires,
                        "raw": entry,
                    })
            return numbers

        # Fallback: card-based layout (same style as received SMS page)
        for card in soup.find_all("div", class_=re.compile(r"card")):
            text = card.text.strip()
            # Look for anything that resembles a phone number
            phone_match = re.search(r"\+?(\d{7,15})", text)
            if not phone_match:
                continue
            number = phone_match.group(1)
            status_match = re.search(r"(active|inactive|expired|pending)", text, re.IGNORECASE)
            status = status_match.group(1).capitalize() if status_match else "—"
            numbers.append({
                "number": number,
                "status": status,
                "country": "—",
                "expires": "—",
                "raw": {},
            })

        return numbers

    # ── Numbers (SMS received per range) ──────────────────────────────────────

    def fetch_numbers(self, to_date: str, range_name: str) -> list[dict]:
        """Fetch numbers active in a given range."""
        url = "https://www.ivasms.com/portal/sms/received/getsms/number"
        headers = {
            **BASE_HEADERS,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": "https://www.ivasms.com/portal/sms/received",
            "Origin": "https://www.ivasms.com",
        }
        data = {
            "_token": self.csrf_token,
            "start": "",
            "end": to_date,
            "range": range_name,
        }
        resp = self.session.post(url, headers=headers, data=data, timeout=30)
        resp.raise_for_status()
        return self._parse_numbers(resp.text)

    @staticmethod
    def _parse_numbers(html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        numbers = []
        for div in soup.find_all("div", class_="card card-body border-bottom bg-100 p-2 rounded-0"):
            col = div.find("div", class_=re.compile(r"col-sm-\d+|col-\d+"))
            if not col:
                continue
            onclick = col.get("onclick", "")
            match = re.search(r"'([^']+)','([^']+)'", onclick)
            if match:
                number, number_id = match.groups()
                numbers.append({"number": number, "number_id": number_id})
        return numbers

    # ── Message ───────────────────────────────────────────────────────────────

    def fetch_message(self, to_date: str, number: str, range_name: str) -> dict:
        """Fetch the latest message for a number in a range."""
        url = "https://www.ivasms.com/portal/sms/received/getsms/number/sms"
        headers = {
            **BASE_HEADERS,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": "https://www.ivasms.com/portal/sms/received",
            "Origin": "https://www.ivasms.com",
        }
        data = {
            "_token": self.csrf_token,
            "start": "",
            "end": to_date,
            "Number": number,
            "Range": range_name,
        }
        resp = self.session.post(url, headers=headers, data=data, timeout=30)
        resp.raise_for_status()
        return self._parse_message(resp.text)

    @staticmethod
    def _parse_message(html: str) -> dict:
        soup = BeautifulSoup(html, "html.parser")
        msg_div = soup.find("div", class_="col-9 col-sm-6 text-center text-sm-start")
        rev_div = soup.find("div", class_="col-3 col-sm-2 text-center text-sm-start")
        message = msg_div.find("p").text.strip() if msg_div else "No message found"
        revenue = "0.0"
        if rev_div:
            span = rev_div.find("span", class_="currency_cdr")
            revenue = span.text.strip() if span else "0.0"
        return {"message": message, "revenue": revenue}
