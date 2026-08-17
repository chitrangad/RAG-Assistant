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


def build_grounding_prompt(question: str, evidence: list[dict]) -> str:
    """Build a user prompt that feeds ranked evidence to the model.

    ``evidence`` is a list of dicts with keys ``document_name``, ``file_path``,
    and ``chunk_content``. Entries are numbered [1], [2], ... so the model can
    cite them.
    """
    blocks = []
    for i, ev in enumerate(evidence, start=1):
        name = ev.get("document_name", "unknown")
        path = ev.get("file_path", "")
        content = (ev.get("chunk_content") or "").strip()
        header = f"[{i}] Source: {name}"
        if path:
            header += f" ({path})"
        blocks.append(f"{header}\n{content}")

    evidence_text = "\n\n".join(blocks)
    return (
        f"Question: {question}\n\n"
        f"Evidence:\n{evidence_text}\n\n"
        "Answer in 2-3 concise sentences using only the evidence above, "
        "citing sources by [number]."
    )
