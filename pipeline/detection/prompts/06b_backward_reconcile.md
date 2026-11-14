### Role
You are reconciling Backward detection proposals against an existing Forward question list.

### Existing Forward questions
These questions are already on the list. You must not delete, rewrite, or remove any of them.

```json
{forward_questions_json}
```

### Backward proposals
These are candidate questions collected from Backward (draft-gated S1+S2+S3). Judge each one.

```json
{backward_proposals_json}
```

### Allowed actions
You may only use these three actions, and no others:

- **add_question**: this proposal is a truly new question/card. Keep it as its own card.
- **add_reading**: this proposal adds a truly new reading (candidate) to an existing Forward card. Name the target Forward span and only the new candidates. Do not repeat candidates the Forward card already has. Do not create a second card for a paraphrase of the same question.
- **skip**: this proposal is only a paraphrase of an existing Forward card and has no new reading. Do not add it. Never delete the existing Forward card.

Do not emit a delete action. Do not emit an exact copy of an existing Forward card (same span, same type, and identical candidates). If you are not sure it is truly new, use skip.

### Output protocol
Output ONLY a JSON block within ```json ... ```:

```json
{
  "actions": [
    {"proposal_index": 0, "action": "add_question", "span": "<span>", "type": "<type>", "candidates": ["..."]},
    {"proposal_index": 1, "action": "add_reading", "target_span": "<existing Forward span>", "type": "<type>", "new_candidates": ["..."]},
    {"proposal_index": 2, "action": "skip", "reason": "paraphrase of existing card <span>"}
  ]
}
```

Give exactly one action for every Backward proposal, using its `proposal_index`.
