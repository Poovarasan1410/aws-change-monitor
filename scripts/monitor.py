import hashlib
import json
import os
import re
import subprocess
import urllib.request
import xml.etree.ElementTree as ET

from datetime import datetime, timezone
from urllib.request import Request, urlopen


STATE_FILE = "data/state.json"

FEEDS = {
    "AWS What's New":
        "https://aws.amazon.com/about-aws/whats-new/recent/feed/",

    "AWS Security":
        "https://aws.amazon.com/security/security-bulletins/rss/"
}

# Maximum time to wait for AWS feeds
TIMEOUT = 15


# ============================================================
# LOAD STATE
# ============================================================

def load_state():

    if not os.path.exists(STATE_FILE):

        return {
            "last_run": None,
            "processed": []
        }

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            content = f.read().strip()

        if not content:

            return {
                "last_run": None,
                "processed": []
            }

        return json.loads(content)

    except json.JSONDecodeError:

        print(
            "WARNING: Invalid state.json. "
            "Starting with empty state."
        )

        return {
            "last_run": None,
            "processed": []
        }


# ============================================================
# SAVE STATE
# ============================================================

def save_state(state):

    os.makedirs(
        "data",
        exist_ok=True
    )

    with open(
        STATE_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            state,
            f,
            indent=2,
            ensure_ascii=False
        )


# ============================================================
# FETCH AWS RSS FEED
# ============================================================

def fetch_feed(url):

    print(
        f"Fetching: {url}"
    )

    request = Request(
        url,
        headers={
            "User-Agent":
                "AWS-Change-Monitor/1.0"
        }
    )

    try:

        with urlopen(
            request,
            timeout=TIMEOUT
        ) as response:

            return response.read()

    except Exception as error:

        print(
            f"WARNING: Could not fetch feed: "
            f"{error}"
        )

        return None


# ============================================================
# CLEAN HTML
# ============================================================

