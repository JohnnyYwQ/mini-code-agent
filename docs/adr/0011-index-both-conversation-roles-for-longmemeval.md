---
status: superseded by ADR-0014
---

# Index both conversation roles for LongMemEval

The LongMemEval adapter indexes visible text from every user and assistant turn with explicit role labels and uses `answer_session_ids` as the session-level gold set for every non-abstention case. This matches the product's ability to extract Memory from both sides of a completed Turn and preserves assistant-origin evidence; changing to user-only evidence would invalidate comparisons with this baseline. Abstention cases remain visible in dataset statistics but are not scored as positive Recall or NDCG cases because they intentionally have no Evidence Session and the current retrieval contract has no rejection outcome.
