"""
Strait of Georgia (south of Nanaimo) wind alert script.
Fetches the Environment Canada marine forecast and sends a Gmail alert
if westerly or northwesterly winds over 15 knots are forecast.
Includes the full forecast report in the email body.
"""

import os
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests
from bs4 import BeautifulSoup

# ── Config ────────────────────────────────────────────────────────────────────

FORECAST_URL = "https://weather.gc.ca/marine/forecast_e.html?mapID=02&siteID=14305"
LOCATION_NAME = "Strait of Georgia (south of Nanaimo)"

WESTERLY_PATTERN = re.compile(
    r'\b(north[\s-]?west(?:erly)?|n\.?w\.?|w\.?n\.?w\.?|n\.?n\.?w\.?|west(?:erly)?)\b',
    re.IGNORECASE
)

KNOTS_THRESHOLD = 15

# ── Fetch & parse ─────────────────────────────────────────────────────────────

def fetch_forecast(url: str):
    """Download the forecast page and return (plain_text, soup)."""
    headers = {"User-Agent": "wind-alert-bot/1.0 (personal weather monitor)"}
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    return soup.get_text(separator="\n"), soup


def extract_forecast_sections(soup) -> str:
    """Pull the key forecast sections as clean readable text."""
    sections = []
    # Target headings we care about
    target_headings = [
        "Marine Forecast", "Winds", "Weather & Visibility",
        "Extended Forecast", "Synopsis"
    ]
    for heading in soup.find_all(["h2", "h3"]):
        title = heading.get_text(strip=True)
        if any(t in title for t in target_headings):
            # Grab all text until the next heading
            content_parts = []
            for sibling in heading.next_siblings:
                if sibling.name in ["h2", "h3"]:
                    break
                text = sibling.get_text(separator=" ", strip=True) if hasattr(sibling, 'get_text') else str(sibling).strip()
                if text:
                    content_parts.append(text)
            content = " ".join(content_parts).strip()
            if content:
                sections.append(f"{'─' * 40}\n{title.upper()}\n{'─' * 40}\n{content}\n")
    return "\n".join(sections) if sections else "(Could not extract forecast sections)"


def find_qualifying_lines(text: str) -> list[str]:
    """Return forecast lines with W/NW winds strictly over KNOTS_THRESHOLD."""
    qualifying = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if not WESTERLY_PATTERN.search(line):
            continue
        if "knot" not in line.lower():
            continue
        speeds = [int(n) for n in re.findall(r'\b(\d+)\b', line) if int(n) < 100]
        if any(s > KNOTS_THRESHOLD for s in speeds):
            qualifying.append(line)
    return qualifying


# ── Email ─────────────────────────────────────────────────────────────────────

def send_alert(matches: list[str], full_report: str, gmail_user: str, app_password: str, recipient: str) -> None:
    """Send a Gmail alert with matching lines and the full forecast report."""
    subject = f"💨 Wind Alert: W/NW >{KNOTS_THRESHOLD} kts – {LOCATION_NAME}"

    body_lines = [
        f"Qualifying wind conditions detected in the {LOCATION_NAME} marine forecast:",
        "",
    ]
    for line in matches:
        body_lines.append(f"  • {line}")
    body_lines += [
        "",
        "=" * 50,
        "FULL FORECAST REPORT",
        "=" * 50,
        "",
        full_report,
        "",
        f"Source: {FORECAST_URL}",
    ]
    body = "\n".join(body_lines)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = recipient
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, app_password)
        server.sendmail(gmail_user, recipient, msg.as_string())

    print(f"✅ Alert sent to {recipient} — {len(matches)} matching line(s).")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"Fetching forecast from {FORECAST_URL} …")
    text, soup = fetch_forecast(FORECAST_URL)

    matches = find_qualifying_lines(text)

    if not matches:
        print(f"✓ No W/NW winds >{KNOTS_THRESHOLD} kts found in current forecast.")
        return

    print(f"⚠ Found {len(matches)} qualifying line(s):")
    for m in matches:
        print(f"  → {m}")

    full_report = extract_forecast_sections(soup)

    gmail_user = os.environ["GMAIL_USER"]
    app_password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ.get("RECIPIENT_EMAIL", gmail_user)

    send_alert(matches, full_report, gmail_user, app_password, recipient)


if __name__ == "__main__":
    main()
