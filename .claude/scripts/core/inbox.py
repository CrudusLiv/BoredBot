"""Auto-classify and summarise files dropped into Dynamous/Memory/inbox/.

Runs at the top of each heartbeat tick, BEFORE the snapshot diff. For each
.pptx/.pdf in the inbox:

    1. Extract text via .claude/skills/lecture-summarizer/scripts/extract.py
    2. Classify (cheap LLM call): lecture or project? Course/project name?
       Any deadlines mentioned in the text?
    3. Summarise with the type-appropriate prompt and write to:
         - lectures/<course>/<date>_<slug>.md  for lectures
         - projects/<project>/<date>_<slug>.md for project documents
    4. Move the source to inbox/_processed/
    5. Return any extracted deadlines so the heartbeat can promote them
       into DEADLINES.md ## Active.

Failures are caught per-file -- one broken PDF doesn't stop the others.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core import llm

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])

sys.path.insert(0, str(PROJECT_DIR / ".claude" / "scripts"))
sys.path.insert(0, str(PROJECT_DIR))
from integrations import vault_fs  # noqa: E402
from memory import wikilinks  # noqa: E402
from scripts.concept_linker import process_lecture_concepts  # noqa: E402
from scripts.roadmap_generator import generate_roadmap_file  # noqa: E402
from scripts.ocr_processor import (  # noqa: E402
    alert_ocr_failures, extract_slide_images, format_ocr_summary, merge_text, run_ocr_on_image
)

VAULT = PROJECT_DIR / "Dynamous" / "Memory"
LECTURES = VAULT / "lectures"
PROJECTS = VAULT / "projects"
SCREENSHOTS = VAULT / "screenshots"
EXTRACT_SCRIPT = PROJECT_DIR / ".claude" / "skills" / "lecture-summarizer" / "scripts" / "extract.py"

KL = timezone(timedelta(hours=8))

# Hard cap on extracted text we hand to the LLM. A 200-page PDF can blow past
# Haiku's practical reasoning window; truncating with a note is better than
# silently degrading or timing out.
MAX_EXTRACT_CHARS = 80_000
# Classification only needs a glimpse -- title, abstract, intro.
CLASSIFY_PEEK_CHARS = 3_500


CLASSIFY_SYSTEM = """You classify academic documents. Given a filename and the
first few thousand chars of a document, decide whether it is:

- "lecture": teaching material -- slides, lecture notes, textbook chapter,
  tutorial. Has didactic structure: concepts, examples, exercises.

- "project": project / assignment artefact -- a proposal, report, spec, design
  doc, dissertation, group submission. Has deliverables, deadlines, tech
  decisions, status.

Also extract:
- name: top-level category folder. The SUBJECT or COURSE that owns this
  material -- NOT a concept covered within it. A lecture about "Threads"
  belongs under "Operating_Systems" (the course), not "Threads" (the
  topic). "Iteration", "Loops", "Pointers", "Functions" are concepts
  inside a course -- never folder names.
    - For lecture: subject code or course name (DIP209, MATH202,
      "Operating_Systems", "Kotlin"). Preserve casing exactly as it
      appears in the source.
    - For project: subject code if present (DIP209, CS101); else a short
      name from the filename (e.g. "MSc_Project").
    - NEVER lowercase. NEVER use hyphens unless the source uses them.

  STRICT CATEGORY RULE: You MUST pick a name from the "Existing
  categories" list whenever the document plausibly belongs under one
  of them -- judged by subject codes mentioned in the source, course
  names referenced, OR the topic clearly being part of that subject's
  standard curriculum. Only invent a new category name when no existing
  category is a reasonable parent. When in doubt, prefer an existing
  category over creating a new one.
- subcategory: optional subfolder under name. ONLY for projects.
    - If the source is "Assignment 2" / "Project 1" / "Coursework 3" /
      "Assessment 2" etc., return "Assignment_2" / "Project_1" /
      "Coursework_3" / "Assessment_2" (preserve casing, replace spaces
      with underscores).
    - If the project document is a single piece (dissertation, capstone,
      thesis, MSc project) with no sub-numbering, return "".
    - For lectures, always return "".