def clean_html(text):

    if not text:

        return ""

    text = re.sub(
        r"<[^>]+>",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# ============================================================
# PARSE RSS
# ============================================================

def parse_feed(xml_data):

    if not xml_data:

        return []

    try:

        root = ET.fromstring(
            xml_data
        )

    except ET.ParseError as error:

        print(
            f"WARNING: RSS parsing failed: "
            f"{error}"
        )

        return []

    entries = []

    for item in root.findall(
        ".//item"
    ):

        title = item.findtext(
            "title",
            ""
        )

        link = item.findtext(
            "link",
            ""
        )

        description = item.findtext(
            "description",
            ""
        )

        published = item.findtext(
            "pubDate",
            ""
        )

        entries.append({

            "title":
                clean_html(title),

            "link":
                link.strip(),

            "description":
                clean_html(
                    description
                ),

            "published":
                published.strip()
        })

    return entries


# ============================================================
# GENERATE UNIQUE ID
# ============================================================

def generate_id(item):

    raw = (
        item["title"]
        + "|"
        + item["link"]
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


# ============================================================
# DETECT PRIORITY
# ============================================================

def detect_priority(item):

    text = (
        item["title"]
        + " "
        + item["description"]
    ).lower()

    high_keywords = [

        "new service",

        "launch",

        "general availability",

        "now available",

        "security",

        "vulnerability",

        "critical",

        "deprecation",

        "end of support",

        "breaking change",

        "new capability"
    ]

    medium_keywords = [

        "new feature",

        "now supports",

        "support for",

        "available in",

        "enhancement",

        "integration",

        "console",

        "monitoring",

        "api",

        "cli"
    ]

    for keyword in high_keywords:

        if keyword in text:

            return "HIGH"

    for keyword in medium_keywords:

        if keyword in text:

            return "MEDIUM"

    return "LOW"


# ============================================================
# DETECT AWS SERVICES
# ============================================================

def detect_services(item):

    text = (
        item["title"]
        + " "
        + item["description"]
    ).lower()

    services = [

        "EC2",

        "VPC",

        "IAM",

        "S3",

        "RDS",

        "Aurora",

        "Lambda",

        "ECS",

        "EKS",

        "CloudWatch",

        "CloudTrail",

        "CloudFormation",

        "Route 53",

        "CloudFront",

        "WAF",

        "GuardDuty",

        "Security Hub",

        "KMS",

        "Secrets Manager",

        "Systems Manager",

        "AWS Organizations",

        "AWS Backup",

        "Bedrock",

        "SageMaker"
    ]

    detected = []

    for service in services:

        if service.lower() in text:

            detected.append(
                service
            )

    return detected


# ============================================================
# CREATE GITHUB ISSUE
# ============================================================

def create_issue(
    item,
    priority,
    services
):

    token = os.environ.get(
        "GH_TOKEN"
    )

    if not token:

        print(
            "WARNING: GH_TOKEN not available."
        )

        return None

    title = (
        f"[AWS {priority}] "
        f"{item['title']}"
    )

    service_text = (

        ", ".join(services)

        if services

        else "AWS General"
    )

    body = f"""# AWS Change Detected

## Service

{service_text}

## Priority

**{priority}**

## Published

{item['published']}

## Change

{item['title']}

## Details

{item['description']}

## Official AWS Source

{item['link']}

---

Automatically detected by **AWS Change Monitor**.
"""

    try:

        result = subprocess.run(
            [
                "gh",
                "issue",
                "create",
                "--title",
                title,
                "--body",
                body
            ],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:

            issue_url = (
                result.stdout.strip()
            )

            print()
            print(
                "GitHub Issue created:"
            )

            print(
                issue_url
            )

            return issue_url

        else:

            print()
            print(
                "WARNING: GitHub Issue creation failed:"
            )

            print(
                result.stderr
            )

            return None

    except subprocess.TimeoutExpired:

        print(
            "WARNING: GitHub Issue creation timed out."
        )

        return None


# ============================================================
# SEND MICROSOFT TEAMS NOTIFICATION
# ============================================================

def send_teams_notification(
    item,
    priority,
    services,
    issue_url=None
):

    webhook_url = os.environ.get(
        "TEAMS_WEBHOOK_URL"
    )

    if not webhook_url:

        print(
            "TEAMS_WEBHOOK_URL not configured."
        )

        return

    service_text = (

        ", ".join(services)

        if services

        else "AWS General"
    )

    issue_text = ""

    if issue_url:

        issue_text = (
            "\n\n"
            "GitHub Issue:\n"
            f"{issue_url}"
        )

    message = (
        f"🚨 AWS {priority} CHANGE DETECTED\n\n"

        f"Service: {service_text}\n"

        f"Change: {item['title']}\n"

        f"Published: {item['published']}\n\n"

        f"Details:\n"
        f"{item['description'][:1500]}\n\n"

        f"AWS Official Source:\n"
        f"{item['link']}"

        f"{issue_text}"
    )

    payload = json.dumps({

        "text": message

    }).encode("utf-8")

    request = urllib.request.Request(

        webhook_url,

        data=payload,

        headers={
            "Content-Type":
                "application/json"
        },

        method="POST"
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=15
        ) as response:

            response.read()

        print()
        print(
            "Microsoft Teams notification "
            "sent successfully."
        )

    except Exception as error:

        print(
            f"WARNING: Teams notification failed: "
            f"{error}"
        )


# ============================================================
# MAIN AWS MONITOR
# ============================================================

def main():

    print()
    print(
        "=========================================="
    )

    print(
        "       AWS CHANGE MONITOR"
    )

    print(
        "=========================================="
    )

    print()

    state = load_state()

    processed = set(
        state.get(
            "processed",
            []
        )
    )

    new_items = []

    for source, feed_url in FEEDS.items():

        print(
            f"Checking {source}..."
        )

        try:

            xml_data = fetch_feed(
                feed_url
            )

            entries = parse_feed(
                xml_data
            )

        except Exception as error:

            print(
                f"ERROR reading {source}: "
                f"{error}"
            )

            continue

        print(
            f"Found {len(entries)} entries."
        )

        for item in entries:

            if not item["link"]:

                continue

            item_id = generate_id(
                item
            )

            # ------------------------------------------
            # Duplicate detection
            # ------------------------------------------

            if item_id in processed:

                continue

            priority = detect_priority(
                item
            )

            services = detect_services(
                item
            )

            print()
            print(
                f"NEW: {item['title']}"
            )

            print(
                f"Priority: {priority}"
            )

            print(
                "Services: "
                f"{', '.join(services) or 'General AWS'}"
            )

            # ------------------------------------------
            # Create issue and notify Teams
            # ------------------------------------------

            if priority in [
                "HIGH",
                "MEDIUM"
            ]:

                issue_url = create_issue(
                    item,
                    priority,
                    services
                )

                send_teams_notification(
                    item,
                    priority,
                    services,
                    issue_url
                )

            # ------------------------------------------
            # Save processed item
            # ------------------------------------------

            processed.add(
                item_id
            )

            new_items.append(
                item_id
            )

    # ========================================================
    # SAVE STATE
    # ========================================================

    now = datetime.now(
        timezone.utc
    ).isoformat()

    state["last_run"] = now

    state["processed"] = list(
        processed
    )[-2000:]

    save_state(
        state
    )

    print()

    print(
        "=========================================="
    )

    print(
        f"New items processed: "
        f"{len(new_items)}"
    )

    print(
        f"Run completed: {now}"
    )

    print(
        "=========================================="
    )


# ============================================================
# SCRIPT ENTRY POINT
# ============================================================

if __name__ == "__main__":

    # ------------------------------------------
    # Run AWS What's New + Security monitoring
    # ------------------------------------------

    main()

    # ------------------------------------------
    # Run AWS documentation monitoring
    # ------------------------------------------

    print()

    print(
        "=========================================="
    )

    print(
        "Running AWS documentation monitoring"
    )

    print(
        "=========================================="
    )

    try:

        result = subprocess.run(
            [
                "python",
                "scripts/docs_monitor.py"
            ],
            capture_output=False,
            timeout=120
        )

        if result.returncode != 0:

            print(
                "WARNING: AWS documentation "
                "monitoring failed."
            )

    except subprocess.TimeoutExpired:

        print(
            "WARNING: AWS documentation "
            "monitoring timed out."
        )
