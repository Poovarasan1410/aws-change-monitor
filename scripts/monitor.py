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

    # --------------------------------------------------
    # Service name
    # --------------------------------------------------

    service_text = (
        ", ".join(services)
        if services
        else "AWS General"
    )

    # --------------------------------------------------
    # Priority formatting
    # --------------------------------------------------

    if priority == "HIGH":

        priority_label = "🚨 HIGH"
        priority_color = "Attention"

    elif priority == "MEDIUM":

        priority_label = "⚠️ MEDIUM"
        priority_color = "Warning"

    else:

        priority_label = "ℹ️ LOW"
        priority_color = "Accent"

    # --------------------------------------------------
    # Description
    # --------------------------------------------------

    description = (
        item.get(
            "description",
            ""
        )
        .strip()
    )

    if not description:

        description = (
            "AWS has published a change "
            "for this service."
        )

    # Keep Teams card readable
    if len(description) > 2000:

        description = (
            description[:2000]
            + "..."
        )

    # --------------------------------------------------
    # GitHub issue action
    # --------------------------------------------------

    actions = []

    if item.get("link"):

        actions.append({

            "type":
                "Action.OpenUrl",

            "title":
                "View AWS Announcement",

            "url":
                item["link"]
        })

    if issue_url:

        actions.append({

            "type":
                "Action.OpenUrl",

            "title":
                "View GitHub Issue",

            "url":
                issue_url
        })

    # --------------------------------------------------
    # Adaptive Card
    # --------------------------------------------------

    card = {

        "type": "message",

        "attachments": [

            {

                "contentType":
                    "application/vnd.microsoft.card.adaptive",

                "contentUrl":
                    None,

                "content": {

                    "$schema":
                        "http://adaptivecards.io/schemas/adaptive-card.json",

                    "type":
                        "AdaptiveCard",

                    "version":
                        "1.2",

                    "body": [

                        # --------------------------------
                        # Header
                        # --------------------------------

                        {

                            "type":
                                "TextBlock",

                            "text":
                                "🚨 AWS CHANGE DETECTED",

                            "weight":
                                "Bolder",

                            "size":
                                "Large",

                            "wrap":
                                True
                        },

                        {

                            "type":
                                "TextBlock",

                            "text":
                                item["title"],

                            "weight":
                                "Bolder",

                            "size":
                                "Medium",

                            "wrap":
                                True,

                            "spacing":
                                "Small"
                        },

                        # --------------------------------
                        # Priority
                        # --------------------------------

                        {

                            "type":
                                "TextBlock",

                            "text":
                                priority_label,

                            "weight":
                                "Bolder",

                            "color":
                                priority_color,

                            "spacing":
                                "Small"
                        },

                        # --------------------------------
                        # Service information
                        # --------------------------------

                        {

                            "type":
                                "FactSet",

                            "facts": [

                                {

                                    "title":
                                        "AWS Service",

                                    "value":
                                        service_text
                                },

                                {

                                    "title":
                                        "Published",

                                    "value":
                                        item.get(
                                            "published",
                                            "Unknown"
                                        )
                                },

                                {

                                    "title":
                                        "Change Type",

                                    "value":
                                        "AWS What's New / Security"
                                }

                            ],

                            "spacing":
                                "Medium"
                        },

                        # --------------------------------
                        # Divider
                        # --------------------------------

                        {

                            "type":
                                "TextBlock",

                            "text":
                                "What changed",

                            "weight":
                                "Bolder",

                            "size":
                                "Medium",

                            "spacing":
                                "Medium"
                        },

                        {

                            "type":
                                "TextBlock",

                            "text":
                                description,

                            "wrap":
                                True,

                            "spacing":
                                "Small"
                        },

                        # --------------------------------
                        # Operational impact
                        # --------------------------------

                        {

                            "type":
                                "TextBlock",

                            "text":
                                "Why this matters",

                            "weight":
                                "Bolder",

                            "size":
                                "Medium",

                            "spacing":
                                "Medium"
                        },

                        {

                            "type":
                                "TextBlock",

                            "text":
                                (
                                    "Review this AWS change to "
                                    "determine whether it affects "
                                    "your infrastructure, monitoring, "
                                    "security controls, automation, "
                                    "or operational procedures."
                                ),

                            "wrap":
                                True,

                            "spacing":
                                "Small"
                        }

                    ],

                    # ------------------------------------
                    # Buttons
                    # ------------------------------------

                    "actions":
                        actions
                }
            }
        ]
    }

    payload = json.dumps(
        card
    ).encode("utf-8")

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

            response_body = (
                response.read()
                .decode("utf-8")
            )

            print()
            print(
                "Microsoft Teams notification "
                "sent successfully."
            )

            print(
                f"Teams HTTP status: "
                f"{response.status}"
            )

            if response_body:

                print(
                    f"Teams response: "
                    f"{response_body}"
                )

    except Exception as error:

        print(
            "WARNING: Teams notification failed:"
        )

        print(error)


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