- title: a one-line human-readable title for this document.
- deadlines: any dated milestones mentioned in the text. Empty list if none.
  Each: { "due_date": "YYYY-MM-DD", "title": "...", "context": "..." }.
  ONLY include items with an explicit date; never guess.

Output STRICT JSON, no prose, no fences:
{
  "type": "lecture" | "project",
  "name": "<top-level name preserving case>",
  "subcategory": "<subfolder name or empty string>",
  "title": "<one-line>",
  "deadlines": [ { "due_date": "...", "title": "...", "context": "..." } ]
}
"""

LECTURE_SUMMARY_SYSTEM = """You convert raw lecture material into a
student-friendly Obsidian note. Output STRICT markdown, no prose intro, no
code fences around the whole thing. Use this exact structure:

---
type: lecture
course: <course code or _uncategorised>
source_file: <original filename>
date: <YYYY-MM-DD>
tags: [lecture, <course>]
---

# <Lecture title>

## Key concepts
- <bulleted, terse, one idea per bullet>

## Worked examples
<verbatim examples / derivations / code from the source, in fenced blocks
where appropriate. Skip this section entirely if the source has none.>

## Study cards
- Q: <question> | A: <answer>
<5-10 cards drilling the most testable facts>

## Open questions
- <things the slides hint at but don't fully explain -- empty bullet list is fine>

Rules: Do NOT invent content not in the source. Wikilinks ([[note]]) only when
you're confident the target exists.
"""

PROJECT_SUMMARY_SYSTEM = """You convert a project / assignment document into a
detailed Obsidian project note. Output STRICT markdown, no prose intro, no
fences around the whole thing. Use this exact structure:

---
type: project
project: <project name preserving case>
source_file: <original filename>
date: <YYYY-MM-DD>
tags: [project, <project>]
---

# <Project title>

## Summary
<4-6 sentences: what the project is, what problem it solves, who it's for,
the high-level approach. Pull concrete facts from the source.>

## Background / motivation
<2-4 sentences on the context. Why does this project exist? What gap or
problem prompted it? Cite specifics from the source.>

## Objectives
- <each main objective as a bullet, verbatim where stated>

## Scope
- <in-scope items as bullets>
- <out-of-scope items if specified>

## Deliverables
- <each deliverable as a bullet -- what artefacts must be produced>

## Methodology / approach
<Detailed paragraphs or sub-headings on HOW the project is executed:
methods, frameworks, pipeline, system architecture. Be specific -- name
technologies, algorithms, design patterns mentioned in the source.>

## Tech stack
- <each technology with one-line role: e.g. "Node.js -- backend API server">

## Key dates
- <YYYY-MM-DD>: <milestone>
<Skip the whole section if no dates are mentioned.>

## Stakeholders / team
- <names, roles, supervisors, target users as bullets>
<Skip if not stated.>

## Risks / open items
- <known risks, open decisions, or unresolved questions>

## Notable details
<Anything else worth recording verbatim from the source: technical
specifications, evaluation criteria, success metrics, references. Use
sub-bullets liberally.>

Rules:
- Do NOT invent content not in the source. If a section has nothing,
  OMIT THE ENTIRE SECTION rather than writing a placeholder.
- Quote technical specifics verbatim when useful (algorithms, version
  numbers, parameter values).
