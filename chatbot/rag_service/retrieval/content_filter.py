"""Classify course text chunks for quiz vs general chat indexing."""



def is_assignment_or_instruction_chunk(text: str) -> bool:
    """
    True when a chunk is lab/assignment framing, not teachable subject matter.

    These chunks cause quiz models to ask meta questions like
    "What is the purpose of this lab activity?" instead of testing concepts.
    """
    t = (text or "").strip().lower()
    if len(t) < 80:
        return True

    instruction_patterns = [
        "purpose of this lab",
        "purpose of the lab",
        "objective of this lab",
        "objective of this activity",
        "in this lab activity",
        "this lab activity",
        "this lab is designed",
        "you are required to",
        "you must submit",
        "submit your",
        "due date",
        "grading rubric",
        "assessment criteria",
        "complete the following task",
        "follow these steps to complete",
        "download the template",
        "upload your",
        "learning objective",
        "course objective",
        "by the end of this lab",
        "instructions:",
        "assignment:",
    ]

    if any(p in t for p in instruction_patterns):
        return True

    # Short chunks that only describe what the student will do (not how concepts work).
    if len(t) < 400 and t.count("?") == 0:
        action_leads = ("in this lab", "this activity", "you will", "students will", "your task")
        if sum(1 for p in action_leads if p in t) >= 2:
            return True

    return False


def is_substantive_learning_content(text: str) -> bool:
    """
    Return True if a chunk is suitable for the quiz collection.

    Quiz indexing should only include educational substance (concepts, procedures,
    formulas, labs) — not course admin metadata, section titles, or grading info.
    """
    t = (text or "").strip().lower()

    if len(t) < 400:
        return False

    if is_assignment_or_instruction_chunk(text):
        return False

    bad_patterns = [
        "course full name:",
        "short name:",
        "course summary:",
        "grading",
        "attendance",
        "section ",
        "activity:",
        "week ",
        "learning outcomes",
        "course objective",
        "mid exam",
        "final exam",
        "--- file skipped",
        "[no extracted text",
    ]

    if any(x in t for x in bad_patterns):
        return False

    educational_signals = 0

    indicators = [
        ".",
        ":",
        "because",
        "therefore",
        "example",
        "method",
        "process",
        "algorithm",
        "system",
        "input",
        "output",
        "formula",
        "equation",
        "transform",
        "filter",
        "pixel",
        "matrix",
        "function",
        "definition",
    ]

    for x in indicators:
        if x in t:
            educational_signals += 1

    return educational_signals >= 3
