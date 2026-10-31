"""Render a saved analysis with clickable references to its frozen source text."""

import argparse
import html
import json
import re
from pathlib import Path
from string import Template

from project_reader import SourceFile
from revival_analysis import FILE_REFERENCE, reference_fragments, resolve_reference


ROOT = Path(__file__).resolve().parent
INLINE = re.compile(r"(`[^`\n]+`|\*\*[^*\n]+\*\*|\[F\d+[^\]\n]*\])")


def source_snapshot(messages):
    for message in messages:
        if message.get("role") != "user":
            continue
        try:
            packet = json.loads(message["content"])
        except (ValueError, TypeError):
            continue
        if not isinstance(packet, dict) or "snapshot" not in packet:
            continue
        sources = {}
        for item in packet["snapshot"]["files"]:
            if not re.fullmatch(r"F[1-9]\d*", item["source_id"]) or item["source_id"] in sources:
                raise ValueError("Saved source identifiers are inconsistent.")
            lines = item["numbered_text"].splitlines()
            if any(not line.startswith(f"{i}: ") for i, line in enumerate(lines, 1)):
                raise ValueError("Saved source line numbers are inconsistent.")
            content_lines = [line.split(": ", 1)[1] for line in lines]
            text = "\n".join(content_lines)
            # A final numbered empty line needs its own terminator; otherwise
            # splitlines() drops it and exports reject a valid source snapshot.
            if content_lines and content_lines[-1] == "":
                text += "\n"
            redacted = tuple(i for i, line in enumerate(text.splitlines(), 1)
                             if line == "[credential-like value omitted]")
            source = SourceFile(item["path"], text, redacted)
            if source.line_count != item["line_count"]:
                raise ValueError("Saved source line count is inconsistent.")
            sources[item["source_id"]] = source
        return sources, packet.get("developer_goal", "")
    raise ValueError("No saved project evidence was found for this analysis.")


def citation_links(marker, sources):
    links = []
    for fragment in reference_fragments(marker):
        references, issue = resolve_reference(fragment, sources)
        if issue:
            links.append(f'<span title="Source location unavailable">{html.escape(fragment)}</span>')
            continue
        for reference in references:
            source_id, path = reference["source_id"], reference["path"]
            if reference["scope"] == "file":
                label = html.escape(f"{path} (file)")
                description = html.escape(f"Show {path}, whole file; no line range cited", quote=True)
                links.append(f'<a class="citation file-citation" href="#source-{source_id}" '
                             f'data-source="{source_id}" aria-label="{description}">{label}</a>')
            else:
                first, last = reference["first_line"], reference["last_line"]
                location = str(first) if first == last else f"{first}–{last}"
                label = html.escape(f"{path}:{location}")
                description = html.escape(f"Show {path}, lines {first} to {last}", quote=True)
                links.append(f'<a class="citation" href="#source-{source_id}-L{first}" '
                             f'data-source="{source_id}" data-first="{first}" data-last="{last}" '
                             f'aria-label="{description}">{label}</a>')
    return '<span class="references">[' + "; ".join(links) + "]</span>"


def inline(text, sources):
    output, position = [], 0
    for match in INLINE.finditer(text):
        output.append(html.escape(text[position:match.start()]))
        token = match[0]
        if token.startswith("`"):
            output.append("<code>" + html.escape(token[1:-1]) + "</code>")
        elif token.startswith("**"):
            output.append("<strong>" + inline(token[2:-2], sources) + "</strong>")
        else:
            output.append(citation_links(token, sources))
        position = match.end()
    output.append(html.escape(text[position:]))
    return "".join(output)


def render_report(text, sources):
    output, paragraph, list_type = [], [], None

    def flush():
        nonlocal list_type
        if paragraph:
            output.append("<p>" + inline(" ".join(paragraph), sources) + "</p>")
            paragraph.clear()
        if list_type:
            output.append(f"</{list_type}>")
            list_type = None

    for line in text.splitlines():
        heading = re.match(r"^(#{1,4})\s+(.+)", line)
        bullet = re.match(r"^\s*(?:([-*])\s+|\d+\.\s+)(.+)", line)
        if heading:
            flush()
            level = max(2, len(heading[1]))
            output.append(f"<h{level}>" + inline(heading[2], sources) + f"</h{level}>")
        elif bullet:
            wanted = "ul" if bullet[1] else "ol"
            if list_type != wanted or paragraph:
                flush()
                output.append(f"<{wanted}>")
                list_type = wanted
            output.append("<li>" + inline(bullet[2], sources) + "</li>")
        elif not line.strip():
            flush()
        else:
            if list_type:
                flush()
            paragraph.append(line.strip())
    flush()
    return "\n".join(output)