- Use fenced code blocks for any code or pseudo-code from the source.
"""


def process_new_files() -> list[dict]:
    """Process every new file in inbox/. Returns a list of result dicts.

    Each entry: {
        "path": <abs Path to written note>,
        "type": "lecture" | "project",
        "name": <course or project slug>,
        "title": <one-line>,
        "source": <original filename>,
        "deadlines": [ {due_date, title, context, source} ]
    }
    """
    files = vault_fs.list_inbox_new()
    if not files:
        return []

    out: list[dict] = []
    for src in files:
        try:
            if src.suffix.lower() in (".png", ".jpg", ".jpeg"):
                result = _process_screenshot(src)
            else:
                result = _process_one(src)
            if result:
                out.append(result)
        except Exception as exc:
            print(f"inbox: failed on {src.name}: {exc}", file=sys.stderr)
    return out


def _open_image(path: Path):
    from PIL import Image
    return Image.open(path)


def _process_screenshot(src: Path) -> dict | None:
    """OCR a single dropped screenshot (no slide/page structure, unlike
    lecture PDFs/PPTX) and write it as a plain vault note under
    screenshots/. Returns None (leaving src in place) if OCR fails."""
    try:
        image = _open_image(src)
    except Exception as exc:
        print(f"inbox: failed to open screenshot {src.name}: {exc}", file=sys.stderr)
        return None

    text, confidence, error = run_ocr_on_image(image)
    if error or not text.strip():
        print(f"inbox: OCR failed for screenshot {src.name}: {error or 'empty text'}", file=sys.stderr)
        return None

    date = datetime.now(KL).strftime("%Y-%m-%d")
    title = _safe_name(src.stem) or "screenshot"
    note_md = (
        f"---\n"
        f"source: {src.name}\n"
        f"date: {date}\n"
        f"ocr_confidence: {confidence:.2f}\n"
        f"---\n\n"
        f"# {title}\n\n{text.strip()}\n"
    )

    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    base = f"{date}_{title}"
    note_path = SCREENSHOTS / f"{base}.md"
    i = 1
    while note_path.exists():
        note_path = SCREENSHOTS / f"{base}_{i}.md"
        i += 1
    note_path.write_text(note_md, encoding="utf-8")

    processed_dir = src.parent / "_processed"
    processed_dir.mkdir(exist_ok=True)
    moved = processed_dir / src.name
    ctr = 1
    while moved.exists():
        moved = processed_dir / f"{src.stem}_{ctr}{src.suffix}"
        ctr += 1
    src.rename(moved)

    return {
        "path": note_path, "type": "screenshot", "name": "screenshots",
        "subcategory": "", "title": title, "source": src.name,
        "deadlines": [], "tldr": [], "date": date, "study_cards": 0,
        "roadmap_notice": None,
    }


def _process_one(src: Path) -> dict | None:
    extract = _run_extract(src)
    if not extract or "error" in extract:
        msg = (extract or {}).get("error", "extract.py returned nothing")
        print(f"inbox: extract failed for {src.name}: {msg}", file=sys.stderr)
        return None

    augmented_extract, ocr_results = _run_ocr_augment(src, extract)
    flat_text = _flatten_extract(augmented_extract)
    if not flat_text.strip():
        print(f"inbox: {src.name} extracted to empty text; skipping", file=sys.stderr)
        return None

    classification = _classify(src.name, flat_text[:CLASSIFY_PEEK_CHARS])
    if not classification:
        print(f"inbox: classification failed for {src.name}; defaulting to lecture", file=sys.stderr)
        classification = {"type": "lecture", "name": _guess_course(src.name), "title": src.stem, "deadlines": []}

    raw_type = classification.get("type")
    doc_type: str = raw_type if raw_type in ("lecture", "project") else "lecture"
    name = _safe_name(classification.get("name") or "")
    subcategory = _safe_name(classification.get("subcategory") or "") if doc_type == "project" else ""
    if doc_type == "lecture" and not name:
        name = _guess_course(src.name) or "_uncategorised"
    if doc_type == "project" and not name:
        name = _safe_name(src.stem) or "_uncategorised"

    truncated = flat_text
    if len(truncated) > MAX_EXTRACT_CHARS:
        truncated = truncated[:MAX_EXTRACT_CHARS] + "\n\n[TRUNCATED -- source longer than 80k chars]"

    date = datetime.now(KL).strftime("%Y-%m-%d")
    system = LECTURE_SUMMARY_SYSTEM if doc_type == "lecture" else PROJECT_SUMMARY_SYSTEM
    prompt = (
        f"Source filename: {src.name}\n"
        f"Type: {doc_type}\n"
        f"Name: {name}\n"
        f"Today: {date}\n\n"
        f"Source content follows. Convert it to the note format from the system prompt.\n\n"
        f"---\n{truncated}\n---"
    )
    note_md = llm.call(prompt, system_prompt=system, model="haiku", task="inbox_format", timeout=180)
    if not note_md:
        print(f"inbox: LLM returned nothing for {src.name}; leaving source in inbox", file=sys.stderr)
        return None

    if ocr_results:
        note_md += f"\n\n_OCR Processing: {format_ocr_summary(ocr_results)}_"
        title = classification.get("title") or src.stem
        try:
            alert_ocr_failures(ocr_results, lecture_title=title)
        except Exception as exc:
            print(f"inbox: OCR alert failed for {src.name}: {exc}", file=sys.stderr)

    note_path = _write_note(src, doc_type, name, subcategory, date, note_md)
    wikilinks.add_sibling_wikilinks(note_path)
    # Wire concept linker for lectures to extract concepts and create stubs
    roadmap_notice = None
    if doc_type == "lecture":
        try:
            process_lecture_concepts(lecture_file=note_path, vault_dir=VAULT)
        except Exception as exc:
            print(f"inbox: concept linker failed for {note_path.name}: {exc}", file=sys.stderr)

        # Wire roadmap generator for lectures
        try:
            lecture_data = _extract_lecture_data(note_md)
            roadmap_file = generate_roadmap_file(note_path, lecture_data)
            roadmap_notice = _build_roadmap_notice(lecture_data, roadmap_file)
        except Exception as exc:
            print(f"inbox: roadmap generator failed for {note_path.name}: {exc}", file=sys.stderr)
    # Section 4: move src into _processed/ first so the carve-out applies,
    # then delete iff the written note passes the success check.
    processed_dir = src.parent / "_processed"
    processed_dir.mkdir(exist_ok=True)
    moved = processed_dir / src.name
    ctr = 1
    while moved.exists():
        moved = processed_dir / f"{src.stem}_{ctr}{src.suffix}"
        ctr += 1
    src.rename(moved)
    if not vault_fs.delete_after_success(moved, note_path):
        print(f"inbox: success_check failed for {note_path.name}; keeping source at {moved}", file=sys.stderr)

    # Stamp each deadline with source so deadlines.promote() can dedupe
    # across ticks.
    deadlines = []
    for d in classification.get("deadlines") or []:
        if not d.get("due_date") or not d.get("title"):
            continue
        deadlines.append({
            "due_date": d["due_date"],
            "title": d["title"],
            "course": name,
            "source": f"inbox:{src.name}:{d['due_date']}",
        })

    title = _extract_title(note_md) or classification.get("title") or src.stem
    tldr = _extract_tldr(note_md) if doc_type == "lecture" else []
    study_cards = _extract_study_card_count(note_md) if doc_type == "lecture" else 0
    return {
        "path": note_path,
        "type": doc_type,
        "name": name,
        "subcategory": subcategory,
        "title": title,
        "source": src.name,
        "deadlines": deadlines,
        "tldr": tldr,
        "date": date,
        "study_cards": study_cards,
        "roadmap_notice": roadmap_notice,
    }


def _classify(filename: str, peek_text: str) -> dict | None:
    existing = _existing_categories()
    existing_list = ", ".join(existing) if existing else "(none yet)"
    existing_block = (
        "Existing categories -- you MUST pick one of these unless the "
        "document is clearly outside ALL of their scopes. A lecture about a "
        "concept (Threads, Iteration, Loops, Functions, etc.) goes under "
        "the COURSE that teaches that concept; do NOT create a new folder "
        "named after the concept.\n"
        f"{existing_list}\n\n"
    )
    prompt = (
        existing_block
        + f"Filename: {filename}\n\n"
        + f"First chars of document:\n---\n{peek_text}\n---\n\n"
        + f"Return JSON per the schema in the system prompt."
    )
    return llm.call_json(prompt, system_prompt=CLASSIFY_SYSTEM, model="haiku", task="inbox_classify", timeout=60)


def _existing_categories() -> list[str]:
    """List top-level folder names under lectures/ and projects/ so the
    classifier can prefer an already-used code over a brand-new one."""
    found: set[str] = set()
    for root in (LECTURES, PROJECTS):
        if not root.exists():
            continue
        for p in root.iterdir():
            if p.is_dir() and not p.name.startswith("_") and not p.name.startswith("."):
                found.add(p.name)
    return sorted(found)


def _run_extract(src: Path) -> dict | None:
    # Capture as bytes -- some PDFs surface Windows-1252 / CP-1252 codepoints
    # (smart quotes, em-dashes) that aren't valid UTF-8. Decode with replace
    # so one bad byte doesn't abort the whole extract.
    try:
        result = subprocess.run(
            [sys.executable, str(EXTRACT_SCRIPT), str(src)],
            capture_output=True, timeout=90,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        print(f"inbox: extract subprocess failed: {exc}", file=sys.stderr)
        return None
    stdout = (result.stdout or b"").decode("utf-8", errors="replace")
    stderr = (result.stderr or b"").decode("utf-8", errors="replace")
    if result.returncode != 0:
        return {"error": stderr[:300]}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {"error": "extract.py emitted non-JSON output"}


def _run_ocr_augment(src: Path, extract: dict) -> tuple[dict, list[dict]]:
    """Run OCR on src and merge results into extract JSON.

    Returns (augmented_extract, ocr_results). On any failure, returns the
    original extract unchanged with an empty ocr_results list so the caller
    can continue without OCR.
    """
    import copy

    augmented = copy.deepcopy(extract)
    ocr_results: list[dict] = []

    ext = src.suffix.lower()
    try:
        images = extract_slide_images(
            pdf_path=src if ext == ".pdf" else None,
            pptx_path=src if ext == ".pptx" else None,
        )
    except Exception as exc:
        print(f"inbox: OCR image extraction failed for {src.name}: {exc}", file=sys.stderr)
        return augmented, []

    if not images:
        return augmented, []

    if extract.get("type") == "pptx":
        for slide_dict in augmented.get("slides", []):
            idx = slide_dict.get("slide_num", 1) - 1  # 0-based
            result: dict = {"slide": idx + 1}
            if idx < len(images):
                original = (slide_dict.get("title") or "") + "\n" + "\n".join(slide_dict.get("bullets") or [])
                ocr_text, confidence, error = run_ocr_on_image(images[idx])
                if error:
                    result["status"] = "failed"
                    result["error"] = error
                else:
                    result["status"] = "success"
                    result["confidence"] = confidence
                    merged, used = merge_text(original, ocr_text)
                    result["ocr_used"] = used
                    if used:
                        lines = [l.strip() for l in merged.splitlines() if l.strip()]
                        slide_dict["title"] = lines[0] if lines else slide_dict.get("title", "")
                        slide_dict["bullets"] = lines[1:] if len(lines) > 1 else []
            else:
                result["status"] = "skipped"
            ocr_results.append(result)

    elif extract.get("type") == "pdf":
        for page_dict in augmented.get("pages", []):
            idx = page_dict.get("page_num", 1) - 1  # 0-based
            result = {"slide": idx + 1}
            if idx < len(images):
                original = (page_dict.get("text") or "").strip()
                ocr_text, confidence, error = run_ocr_on_image(images[idx])
                if error:
                    result["status"] = "failed"
                    result["error"] = error
                else:
                    result["status"] = "success"
                    result["confidence"] = confidence
                    merged, used = merge_text(original, ocr_text)
                    result["ocr_used"] = used
                    if used:
                        page_dict["text"] = merged
            else:
                result["status"] = "skipped"
            ocr_results.append(result)

    return augmented, ocr_results


def _flatten_extract(extract: dict) -> str:
    """Flatten the extract.py JSON into one chunk of text. Handles both .pptx
    and .pdf shapes."""
    if extract.get("type") == "pptx":
        chunks = []
        for s in extract.get("slides", []):
            head = f"### Slide {s.get('slide_num')}: {s.get('title') or ''}".rstrip()
            bullets = "\n".join(f"- {b}" for b in s.get("bullets", []))
            notes = (s.get("notes") or "").strip()
            block = head
            if bullets:
                block += "\n" + bullets
            if notes:
                block += f"\n\n*Speaker notes:* {notes}"
            chunks.append(block)
        return "\n\n".join(chunks)
    if extract.get("type") == "pdf":
        chunks = []
        for p in extract.get("pages", []):
            text = (p.get("text") or "").strip()
            if not text:
                continue
            chunks.append(f"### Page {p.get('page_num')}\n{text}")
        return "\n\n".join(chunks)
    return ""


COURSE_RE = re.compile(r"^([A-Z]{2,6}\s?\d{2,4})", re.IGNORECASE)


def _guess_course(filename: str) -> str:
    m = COURSE_RE.match(filename)
    if not m:
        return "_uncategorised"
    return m.group(1).replace(" ", "").upper()


def _safe_name(s: str) -> str:
    """Filesystem-safe name that preserves the source's capitalisation.
    Replaces whitespace with underscores, strips characters Windows forbids
    in path segments, and caps length. Does NOT lowercase."""
    if not s:
        return ""
    s = re.sub(r"\s+", "_", s.strip())
    s = re.sub(r'[<>:"/\\|?*]', "", s)
    return s[:80]


def _write_note(src: Path, doc_type: str, name: str, subcategory: str, date: str, note_md: str) -> Path:
    root = LECTURES if doc_type == "lecture" else PROJECTS
    parent = root / name
    if subcategory:
        parent = parent / subcategory
    parent.mkdir(parents=True, exist_ok=True)
    # Preserve the source filename casing so search by filename works.
    base = f"{date}_{_safe_name(src.stem)}"
    dest = parent / f"{base}.md"
    i = 1
    while dest.exists():
        dest = parent / f"{base}_{i}.md"
        i += 1
    dest.write_text(note_md, encoding="utf-8")
    return dest


def _extract_title(note_md: str) -> str | None:
    for line in note_md.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def _extract_tldr(note_md: str, n: int = 3) -> list[str]:
    """First n bullets under '## Key concepts' -- used as the TL;DR posted
    to #lectures (Slice 4). Empty list if the section is missing or has no
    bullets. Strips leading dashes/asterisks; preserves the bullet text."""
    in_section = False
    out: list[str] = []
    for line in note_md.splitlines():
        if line.startswith("## "):
            in_section = (line.strip() == "## Key concepts")
            continue
        if not in_section:
            continue
        stripped = line.lstrip()
        if stripped.startswith(("- ", "* ")):
            out.append(stripped[2:].strip())
            if len(out) >= n:
                break
    return out


def _extract_study_card_count(note_md: str) -> int:
    """Count Q: lines under '## Study cards'.

    Returns 0 if the section is missing or has no Q: lines. Counting stops
    at the next ## heading."""
    in_section = False
    count = 0
    for line in note_md.splitlines():
        if line.startswith("## "):
            in_section = (line.strip() == "## Study cards")
            continue
        if not in_section:
            continue
        stripped = line.lstrip()
        if stripped.startswith(("- Q:", "* Q:", "Q:")):
            count += 1
    return count


