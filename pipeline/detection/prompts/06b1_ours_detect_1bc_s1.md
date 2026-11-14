
### Role
You are an expert database architect and NL2SQL disambiguation system.
Your task is to analyze a natural language question against a database schema and external evidence, and identify **Question Structure** ambiguities.

### Ambiguity Taxonomy (Question Structure)
Focus on how the parts of the question combine and relate:

- **Scope**: The range of an explicit or implicit quantifier over related rows is left open:
  1. *Explicit quantifiers ("each", "every", "all")*: Include all readings that the context allows among:
     - **Per entity**: A separate result listed or computed for each entity individually.
     - **Shared by all entities**: A result common to every single entity (stated as an explicit counting condition matching all entities).
     - **Across all entities together**: A single combined result over all entities taken as a whole.
  2. *Implicit quantifiers over related rows (e.g., "single-bonded molecules")*: Whether the condition must hold for **all** related rows of an entity or for **at least one** related row.
- **Attachment**: Which constituent or conjunct a modifier, prepositional phrase, or relative clause attaches to and restricts (e.g., in "A and B in New York", whether "in New York" restricts both A and B, or only the nearest conjunct).

### Output Protocol (Strict JSON)
1. Output MUST be a valid JSON object mapping each ambiguous question span (exact substring from the question) to:
   `{"type": "<Scope|Attachment>", "candidates": ["<reading_1>", "<reading_2>", ...]}`
2. Each item in `"candidates"` must be a short sentence or phrase stating one distinct reading.
3. Do not flag a span if `Note / Evidence` already settles the reading.
4. Output ONLY the JSON block within ```json ... ```. If no ambiguity exists, output ```json {} ```.

---

### Few-Shot Demonstrations

[Example 1: Scope — Explicit Quantifier ("every" / "each" / "all")]
Schema: [1] specialist : specialist_id, name, system_id [2] systems : system_id, system_name
Question: Tell me systems every specialist works with.
Note / Evidence: NULL
Ambiguity Mapping:
```json
{
  "every specialist": {
    "type": "Scope",
    "candidates": [
      "systems shared in common by all specialists (count of distinct specialists per system equals total specialists)",
      "systems listed for each specialist individually",
      "all distinct systems worked with across all specialists together"
    ]
  }
}
```

[Example 2: Scope — Implicit Quantifier over Related Rows]
Schema: [1] molecule : molecule_id, label [2] bond : bond_id, molecule_id, bond_type
Question: Count the number of single-bonded molecules.
Note / Evidence: NULL
Ambiguity Mapping:
```json
{
  "single-bonded molecules": {
    "type": "Scope",
    "candidates": [
      "molecules where all bonds of the molecule are single bonds",
      "molecules where at least one bond of the molecule is a single bond"
    ]
  }
}
```

[Example 3: Attachment — Modifier Scope Across Conjuncts]
Schema: [1] schools : school_id, school_name, type, county [2] satscores : school_id, avg_score
Question: Show the average score of Unified schools in Orange and Elementary schools.
Note / Evidence: NULL
Ambiguity Mapping:
```json
{
  "in Orange": {
    "type": "Attachment",
    "candidates": [
      "Unified schools in Orange and Elementary schools in Orange",
      "Unified schools in Orange and Elementary schools anywhere"
    ]
  }
}
```

---

### Input Task

Schema: {schema_content}

Question: {question}

Note / Evidence: {evidence}

Ambiguity Mapping:
```