def render_sources(sources):
    cards, options = [], []
    for index, (source_id, source) in enumerate(sources.items()):
        options.append(f'<option value="{html.escape(source_id, quote=True)}">{html.escape(source.path)}</option>')
        lines = []
        for number, line in enumerate(source.text.splitlines(), 1):
            lines.append(f'<li id="source-{source_id}-L{number}" data-line="{number}">'
                         f'<code>{html.escape(line) or " "}</code></li>')
        hidden = " hidden" if index else ""
        cards.append(f'<section class="source-file" id="source-{source_id}"{hidden}>'
                     f'<h3>{html.escape(source.path)}</h3><ol class="source-lines">'
                     + "\n".join(lines) + "</ol></section>")
    return "\n".join(cards), "\n".join(options)


def render_page(text, messages, title):
    sources, goal = source_snapshot(messages)
    cards, options = render_sources(sources)
    template = Template((ROOT / "templates" / "review.html").read_text(encoding="utf-8"))
    return template.substitute(
        TITLE=html.escape(title), GOAL=html.escape(goal), REPORT=render_report(text, sources),
        SOURCES=cards, OPTIONS=options,
        CSS=(ROOT / "static" / "review.css").read_text(encoding="utf-8"),
        SCRIPT=(ROOT / "static" / "review.js").read_text(encoding="utf-8"),
    )


def write_review(run, title="Project analysis review"):
    run = Path(run)
    original = (run / "analysis.md").read_text(encoding="utf-8")
    messages = json.loads((run / "input.json").read_text(encoding="utf-8"))
    destination = run / "review.html"
    destination.write_text(render_page(original, messages, title), encoding="utf-8")
    return destination


def refresh_saved_navigation(source, destination):
    """Create a separate navigation copy of our saved HTML, preserving its prose."""
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        raise ValueError("Choose a new filename; the saved response must remain unchanged.")
    if source.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Choose a workbench review under 2 MB.")
    page = source.read_text(encoding="utf-8-sig")
    sources = {}
    for source_id, block in re.findall(
            r'<section class="source-file" id="source-(F[1-9]\d*)"[^>]*>(.*?)</section>', page, re.S):
        heading = re.search(r"<h3>(.*?)</h3>", block, re.S)
        lines = re.findall(r'<li[^>]*data-line="(\d+)"[^>]*><code>(.*?)</code></li>', block, re.S)
        if (source_id in sources or not heading or not lines
                or [int(n) for n, _ in lines] != list(range(1, len(lines) + 1))):
            raise ValueError("The saved source structure is inconsistent.")
        text = "\n".join(html.unescape(line) for _, line in lines)
        redacted = tuple(i for i, line in enumerate(text.splitlines(), 1)
                         if line == "[credential-like value omitted]")
        sources[source_id] = SourceFile(html.unescape(heading[1]), text, redacted)
    article = re.search(r"(<article\b[^>]*>)(.*?)(</article>)", page, re.S)
    if not sources or not article:
        raise ValueError("Choose an HTML review exported by this workbench.")
    converted = 0

    def replace_file_reference(match):
        nonlocal converted
        fragment = html.unescape(match[1])
        if not FILE_REFERENCE.fullmatch(fragment):
            return match[0]
        references, issue = resolve_reference(fragment, sources)
        if issue:
            return match[0]
        converted += len(references)
        rendered = citation_links(f"[{fragment}]", sources)
        return rendered.removeprefix('<span class="references">[').removesuffix("]</span>")

    report = re.sub(r'<span title="Source location unavailable">(.*?)</span>',
                    replace_file_reference, article[2], flags=re.S)
    updated = page[:article.start(2)] + report + page[article.end(2):]
    updated = re.sub(r"<style>.*?</style>", lambda _: "<style>" +
                     (ROOT / "static" / "review.css").read_text(encoding="utf-8") + "</style>",
                     updated, count=1, flags=re.S)
    updated = re.sub(r"<script>.*?</script>", lambda _: "<script>" +
                     (ROOT / "static" / "review.js").read_text(encoding="utf-8") + "</script>",
                     updated, count=1, flags=re.S)
    with destination.open("x", encoding="utf-8") as output:
        output.write(updated)
    return {"saved_to": str(destination), "file_links_added": converted}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--title", default="Project analysis review")
    args = parser.parse_args()
    print(write_review(args.run, args.title))