def _extract_lecture_data(note_md: str) -> dict:
    """Extract structured data from a lecture markdown for roadmap generation.

    Extracts: title, objectives, problems, prior_lectures.
    Returns a dict suitable for passing to generate_roadmap_file()."""
    title = _extract_title(note_md) or "Untitled"

    # Extract objectives from ## heading or learning goals section
    objectives = []
    in_objectives = False
    for line in note_md.splitlines():
        if line.startswith("## "):
            in_objectives = line.strip() in ("## Objectives", "## Learning Objectives", "## Key concepts")
            if in_objectives and "## Key concepts" in line:
                # Key concepts as fallback objectives
                objectives = _extract_tldr(note_md, n=10)
                break
            continue
        if in_objectives:
            stripped = line.lstrip()
            if stripped.startswith(("- ", "* ")):
                objectives.append(stripped[2:].strip())
            elif line.startswith("## "):
                break

    # Extract problems from practice or problems section
    problems = []
    in_problems = False
    for line in note_md.splitlines():
        if line.startswith("## "):
            in_problems = line.strip() in ("## Practice Problems", "## Problems", "## Exercises")
            continue
        if in_problems:
            stripped = line.lstrip()
            if stripped.startswith(("- ", "* ")):
                problem_text = stripped[2:].strip()
                # Parse difficulty if present (e.g., "- **Easy** - problem text")
                difficulty = "Medium"
                if "**" in problem_text:
                    parts = problem_text.split("**")
                    if len(parts) >= 2:
                        difficulty = parts[1]
                        problem_text = "**".join(parts[2:]).lstrip(" - ").strip()
                problems.append({
                    "difficulty": difficulty,
                    "statement": problem_text
                })
            elif line.startswith("## "):
                break

    # Extract prior lectures from Open questions or prerequisites
    prior_lectures = []
    in_prior = False
    for line in note_md.splitlines():
        if line.startswith("## "):
            in_prior = line.strip() in ("## Open questions", "## Prerequisites", "## Prior knowledge")
            continue
        if in_prior:
            stripped = line.lstrip()
            if stripped.startswith(("- ", "* ")):
                prior_lectures.append(stripped[2:].strip())
            elif line.startswith("## "):
                break

    return {
        "title": title,
        "objectives": objectives,
        "problems": problems,
        "prior_lectures": prior_lectures
    }


