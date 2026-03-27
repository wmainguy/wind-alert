"""
Strait of Georgia (south of Nanaimo) wind alert script.
- Sends a nicely formatted HTML email
- Only alerts if the forecast has changed since the last alert
  (stores a hash in last_alert_hash.txt in the repo via GitHub API)
"""

import hashlib
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from bs4 import BeautifulSoup

# ── Config ────────────────────────────────────────────────────────────────────

FORECAST_URL = "https://weather.gc.ca/marine/forecast_e.html?mapID=02&siteID=14305"
LOCATION_NAME = "Strait of Georgia (south of Nanaimo)"
HASH_FILE = "last_alert_hash.txt"
REPO = "wmainguy/wind-alert"
GITHUB_API = "https://api.github.com"

WESTERLY_PATTERN = re.compile(
    r'\b(north[\s-]?west(?:erly)?|n\.?w\.?|w\.?n\.?w\.?|n\.?n\.?w\.?|west(?:erly)?)\b',
    re.IGNORECASE
)
KNOTS_THRESHOLD = 15

# ── Fetch & parse ─────────────────────────────────────────────────────────────

def fetch_forecast():
    headers = {"User-Agent": "wind-alert-bot/1.0 (personal weather monitor)"}
    resp = requests.get(FORECAST_URL, headers=headers, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    return soup.get_text(separator="\n"), soup


def find_qualifying_lines(text):
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


def extract_sections(soup):
    target = ["Marine Forecast", "Winds", "Weather & Visibility", "Extended Forecast",
              "Technical Marine Synopsis", "Marine Weather Statement"]
    sections = {}
    for heading in soup.find_all(["h2", "h3"]):
        title = heading.get_text(strip=True)
        if any(t in title for t in target):
            parts = []
            for sib in heading.next_siblings:
                if sib.name in ["h2", "h3"]:
                    break
                t = sib.get_text(" ", strip=True) if hasattr(sib, "get_text") else str(sib).strip()
                if t:
                    parts.append(t)
            content = " ".join(parts).strip()
            if content:
                sections[title] = content
    return sections

# ── Deduplication via GitHub API ──────────────────────────────────────────────

def gh_headers():
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PAT")
    if not token:
        raise RuntimeError("No GitHub token found in environment")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_last_hash():
    try:
        r = requests.get(f"{GITHUB_API}/repos/{REPO}/contents/{HASH_FILE}",
                         headers=gh_headers(), timeout=10)
        if r.status_code == 200:
            import base64
            return base64.b64decode(r.json()["content"]).decode().strip(), r.json()["sha"]
    except Exception:
        pass
    return None, None


def save_hash(new_hash, old_sha):
    import base64, json
    content = base64.b64encode(new_hash.encode()).decode()
    body = {"message": "Update last alert hash", "content": content}
    if old_sha:
        body["sha"] = old_sha
    requests.put(f"{GITHUB_API}/repos/{REPO}/contents/{HASH_FILE}",
                 headers=gh_headers(), data=json.dumps(body), timeout=10)


def fingerprint(matches):
    return hashlib.sha256("\n".join(sorted(matches)).encode()).hexdigest()


# ── HTML Email ────────────────────────────────────────────────────────────────

def build_html(matches, sections):
    bullet_rows = "".join(
        f'<tr><td style="padding:6px 12px;border-bottom:1px solid #e8f0e8;">💨 {line}</td></tr>'
        for line in matches
    )
    section_html = ""
    for title, content in sections.items():
        section_html += f'''
        <div style="margin-bottom:20px;">
          <div style="font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#2d6a4f;border-bottom:2px solid #95d5b2;padding-bottom:4px;margin-bottom:8px;">{title}</div>
          <div style="font-size:14px;color:#333;line-height:1.6;">{content}</div>
        </div>'''
    return f'''<!DOCTYPE html><html><body style="margin:0;padding:0;background:#f0f4f0;font-family:Georgia,serif;">
  <div style="max-width:620px;margin:30px auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.12);">
    <div style="background:#1b4332;padding:24px 28px;">
      <div style="font-size:22px;color:#fff;font-weight:bold;">💨 Wind Alert</div>
      <div style="font-size:13px;color:#95d5b2;margin-top:4px;">{LOCATION_NAME}</div>
    </div>
    <div style="padding:20px 28px 0;">
      <div style="font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#2d6a4f;margin-bottom:10px;">Qualifying Conditions (W/NW &gt;{KNOTS_THRESHOLD} kts)</div>
      <table style="width:100%;border-collapse:collapse;background:#f6fff8;border:1px solid #d8f3dc;border-radius:4px;font-size:14px;">{bullet_rows}</table>
    </div>
    <div style="padding:24px 28px;">
      <div style="font-size:15px;font-weight:bold;color:#1b4332;border-bottom:2px solid #1b4332;padding-bottom:6px;margin-bottom:18px;">Full Forecast Report</div>
      {section_html}
    </div>
    <div style="background:#f6fff8;padding:14px 28px;font-size:12px;color:#888;border-top:1px solid #d8f3dc;">Source: <a href="{FORECAST_URL}" style="color:#2d6a4f;">{FORECAST_URL}</a></div>
  </div></body></html>'''


def build_plaintext(matches, sections):
    lines = [f"Wind Alert: W/NW >{KNOTS_THRESHOLD} kts — {LOCATION_NAME}", ""]
    for m in matches:
        lines.append(f"  • {m}")
    lines += ["", "=" * 50, "FULL FORECAST", "=" * 50, ""]
    for title, content in sections.items():
        lines += [title.upper(), "-" * len(title), content, ""]
    lines.append(f"Source: {FORECAST_URL}")
    return "\n".join(lines)


def send_alert(matches, sections, gmail_user, app_password, recipient):
    subject = f"💨 Wind Alert: W/NW >{KNOTS_THRESHOLD} kts — {LOCATION_NAME}"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = recipient
    msg.attach(MIMEText(build_plaintext(matches, sections), "plain"))
    msg.attach(MIMEText(build_html(matches, sections), "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, app_password)
        server.sendmail(gmail_user, recipient, msg.as_string())
    print(f"✅ Alert sent to {recipient}")


def main():
    print(f"Fetching {FORECAST_URL} …")
    text, soup = fetch_forecast()
    matches = find_qualifying_lines(text)
    if not matches:
        print(f"✓ No W/NW winds >{KNOTS_THRESHOLD} kts in forecast.")
        return
    print(f"⚨ {len(matches)} qualifying line(s) found.")
    current_hash = fingerprint(matches)
    last_hash, last_sha = get_last_hash()
    if current_hash == last_hash:
        print("⏭  Forecast unchanged since last alert — skipping email.")
        return
    sections = extract_sections(soup)
    gmail_user    = os.environ["GMAIL_USER"]
    app_password  = os.environ["GMAIL_APP_PASSWORD"]
    recipient     = os.environ.get("RECIPIENT_EMAIL", gmail_user)
    send_alert(matches, sections, gmail_user, app_password, recipient)
    save_hash(current_hash, last_sha)
    print("💾 Hash saved.")


if __name__ == "__main__":
    main()
