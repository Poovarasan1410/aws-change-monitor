import hashlib
import json
import os
import re

import requests
from bs4 import BeautifulSoup


CONFIG_FILE = "config/docs_sources.json"
STATE_FILE = "data/state.json"


def load_json(path, default):

    if not os.path.exists(path):
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()

        if not content:
            return default

        return json.loads(content)

    except json.JSONDecodeError:
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


def normalize(text):

    if not text:
        return ""

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def fetch_page(url):

    headers = {
        "User-Agent":
            "AWS-Change-Monitor/1.0"
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=30
    )

    response.raise_for_status()

    return response.text


def extract_changes(html):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    changes = []

    tables = soup.find_all("table")

    for table in tables:

        rows = table.find_all("tr")

        if not rows:
            continue

        headers = [
            normalize(
                cell.get_text(
                    " ",
                    strip=True
                )
            ).lower()
            for cell in rows[0].find_all(
                ["th", "td"]
            )
        ]

        if not headers:
            continue

        change_index = None
        description_index = None
        date_index = None

        for i, header in enumerate(headers):

            if header == "change":
                change_index = i

            elif header == "description":
                description_index = i

            elif header in [
                "date",
                "release date"
            ]:
                date_index = i

        if change_index is None:
            continue

        for row in rows[1:]:

            cells = row.find_all(
                ["td", "th"]
            )

            values = [
                normalize(
                    cell.get_text(
                        " ",
                        strip=True
                    )
                )
                for cell in cells
            ]

            if len(values) <= change_index:
                continue

            change = values[
                change_index
            ]

            description = ""

            if (
                description_index is not None
                and len(values) >
                description_index
            ):
                description = values[
                    description_index
                ]

            date = ""

            if (
                date_index is not None
                and len(values) >
                date_index
            ):
                date = values[
                    date_index
                ]

            if not change:
                continue

            changes.append({
                "change": change,
                "description": description,
                "date": date
            })

    return changes


def create_change_id(
    service,
    change
):

    raw = (
        service
        + "|"
        + change["change"]
        + "|"
        + change["date"]
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


def calculate_priority(
    change
):

    text = (
        change["change"]
        + " "
        + change["description"]
    ).lower()

    high_keywords = [
        "new feature",
        "new capability",
        "new service",
        "now supports",
        "support added",
        "console",
        "status",
        "monitoring",
        "permission",
        "iam",
        "security",
        "deprecated",
        "deprecation",
        "end of support",
        "breaking"
    ]

    medium_keywords = [
        "updated",
        "added",
        "available",
        "support",
        "enhancement",
        "region",
        "api",
        "cli",
        "policy"
    ]

    for keyword in high_keywords:

        if keyword in text:
            return "HIGH"

    for keyword in medium_keywords:

        if keyword in text:
            return "MEDIUM"

    return "LOW"


def create_issue(
    service,
    change,
    priority,
    source_url
):

    import subprocess

    title = (
        f"[AWS DOC {priority}] "
        f"{service} - "
        f"{change['change']}"
    )

    body = f"""# AWS Documentation Change

## Service

{service}

## Priority

**{priority}**

## Date

{change['date']}

## Change

{change['change']}

## Description

{change['description']}

## AWS Documentation

{source_url}

---

Detected automatically by AWS Change Monitor.
"""

    result = subprocess.run(
        [
            "gh",
            "issue",
            "create",
            "--title",
            title,
            "--body",
            body,
            "--label",
            "aws,aws-documentation"
        ],
        capture_output=True,
        text=True
    )

    if result.returncode == 0:

        print(
            "Created GitHub issue:"
        )

        print(
            result.stdout.strip()
        )

    else:

        print(
            "Issue creation failed:"
        )

        print(
            result.stderr
        )


def main():

    print(
        "===================================="
    )

    print(
        " AWS DOCUMENTATION CHANGE MONITOR"
    )

    print(
        "===================================="
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

    for source in config["sources"]:

        service = source["service"]
        url = source["url"]

        print()
        print(
            f"Checking {service}..."
        )

        try:

            html = fetch_page(
                url
            )

            changes = extract_changes(
                html
            )

        except Exception as error:

            print(
                f"ERROR: {error}"
            )

            continue

        print(
            f"Found {len(changes)} "
            f"document history entries."
        )

        for change in changes:

            change_id = create_change_id(
                service,
                change
            )

            if change_id in processed:
                continue

            priority = calculate_priority(
                change
            )

            print()
            print(
                f"NEW CHANGE: "
                f"{service}"
            )

            print(
                f"Change: "
                f"{change['change']}"
            )

            print(
                f"Date: "
                f"{change['date']}"
            )

            print(
                f"Priority: "
                f"{priority}"
            )

            if priority in [
                "HIGH",
                "MEDIUM"
            ]:

                create_issue(
                    service,
                    change,
                    priority,
                    url
                )

            processed.add(
                change_id
            )

    state["processed"] = list(
        processed
    )[-5000:]

    save_json(
        STATE_FILE,
        state
    )

    print()
    print(
        "Documentation monitoring completed."
    )


if __name__ == "__main__":
    main()