def _build_roadmap_notice(lecture_data: dict, roadmap_file: Path) -> str:
    """Return a short human-readable roadmap-ready notice. Replaces the old
    _post_roadmap_embed, which posted this directly to Discord — the caller
    now decides where the notice goes."""
    course = lecture_data.get("course") or lecture_data.get("name") or ""
    title = lecture_data.get("title") or roadmap_file.stem
    label = f"{course} — {title}" if course else title
    return f"Roadmap ready: {label}"


DAILY = VAULT / "daily"

# Daily logs use a chronological chain (prev/next) rather than full sibling
# linking -- a year of daily notes all linked to each other is graph noise.
TIMELINE_BEGIN = "<!-- timeline:begin -->"
TIMELINE_END = "<!-- timeline:end -->"
DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")


def refresh_daily_timeline() -> None:
    """Rewrite the ## Timeline (prev/next) footer in every YYYY-MM-DD.md
    daily log. Called by the heartbeat once per tick so the chain stays
    correct as new days are added."""
    if not DAILY.exists():
        return
    dated = sorted(
        (p for p in DAILY.iterdir() if p.is_file() and DATE_RE.match(p.name)),
        key=lambda p: p.name,
    )
    for i, note in enumerate(dated):
        prev_note = dated[i - 1] if i > 0 else None
        next_note = dated[i + 1] if i < len(dated) - 1 else None
        _write_timeline(note, prev_note, next_note)


def _write_timeline(note: Path, prev: Path | None, nxt: Path | None) -> None:
    text = note.read_text(encoding="utf-8")
    begin = text.find(TIMELINE_BEGIN)
    if begin != -1:
        end = text.find(TIMELINE_END, begin)
        if end != -1:
            text = (text[:begin] + text[end + len(TIMELINE_END):]).rstrip() + "\n"
    if not (prev or nxt):
        note.write_text(text, encoding="utf-8")
        return
    parts: list[str] = []
    if prev:
        parts.append(f"← [[{prev.stem}]]")
    if nxt:
        parts.append(f"[[{nxt.stem}]] →")
    block = f"\n\n{TIMELINE_BEGIN}\n## Timeline\n{' · '.join(parts)}\n{TIMELINE_END}\n"
    note.write_text(text.rstrip() + block, encoding="utf-8")
