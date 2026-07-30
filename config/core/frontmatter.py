import yaml


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter and return its metadata and document body."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return {}, text

    split_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.rstrip("\r\n") == "---":
            split_index = index
            break

    if split_index is None:
        return {}, text

    metadata_text = "".join(lines[1:split_index])
    body = "".join(lines[split_index + 1:])
    try:
        metadata = yaml.safe_load(metadata_text) or {}
    except yaml.YAMLError:
        metadata = {}

    if not isinstance(metadata, dict):
        metadata = {}
    return metadata, body
