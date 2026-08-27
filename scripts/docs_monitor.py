import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
from urllib.request import Request, urlopen


CONFIG_FILE = "config/docs_sources.json"
STATE_FILE = "data/state.json"

TIMEOUT = 15


def load_json(path, default):
    if not os.path.exists(path):
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()

        if not content:
            return default

        return json.loads(content)

    except (json.JSONDecodeError, OSError):
        return default


def save_json(path, data):
    os.makedirs(
        os.path.dirname(path),
        exist_ok=True
    )

    with open(
        path,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False
        )


def fetch_feed(url):

    print(f"Fetching: {url}")

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
            f"WARNING: Could not fetch feed: {error}"
        )

        return None


def clean_text(text):

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

    if not xml_data:
        return []

    try:

        root = ET.fromstring(
            xml_data
        )

    except ET.ParseError as error:

        print(
            f"WARNING: Invalid RSS/XML: {error}"
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
            "title": clean_text(title),
            "link": link.strip(),
            "description":
                clean_text(description),
            "published":
                published.strip()
        })

    return entries


def generate_id(
    service,
    item
):

    raw = (
        service
        + "|"
        + item["title"]
        + "|"
        + item["link"]
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


def priority(item):

    text = (
        item["title"]
        + " "
        + item["description"]
    ).lower()

    high = [
        "new service",
        "new capability",
        "general availability",
        "launch",
        "security",
        "vulnerability",
        "deprecated",
        "deprecation",
        "end of support",
        "breaking change",
        "console"
    ]

    medium = [
        "new feature",
        "now supports",
        "support for",
        "available in",
        "enhancement",
        "integration",
        "monitoring",
        "api",
        "cli",
        "policy"
    ]

    if any(
        keyword in text
        for keyword in high
    ):
        return "HIGH"

    if any(
        keyword in text
        for keyword in medium
    ):
        return "MEDIUM"

    return "LOW"


def create_issue(
    service,
    item,
    level,
    source
):

    import subprocess

    title = (
        f"[AWS DOC {level}] "
        f"{service} - "
        f"{item['title']}"
    )

    body = f"""# AWS Documentation Change

## Service

{service}

## Priority

**{level}**

## Published

{item['published']}

## Change

{item['title']}

## Details

{item['description']}

## Official AWS Source

{item['link']}

## Monitoring Source

{source}

---

Automatically detected by AWS Change Monitor.
"""

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

        print(
            f"GitHub issue created: "
            f"{result.stdout.strip()}"
        )

    else:

        print(
            f"WARNING: GitHub issue failed: "
            f"{result.stderr}"
        )


def main():

    print()
    print(
        "=========================================="
    )
    print(
        " AWS DOCUMENTATION CHANGE MONITOR"
    )
    print(
        "=========================================="
    )

    config = load_json(
        CONFIG_FILE,
        {"sources": []}
    )

    state = load_json(
        STATE_FILE,
        {
            "last_run": None,
            "processed": []
        }
    )

    processed = set(
        state.get(
            "processed",
            []
        )
    )

    total_new = 0

    for source in config.get(
        "sources",
        []
    ):

        service = source.get(
            "service",
            "AWS"
        )

        url = source.get(
            "url"
        )

        if not url:
            continue

        print()
        print(
            f"Checking {service}..."
        )

        xml_data = fetch_feed(
            url
        )

        if not xml_data:
            continue

        entries = parse_feed(
            xml_data
        )

        print(
            f"Found {len(entries)} entries."
        )

        for item in entries:

            if not item["link"]:
                continue

            item_id = generate_id(
                service,
                item
            )

            if item_id in processed:
                continue

            level = priority(
                item
            )

            print()
            print(
                f"NEW: {service}"
            )

            print(
                f"Title: {item['title']}"
            )

            print(
                f"Priority: {level}"
            )

            # Only create issues for
            # meaningful changes.
            if level in [
                "HIGH",
                "MEDIUM"
            ]:

                create_issue(
                    service,
                    item,
                    level,
                    url
                )

            processed.add(
                item_id
            )

            total_new += 1

    state["processed"] = list(
        processed
    )[-5000:]

    save_json(
        STATE_FILE,
        state
    )

    print()
    print(
        "=========================================="
    )

    print(
        f"New documentation entries: "
        f"{total_new}"
    )

    print(
        "Documentation monitoring completed."
    )

    print(
        "=========================================="
    )


if __name__ == "__main__":
    main()
