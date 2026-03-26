"""
Strait of Georgia (south of Nanaimo) wind alert script.
Fetches the Environment Canada marine forecast and sends a Gmail alert
if westerly or northwesterly winds over 15 knots are forecast.
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

# Regex: matches westerly and northwesterly direction words as used in EC forecasts
# Covers: "west", "westerly", "northwest", "northwesterly", "north-westerly"
WESTERLY_PATTERN = re.compile(
    r'\b(north[\s-]?west(?:erly)?|n\.?w\.?|w\.?n\.?w\.?|n\.?n\.?w\.?|west(?:erly)?)\b',
    re.IGNORECASE
)

# Speed threshold (strictly greater than)
KNOTS_THRESHOLD = 15

# ── Fetch & parse ─────────────────────────────────────────────────────────────

def fetch_forecast_text() -> str:
    """Download the forecast page and return its plain text."""
    headers = {"User-Agent": "wind-alert-bot/1.0 (personal weather monitor)"}
    resp = requests.get(FORECAST_URL, headers=headers, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    return soup.get_text(separator="\n")


def find_qualifying_lines(text: str) -> list[str]:
    """
    Return any forecast lines that mention a W/NW wind direction
    with at least one speed value strictly greater than KNOTS_THRESHOLD.
    """
    qualifying = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # Must mention a westerly/northwesterly direction
        if not WESTERLY_PATTERN.search(line):
            continue

        # Must mention "knots" (avoids matching unrelated numbers on the page)
        if "knot" not in line.lower():
            continue

        # Extract all numbers and check if any exceed the threshold
        speeds = [int(n) for n in re.findall(r'\b(\d+)\b', line) if int(n) < 100]
        if any(s > KNOTS_THRESHOLD for s in speeds):
            qualifying.append(line)

    return qualifying


# ── Email ─────────────────────────────────────────────────────────────────────

def send_alert(matches: list[str], gmail_user: str, app_password: str, recipient: str) -> None:
    """Send a Gmail alert listing all qualifying forecast lines."""
    subject = f"💨 Wind Alert: W/NW >{KNOTS_THRESHOLD} kts – {LOCATION_NAME}"

    body_lines = [
        f"Qualifying wind conditions detected in the {LOCATION_NAME} marine forecast:",
        "",
    ]
    for line in matches:
        body_lines.append(f"  • {line}")
    body_lines += [
        "",
        f"Full forecast: {FORECAST_URL}",
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
    text = fetch_forecast_text()

    matches = find_qualifying_lines(text)

    if not matches:
        print(f"✓ No W/NW winds >{KNOTS_THRESHOLD} kts found in current forecast.")
        return

    print(f"⚠ Found {len(matches)} qualifying line(s):")
    for m in matches:
        print(f"  → {m}")

    # Read credentials from environment (set as GitHub Secrets)
    gmail_user = os.environ["GMAIL_USER"]
    app_password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ.get("RECIPIENT_EMAIL", gmail_user)

    send_alert(matches, gmail_user, app_password, recipient)


if __name__ == "__main__":
    main()
