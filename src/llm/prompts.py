"""Prompt construction for grounded answer synthesis."""

INSUFFICIENT_EVIDENCE_ANSWER = "I do not have enough evidence to answer this question."

SYSTEM_PROMPT = (
    "You are a project-knowledge assistant. Answer the user's question using ONLY "
    "the evidence provided below. Do not add facts, invent projects, infer "
    "requirements, invent dates, or fabricate change requests. Cite each source "
    "by its [number] whenever you use it. If the evidence does not answer the "
    "question, reply with exactly: "
    '"I do not have enough evidence to answer this question." '
    "Keep the answer to 2-3 concise sentences."
)

# Used when the question asks for an exact count / complete list ("how many books
# did X write", "list all ... by ..."). The evidence is exhaustively retrieved
# for these, so the answer must be exact — never a vague "several".
ENUMERATION_SYSTEM_PROMPT = (
    "You are a project-knowledge assistant. Answer the user's question using ONLY "
    "the evidence provided below. Do not add facts, invent projects, infer "
    "requirements, invent dates, or fabricate change requests. Cite each source "
    "by its [name] whenever you use it. If the evidence does not answer the "
    "question, reply with exactly: "
    '"I do not have enough evidence to answer this question." '
    "The question asks for an exact count and/or a complete list. Give the exact "
    "number and, when asked, every single item in a numbered list. Count distinct "
    "items (one per title/name), not chunks or duplicates. Never be vague: do not "
    "write 'several books like ...', 'some projects', 'a few items', or 'many'. "
    "If the evidence contains N items that match, answer N and name all of them. "
    "Prefer a bulleted/numbered list over prose for enumeration."
)


def _format_evidence(evidence: list[dict]) -> str:
    """Format ranked evidence into numbered blocks the model can cite."""
    blocks = []
    for i, ev in enumerate(evidence, start=1):
        name = ev.get("document_name", "unknown")
        path = ev.get("file_path", "")
        content = (ev.get("chunk_content") or "").strip()
        header = f"[{i}] Source: {name}"
        if path:
            header += f" ({path})"
        blocks.append(f"{header}\n{content}")

    return "\n\n".join(blocks)


def build_grounding_prompt(question: str, evidence: list[dict]) -> str:
    """Build a user prompt that feeds ranked evidence to the model.

    ``evidence`` is a list of dicts with keys ``document_name``, ``file_path``,
    and ``chunk_content``. Entries are numbered [1], [2], ... so the model can
    cite them.
    """
    evidence_text = _format_evidence(evidence)
    return (
        f"Question: {question}\n\n"
        f"Evidence:\n{evidence_text}\n\n"
        "Answer in 2-3 concise sentences using only the evidence above, "
        "citing sources by [number]."
    )


def build_enumeration_prompt(question: str, evidence: list[dict]) -> str:
    """Build the prompt for exact count / complete-list questions.

    Evidence may span more documents than a normal search (all matches are
    gathered), so the model is told to state the exact count and list everything.
    """
    evidence_text = _format_evidence(evidence)
    return (
        f"Question: {question}\n\n"
        f"Evidence:\n{evidence_text}\n\n"
        "Using only the evidence above, give the exact count and, if asked for "
        "titles/names, the complete list with every item. Do not use vague "
        "quantifiers ('several', 'some', 'a few'); state the exact number. "
        "Cite sources as [N]."
    )

