import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.request import Request, urlopen


STATE_FILE = "data/state.json"

FEEDS = {
    "AWS What's New": "https://aws.amazon.com/about-aws/whats-new/recent/feed/",
    "AWS Security": "https://aws.amazon.com/security/security-bulletins/rss/"
}


def load_state():
    if not os.path.exists(STATE_FILE):
        return {
            "last_run": None,
            "processed": []
        }

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()

        if not content:
            return {
                "last_run": None,
                "processed": []
            }

        return json.loads(content)

    except json.JSONDecodeError:
        print("WARNING: Invalid state.json. Starting fresh.")

        return {
            "last_run": None,
            "processed": []
        }


def save_state(state):
    os.makedirs("data", exist_ok=True)

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            state,
            f,
            indent=2,
            ensure_ascii=False
        )


def fetch_feed(url):

    request = Request(
        url,
        headers={
            "User-Agent": "AWS-Change-Monitor/1.0"
        }
    )

    with urlopen(request, timeout=30) as response:
        return response.read()


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


def parse_feed(xml_data):

    root = ET.fromstring(xml_data)

    entries = []

    for item in root.findall(".//item"):

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
            "title": clean_html(title),
            "link": link.strip(),
            "description": clean_html(description),
            "published": published.strip()
        })

    return entries


def generate_id(item):

    raw = (
        item["title"]
        + "|"
        + item["link"]
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


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
            detected.append(service)

    return detected


def create_issue(item, priority, services):

    token = os.environ.get("GH_TOKEN")

    if not token:
        print("GH_TOKEN not available.")
        return

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

    import subprocess

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
        text=True
    )

    if result.returncode == 0:

        print(
            "GitHub Issue created:"
        )

        print(
            result.stdout.strip()
        )

    else:

        print(
            "Failed to create issue:"
        )

        print(
            result.stderr
        )


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
                f"Services: "
                f"{', '.join(services) or 'General AWS'}"
            )

            # Create GitHub issue only for
            # meaningful changes.
            if priority in [
                "HIGH",
                "MEDIUM"
            ]:

                create_issue(
                    item,
                    priority,
                    services
                )

            processed.add(
                item_id
            )

            new_items.append(
                item_id
            )

    now = datetime.now(
        timezone.utc
    ).isoformat()

    state["last_run"] = now

    state["processed"] = list(
        processed
    )[-2000:]

    save_state(state)

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


if __name__ == "__main__":
    main()
