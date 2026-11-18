# ruff: noqa: E501  (the role lines and section names are prompt text)
"""Build the specialised router prompts (router_<intent>/v2.md) from the chat handbook.

Each intent gets a role line, the general answering rules, ONLY the handbook sections that its
questions need, and the "things you must not do" section. The handbook (prompts/chat_system/v1.md)
stays the single source of truth: edit it and run this script again, then give the new files a new
version number if the text changed.

    uv run python scripts/build_router_prompts.py
"""

from pathlib import Path

PROMPTS = Path(__file__).resolve().parent.parent / "src" / "ai_service" / "prompts"
HANDBOOK = PROMPTS / "chat_system" / "v1.md"
VERSION = "v2"

# the section names are the "# ..." headings of the handbook
COMMON = ["How to answer", "Things you must not do"]
INTENTS: dict[str, tuple[str, list[str]]] = {
    "admission": (
        "You are the admissions assistant of Bright Path Academy. You answer questions about joining: "
        "eligibility, entrance tests, documents, seats and how to enrol.",
        [
            "About the institute",
            "Courses and fees",
            "Admission steps",
            "Eligibility and age",
            "Equipment",
            "Contact and visits",
            "Common questions",
        ],
    ),
    "fees": (
        "You are the fees assistant of Bright Path Academy. You answer questions about prices, "
        "instalments, discounts, scholarships and the refund policy.",
        [
            "Courses and fees",
            "Combination packages",
            "Payment, instalments and scholarships",
            "Refund and transfer policy",
            "Common questions",
        ],
    ),
    "schedule": (
        "You are the timetable assistant of Bright Path Academy. You answer questions about class "
        "timings, batch start dates, holidays and changing batch.",
        [
            "About the institute",
            "Courses and fees",
            "Timetables",
            "Special batches and events",
            "Common questions",
        ],
    ),
    "academic": (
        "You are the academic assistant of Bright Path Academy. You answer questions about what is "
        "taught: syllabus, teachers, projects, certificates, recordings and notes.",
        [
            "Courses and fees",
            "Learning portal and materials",
            "Placement support",
            "Week-by-week syllabus (use it when a student asks what is taught and when)",
            "Instructors and mentors",
            "Rules for students",
            "Common questions",
        ],
    ),
    "complaint": (
        "You are the student-care assistant of Bright Path Academy. The sender reports something that "
        "went wrong. Say sorry once, in one sentence, and do not argue. Ask for what is needed to look "
        "into it (the date, the course, the payment or ticket number), say what happens next, and offer "
        "to connect the student with the admissions manager. Never promise a refund or a result that is "
        "not written in the handbook.",
        [
            "Payment, instalments and scholarships",
            "Refund and transfer policy",
            "Learning portal and materials",
            "Contact and visits",
            "Rules for students",
        ],
    ),
    "other": (
        "You are the front-desk assistant of Bright Path Academy. The message is a greeting, a thanks, "
        "a job or vendor message, or something unrelated. Reply politely and briefly. If it is about the "
        "institute, use the handbook; if it is not, say you can only help with the institute and point to "
        "the website contact form.",
        ["About the institute", "Contact and visits"],
    ),
}


def sections() -> dict[str, str]:
    found: dict[str, list[str]] = {}
    current = ""
    for line in HANDBOOK.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n"):
        if line.startswith("# "):
            current = line[2:].strip()
            found[current] = [line]
        elif current:
            found[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in found.items()}


def main() -> None:
    parts = sections()
    for intent, (role, wanted) in INTENTS.items():
        missing = [name for name in COMMON + wanted if name not in parts]
        if missing:
            raise SystemExit(f"{intent}: handbook sections not found: {missing}")
        body = [role, "", parts[COMMON[0]], ""]
        body += [parts[name] + "\n" for name in wanted]
        body += [parts[COMMON[1]]]
        out = PROMPTS / f"router_{intent}" / f"{VERSION}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(body).strip() + "\n", encoding="utf-8")
        print(f"{out.relative_to(PROMPTS)}: {len(out.read_text(encoding='utf-8')):>6} characters")
    print(f"the full handbook: {len(HANDBOOK.read_text(encoding='utf-8')):>6} characters")


if __name__ == "__main__":
    main()
