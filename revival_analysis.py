"""Ask Gemma to explain a reviewed project snapshot and propose a restart plan."""

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from gemma_client import generate
from project_reader import scan_project


RULES_PATH = Path(__file__).resolve().parent / "prompts" / "revival-rules.md"
SYSTEM_PROMPT = RULES_PATH.read_text(encoding="utf-8").strip()
REFERENCE = re.compile(r"F(\d+):L(\d+)(?:-L?(\d+))?")
FILE_REFERENCE = re.compile(r"F([1-9]\d*)(?:\s*[-–]\s*F([1-9]\d*))?")


def reference_fragments(marker):
    return [fragment.strip() for fragment in re.split(r"[,;]", marker[1:-1])]


def resolve_reference(fragment, sources):
    """Resolve a supplied file or line location without guessing missing lines."""
    label = f"[{fragment}]"
    if len(fragment) > 80:
        return [], f"Unrecognized source reference: {label}"
    match = REFERENCE.fullmatch(fragment)
    if match:
        source_id = f"F{int(match[1])}"
        source = sources.get(source_id)
        first, last = int(match[2]), int(match[3] or match[2])
        if source is None:
            return [], f"Unknown source: {label}"
        if not 1 <= first <= last <= source.line_count:
            return [], f"Line range outside source: {label}"
        if any(first <= number <= last for number in source.redacted_lines):
            return [], f"Reference includes an omitted credential line: {label}"
        return [{"label": label, "source_id": source_id, "path": source.path,
                 "scope": "lines", "first_line": first, "last_line": last}], None
    match = FILE_REFERENCE.fullmatch(fragment)
    if not match:
        return [], f"Unrecognized source reference: {label}"
    first, last = int(match[1]), int(match[2] or match[1])
    if last < first or last - first + 1 > len(sources):
        return [], f"Invalid source file range: {label}"
    source_ids = [f"F{number}" for number in range(first, last + 1)]
    if any(source_id not in sources for source_id in source_ids):
        return [], f"Unknown source: {label}"
    return [{"label": f"[{source_id}]", "source_id": source_id,
             "path": sources[source_id].path, "scope": "file",
             "first_line": None, "last_line": None} for source_id in source_ids], None


def build_messages(snapshot, goal):
    if not snapshot.files:
        raise ValueError("Select at least one readable project file.")
    if not goal.strip() or len(goal) > 4000:
        raise ValueError("Describe your restart goal in 1-4,000 characters.")
    evidence = [{"source_id": f"F{i}", "path": source.path,
                 "line_count": source.line_count, "numbered_text": source.numbered_text()}
                for i, source in enumerate(snapshot.files, 1)]
    user = {"developer_goal": goal, "snapshot": {
        "files_included": len(snapshot.files), "items_excluded": len(snapshot.skipped),
        "note": "Only the supplied files were inspected; this may be a partial project.",
        "files": evidence,
    }}
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)}]


def check_references(text, snapshot):
    """Check reference targets and ranges, without claiming to verify factual support."""
    valid, issues = [], []
    sources = {f"F{i}": source for i, source in enumerate(snapshot.files, 1)}
    for bracket in re.finditer(r"\[([^\[\]\n]+)\]", text):
        if not re.match(r"F\d+\b", bracket[1]):
            continue
        for fragment in reference_fragments(bracket[0]):
            references, issue = resolve_reference(fragment, sources)
            if issue:
                issues.append(issue)
            else:
                valid.extend(dict(reference, marker=bracket[0]) for reference in references)
    if not valid:
        issues.append("No valid source references found.")
    return {"valid": valid, "issues": issues}


def analyze_project(snapshot, goal, *, project=None):
    messages = build_messages(snapshot, goal)
    result = generate(messages, project=project)
    result["reference_check"] = check_references(result["content"], snapshot)
    result["prompt_sha256"] = hashlib.sha256(json.dumps(messages, ensure_ascii=False).encode()).hexdigest()
    return result


def build_revision_messages(original_messages, original_answer, feedback):
    """Keep the original conversation and append feedback the developer approved."""
    if not feedback.strip() or len(feedback) > 4000:
        raise ValueError("Provide your answers or feedback in 1-4,000 characters.")
    if not original_answer.strip():
        raise ValueError("An existing analysis is required before revising it.")
    messages = [dict(message) for message in original_messages]
    if messages and messages[0].get("role") == "system":
        messages[0]["content"] = SYSTEM_PROMPT
    else:
        messages.insert(0, {"role": "system", "content": SYSTEM_PROMPT})
    return messages + [
        {"role": "assistant", "content": original_answer},
        {"role": "user", "content": feedback},
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--project")
    args = parser.parse_args()
    snapshot = scan_project(args.folder)
    messages = build_messages(snapshot, args.goal)
    run = Path(__file__).resolve().parent / "test" / "test-data" / "analyses" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run.mkdir(parents=True)
    (run / "input.json").write_text(json.dumps(messages, indent=2, ensure_ascii=False), encoding="utf-8")
    result = analyze_project(snapshot, args.goal, project=args.project)
    # Preserve the model's exact response. Reference checking never rewrites it.
    (run / "analysis.md").write_text(result["content"], encoding="utf-8")
    log = {k: v for k, v in result.items() if k != "content"}
    log["files"] = snapshot.manifest()
    (run / "run.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    print(json.dumps({"saved_to": str(run), "model": result["model"],
                      "seconds": result["seconds"], "finish_reason": result["finish_reason"],
                      "usage": result["usage"], "reference_issues": result["reference_check"]["issues"]}, indent=2))


if __name__ == "__main__":
    main()
