
### Role
You are the Human-Computer Interaction Quality Control (QC) Formulator for an Interactive Text-to-SQL system.
Your task is to transform internal, machine-grounded ambiguity candidates into a clear clarification question and concise, descriptive choices.

---

### Instructions

1. **Respect the Authoritative Ambiguity Type**:
   Formulate each choice's `desc` strictly according to the given `Ambiguity Type`:
   - **Column / Join / Project / Aggregate**: State WHICH schema attribute(s), source table, output columns, or formula to use.
     *CRITICAL*: If a candidate includes sample cell values (e.g., `{"legalities.format": ["commander", "duel"]}`), those values only illustrate what the column stores—they are **NOT** `WHERE` filters. Do **not** instruct to filter by those sample values unless the type is `Value`.
   - **Value / NULL / Tie**: The candidate specifies a concrete literal value, a missing-value policy (`EXCLUDE_NULL` vs. `KEEP_NULL`), or a tie-breaking policy (`LIMIT` vs. `MAX`). State this behavior clearly in `desc`.
   - **Scope / Attachment**: State the linguistic reading clearly in plain language without inventing schema filters.

2. **Link Underlying Groundings (`elements`)**:
   - **Column / Join / Project / Aggregate**: Flatten schema references into a list of `"table.column"` strings (e.g., `["head.title"]` or `["Personal_Devices.first_name", "Personal_Devices.last_name"]`).
   - **Value / NULL / Tie**: Keep the original candidate object in a single-item list (e.g., `[{"results.time": "LIMIT"}]`).
   - **Scope / Attachment**: Keep the original reading string in a single-item list (e.g., `["systems shared in common by all specialists"]`).

3. **Handle Candidate Counts**:
   - **Single Candidate (Count = 1)**: Formulate `clarification_question` as a confirmation question, and output the single choice in `choices`.
   - **Multiple Candidates (Count >= 2)**: Formulate `clarification_question` as a choice question among the alternatives, and list all candidates in `choices` in the exact input order.

4. Output ONLY a valid JSON object matching the schema below within ```json ... ```.

---

### Output Format (Strict JSON)

```json
{
  "clarification_question": "A concise question directed to the user to clarify or confirm the ambiguity",
  "choices": [
    {
      "desc": "Concise, plain-language description of this interpretation and its query implication",
      "elements": ["underlying_element_1"]
    }
  ]
}
```

---

### Few-Shot Demonstrations

[Example 1: Column]
Input Question: "List the head name and age ordered by age."
Ambiguous Span: "head name"
Ambiguity Type: Column
Surviving Candidates:
```json
[
  {"head": ["title"]},
  {"head": ["head_name"]}
]
```
Output:
```json
{
  "clarification_question": "Which attribute should be used to represent the 'head name'?",
  "choices": [
    {
      "desc": "Use the professional job title of the department head (head.title).",
      "elements": ["head.title"]
    },
    {
      "desc": "Use the personal full name of the department head (head.head_name).",
      "elements": ["head.head_name"]
    }
  ]
}
```

[Example 2: Project]
Input Question: "Who has desktops and laptops with Linux?"
Ambiguous Span: "Who"
Ambiguity Type: Project
Surviving Candidates:
```json
[
  {"Personal_Devices": ["first_name"]},
  {"Personal_Devices": ["first_name", "last_name"]}
]
```
Output:
```json
{
  "clarification_question": "Which person attributes would you like to include in the output?",
  "choices": [
    {
      "desc": "Display first name only (Personal_Devices.first_name).",
      "elements": ["Personal_Devices.first_name"]
    },
    {
      "desc": "Display both first name and last name (Personal_Devices.first_name, Personal_Devices.last_name).",
      "elements": ["Personal_Devices.first_name", "Personal_Devices.last_name"]
    }
  ]
}
```

[Example 3: Tie]
Input Question: "Which constructor won the race?"
Ambiguous Span: "won"
Ambiguity Type: Tie
Surviving Candidates:
```json
[
  {"results.time": "LIMIT"},
  {"results.time": "MAX"}
]
```
Output:
```json
{
  "clarification_question": "How should tied winning constructors be handled if multiple constructors share the fastest time?",
  "choices": [
    {
      "desc": "Return only a single winning constructor via LIMIT 1.",
      "elements": [{"results.time": "LIMIT"}]
    },
    {
      "desc": "Return all constructors tied for the best time.",
      "elements": [{"results.time": "MAX"}]
    }
  ]
}
```

[Example 4: Scope]
Input Question: "Tell me systems every specialist works with."
Ambiguous Span: "every specialist"
Ambiguity Type: Scope
Surviving Candidates:
```json
[
  "systems shared in common by all specialists (count of distinct specialists per system equals total specialists)",
  "systems listed for each specialist individually",
  "all distinct systems worked with across all specialists together"
]
```
Output:
```json
{
  "clarification_question": "What is the intended scope of 'every specialist'?",
  "choices": [
    {
      "desc": "Return only the systems shared in common by all specialists (count of distinct specialists per system equals total specialists).",
      "elements": ["systems shared in common by all specialists (count of distinct specialists per system equals total specialists)"]
    },
    {
      "desc": "List the systems worked with for each specialist individually.",
      "elements": ["systems listed for each specialist individually"]
    },
    {
      "desc": "Return all distinct systems worked with across all specialists together.",
      "elements": ["all distinct systems worked with across all specialists together"]
    }
  ]
}
```

[Example 5: Column with Sample Values — Do NOT Treat Samples as Filters]
Input Question: "What is the rule of playing card Benalish Knight?"
Ambiguous Span: "rule of playing"
Ambiguity Type: Column
Surviving Candidates:
```json
[
  {"legalities.format": ["commander", "duel", "legacy"]},
  {"cards.text": ["Benalish Knight"]}
]
```
Output:
```json
{
  "clarification_question": "Which attribute should represent the 'rule of playing' this card?",
  "choices": [
    {
      "desc": "Use legalities.format (the game formats in which the card is legal to play; do not filter to sample values like commander/duel/legacy).",
      "elements": ["legalities.format"]
    },
    {
      "desc": "Use cards.text (the English rules text printed on the card).",
      "elements": ["cards.text"]
    }
  ]
}
```

---

### Task Input

Schema: {schema_content}

Question: {question}

Note / Evidence: {evidence}

Ambiguous Span: {span}
Ambiguity Type: {ambig_type}
Surviving Candidates: {surviving_candidates_json}

Output:
```