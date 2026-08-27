import hashlib
import json
import os
import subprocess
from urllib.request import Request, urlopen


CONFIG_FILE = "config/api_services.json"
STATE_FILE = "data/api_state.json"

GITHUB_REPO = "aws/api-models-aws"

TIMEOUT = 20

GITHUB_API = (
    "https://api.github.com"
)


def load_json(path, default):

    if not os.path.exists(path):
        return default

    try:

        with open(
            path,
            "r",
            encoding="utf-8"
        ) as f:

            content = f.read().strip()

        if not content:
            return default

        return json.loads(content)

    except (
        json.JSONDecodeError,
        OSError
    ):

        return default


def save_json(path, data):

    directory = os.path.dirname(path)

    if directory:

        os.makedirs(
            directory,
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


def fetch_json(url):

    token = os.environ.get(
        "GH_TOKEN"
    )

    headers = {
        "User-Agent":
            "AWS-Change-Monitor/1.0",
        "Accept":
            "application/vnd.github+json"
    }

    if token:

        headers["Authorization"] = (
            f"Bearer {token}"
        )

    request = Request(
        url,
        headers=headers
    )

    try:

        with urlopen(
            request,
            timeout=TIMEOUT
        ) as response:

            return json.loads(
                response.read()
            )

    except Exception as error:

        print(
            f"WARNING: Failed to fetch:"
            f"\n{url}"
        )

        print(error)

        return None


def find_latest_model(
    sdk_id
):

    url = (
        f"{GITHUB_API}/repos/"
        f"{GITHUB_REPO}/contents/models/"
        f"{sdk_id}"
    )

    data = fetch_json(
        url
    )

    if not isinstance(
        data,
        list
    ):

        return None

    versions = []

    for item in data:

        if item.get(
            "type"
        ) != "dir":

            continue

        versions.append(
            item["name"]
        )

    if not versions:

        return None

    versions.sort(
        reverse=True
    )

    latest_version = versions[0]

    version_url = (
        f"{GITHUB_API}/repos/"
        f"{GITHUB_REPO}/contents/"
        f"models/{sdk_id}/"
        f"{latest_version}"
    )

    files = fetch_json(
        version_url
    )

    if not isinstance(
        files,
        list
    ):

        return None

    for item in files:

        name = item.get(
            "name",
            ""
        )

        if (
            name.lower()
            .endswith(".json")
        ):

            return {
                "version":
                    latest_version,

                "download_url":
                    item.get(
                        "download_url"
                    ),

                "path":
                    item.get(
                        "path"
                    )
            }

    return None


def fetch_model(
    download_url
):

    if not download_url:

        return None

    data = fetch_json(
        download_url
    )

    return data


def get_members(
    shape
):

    members = shape.get(
        "members",
        {}
    )

    if not isinstance(
        members,
        dict
    ):

        return []

    return sorted(
        members.keys()
    )


def get_enum_values(
    shape
):

    enum_values = []

    enum = shape.get(
        "enum",
        []
    )

    if isinstance(
        enum,
        list
    ):

        for value in enum:

            if isinstance(
                value,
                dict
            ):

                name = value.get(
                    "value"
                )

                if name:

                    enum_values.append(
                        name
                    )

            elif isinstance(
                value,
                str
            ):

                enum_values.append(
                    value
                )

    return sorted(
        set(enum_values)
    )


def summarize_model(
    model
):

    shapes = model.get(
        "shapes",
        {}
    )

    operations = {}

    structures = {}

    enums = {}

    for shape_id, shape in shapes.items():

        if not isinstance(
            shape,
            dict
        ):

            continue

        shape_type = shape.get(
            "type"
        )

        if shape_type == "operation":

            input_shape = (
                shape
                .get("input", {})
                .get("target")
            )

            output_shape = (
                shape
                .get("output", {})
                .get("target")
            )

            operations[
                shape_id
            ] = {
                "input":
                    get_members(
                        shapes.get(
                            input_shape,
                            {}
                        )
                    ),

                "output":
                    get_members(
                        shapes.get(
                            output_shape,
                            {}
                        )
                    )
            }

        elif shape_type == "structure":

            structures[
                shape_id
            ] = get_members(
                shape
            )

        elif shape_type == "string":

            values = get_enum_values(
                shape
            )

            if values:

                enums[
                    shape_id
                ] = values

    return {
        "operations":
            operations,

        "structures":
            structures,

        "enums":
            enums
    }


def calculate_hash(
    summary
):

    content = json.dumps(
        summary,
        sort_keys=True
    )

    return hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()


def compare_models(
    old,
    new
):

    changes = []

    old_operations = old.get(
        "operations",
        {}
    )

    new_operations = new.get(
        "operations",
        {}
    )

    old_structures = old.get(
        "structures",
        {}
    )

    new_structures = new.get(
        "structures",
        {}
    )

    old_enums = old.get(
        "enums",
        {}
    )

    new_enums = new.get(
        "enums",
        {}
    )

    # ------------------------------------------------
    # New API operations
    # ------------------------------------------------

    for operation in sorted(
        set(new_operations)
        - set(old_operations)
    ):

        changes.append({
            "type":
                "NEW_OPERATION",

            "name":
                operation
        })

    # ------------------------------------------------
    # Removed operations
    # ------------------------------------------------

    for operation in sorted(
        set(old_operations)
        - set(new_operations)
    ):

        changes.append({
            "type":
                "REMOVED_OPERATION",

            "name":
                operation
        })

    # ------------------------------------------------
    # Operation input/output changes
    # ------------------------------------------------

    for operation in sorted(
        set(old_operations)
        & set(new_operations)
    ):

        old_op = old_operations[
            operation
        ]

        new_op = new_operations[
            operation
        ]

        old_input = set(
            old_op.get(
                "input",
                []
            )
        )

        new_input = set(
            new_op.get(
                "input",
                []
            )
        )

        for member in sorted(
            new_input - old_input
        ):

            changes.append({
                "type":
                    "NEW_REQUEST_PARAMETER",

                "operation":
                    operation,

                "name":
                    member
            })

        for member in sorted(
            old_input - new_input
        ):

            changes.append({
                "type":
                    "REMOVED_REQUEST_PARAMETER",

                "operation":
                    operation,

                "name":
                    member
            })

        old_output = set(
            old_op.get(
                "output",
                []
            )
        )

        new_output = set(
            new_op.get(
                "output",
                []
            )
        )

        for member in sorted(
            new_output - old_output
        ):

            changes.append({
                "type":
                    "NEW_RESPONSE_FIELD",

                "operation":
                    operation,

                "name":
                    member
            })

        for member in sorted(
            old_output - new_output
        ):

            changes.append({
                "type":
                    "REMOVED_RESPONSE_FIELD",

                "operation":
                    operation,

                "name":
                    member
            })

    # ------------------------------------------------
    # New structures
    # ------------------------------------------------

    for structure in sorted(
        set(new_structures)
        - set(old_structures)
    ):

        changes.append({
            "type":
                "NEW_STRUCTURE",

            "name":
                structure
        })

    # ------------------------------------------------
    # Structure member changes
    # ------------------------------------------------

    for structure in sorted(
        set(old_structures)
        & set(new_structures)
    ):

        old_members = set(
            old_structures[
                structure
            ]
        )

        new_members = set(
            new_structures[
                structure
            ]
        )

        for member in sorted(
            new_members - old_members
        ):

            changes.append({
                "type":
                    "NEW_STRUCTURE_MEMBER",

                "structure":
                    structure,

                "name":
                    member
            })

    # ------------------------------------------------
    # Enum changes
    # ------------------------------------------------

    for enum_name in sorted(
        set(new_enums)
        & set(old_enums)
    ):

        old_values = set(
            old_enums[
                enum_name
            ]
        )

        new_values = set(
            new_enums[
                enum_name
            ]
        )

        for value in sorted(
            new_values - old_values
        ):

            changes.append({
                "type":
                    "NEW_ENUM_VALUE",

                "enum":
                    enum_name,

                "name":
                    value
            })

    return changes


def priority_for_change(
    change
):

    change_type = change[
        "type"
    ]

    if change_type in [
        "NEW_OPERATION",
        "NEW_REQUEST_PARAMETER",
        "NEW_RESPONSE_FIELD",
        "NEW_ENUM_VALUE",
        "NEW_STRUCTURE"
    ]:

        return "HIGH"

    if change_type in [
        "NEW_STRUCTURE_MEMBER"
    ]:

        return "MEDIUM"

    if change_type.startswith(
        "REMOVED"
    ):

        return "HIGH"

    return "MEDIUM"


def create_issue(
    service,
    version,
    changes
):

    high_count = sum(
        1
        for change in changes
        if priority_for_change(
            change
        ) == "HIGH"
    )

    priority = (
        "HIGH"
        if high_count
        else "MEDIUM"
    )

    title = (
        f"[AWS API {priority}] "
        f"{service} API model changed"
    )

    lines = []

    for change in changes:

        change_type = change[
            "type"
        ]

        if change_type == "NEW_OPERATION":

            lines.append(
                f"- **New API operation:** "
                f"`{change['name']}`"
            )

        elif change_type == "NEW_REQUEST_PARAMETER":

            lines.append(
                f"- **New request parameter:** "
                f"`{change['name']}` "
                f"for `{change['operation']}`"
            )

        elif change_type == "NEW_RESPONSE_FIELD":

            lines.append(
                f"- **New response field:** "
                f"`{change['name']}` "
                f"for `{change['operation']}`"
            )

        elif change_type == "NEW_STRUCTURE":

            lines.append(
                f"- **New structure:** "
                f"`{change['name']}`"
            )

        elif change_type == "NEW_STRUCTURE_MEMBER":

            lines.append(
                f"- **New structure member:** "
                f"`{change['name']}` "
                f"in `{change['structure']}`"
            )

        elif change_type == "NEW_ENUM_VALUE":

            lines.append(
                f"- **New enum/status value:** "
                f"`{change['name']}` "
                f"in `{change['enum']}`"
            )

        elif change_type.startswith(
            "REMOVED"
        ):

            lines.append(
                f"- ⚠️ **{change_type}:** "
                f"`{change.get('name')}`"
            )

    body = f"""# AWS API Model Change

## Service

{service}

## Priority

**{priority}**

## API Model Version

`{version}`

## Changes Detected

{chr(10).join(lines)}

## Source

https://github.com/aws/api-models-aws/tree/main/models

## Why this matters

AWS API model changes can expose new capabilities,
parameters, response fields, operations, or status values
that may later appear in AWS SDKs, CLIs, automation,
or the AWS Management Console.

---

Automatically detected by AWS Change Monitor.
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

            print(
                "GitHub issue created:"
            )

            print(
                result.stdout.strip()
            )

        else:

            print(
                "WARNING: GitHub issue creation failed:"
            )

            print(
                result.stderr
            )

    except subprocess.TimeoutExpired:

        print(
            "WARNING: GitHub issue creation timed out."
        )


def main():

    print()
    print(
        "=========================================="
    )
    print(
        "       AWS API MODEL MONITOR"
    )
    print(
        "=========================================="
    )

    config = load_json(
        CONFIG_FILE,
        {"services": []}
    )

    state = load_json(
        STATE_FILE,
        {
            "services": {}
        }
    )

    services_state = state.setdefault(
        "services",
        {}
    )

    total_changes = 0

    for service in config.get(
        "services",
        []
    ):

        name = service["name"]
        sdk_id = service["sdk_id"]

        print()
        print(
            f"Checking {name} "
            f"({sdk_id})..."
        )

        latest = find_latest_model(
            sdk_id
        )

        if not latest:

            print(
                f"WARNING: Could not find "
                f"model for {name}"
            )

            continue

        print(
            f"Latest model version: "
            f"{latest['version']}"
        )

        model = fetch_model(
            latest["download_url"]
        )

        if not model:

            print(
                f"WARNING: Could not download "
                f"{name} model."
            )

            continue

        summary = summarize_model(
            model
        )

        current_hash = calculate_hash(
            summary
        )

        previous = services_state.get(
            sdk_id
        )

        # -----------------------------------------
        # First run = establish baseline.
        # -----------------------------------------

        if not previous:

            print(
                f"Baseline created for {name}."
            )

            services_state[
                sdk_id
            ] = {
                "name": name,
                "version":
                    latest["version"],
                "hash":
                    current_hash,
                "summary":
                    summary
            }

            continue

        # -----------------------------------------
        # No model change.
        # -----------------------------------------

        if (
            previous.get("hash")
            == current_hash
        ):

            print(
                f"No API changes for {name}."
            )

            continue

        # -----------------------------------------
        # Model changed.
        # -----------------------------------------

        print(
            f"API MODEL CHANGED: {name}"
        )

        old_summary = previous.get(
            "summary",
            {}
        )

        changes = compare_models(
            old_summary,
            summary
        )

        print(
            f"Detected {len(changes)} "
            f"API changes."
        )

        if changes:

            for change in changes:

                print(
                    f"  - "
                    f"{change['type']}: "
                    f"{change.get('name', '')}"
                )

            create_issue(
                name,
                latest["version"],
                changes
            )

            total_changes += len(
                changes
            )

        services_state[
            sdk_id
        ] = {
            "name": name,
            "version":
                latest["version"],
            "hash":
                current_hash,
            "summary":
                summary
        }

    state["services"] = (
        services_state
    )

    save_json(
        STATE_FILE,
        state
    )

    print()
    print(
        "=========================================="
    )

    print(
        f"Total API changes: "
        f"{total_changes}"
    )

    print(
        "API model monitoring completed."
    )

    print(
        "=========================================="
    )


if __name__ == "__main__":
    main()
