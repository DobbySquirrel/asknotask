```markdown
# Prompt 1-BC (Single-Stage): Full 9-Type Ambiguity Detection
# Placeholders: `{schema_content}`, `{question}`, `{evidence}`

### Role
You are an expert database architect and NL2SQL disambiguation system.
Your task is to analyze a natural language question against a database schema and external evidence, and identify **all ambiguities** across the three stages of query construction: **Question Structure**, **Row Set**, and **Measure and Output**.

### Ambiguity Taxonomy (3 Stages, 9 Types)

#### Stage 1 — Question Structure (how the parts of the question combine)
- **Scope**: The range of an explicit or implicit quantifier over related rows is left open.
  1. *Explicit quantifiers ("each", "every", "all")*: include all readings the context allows among:
     - **Per entity**: a separate result for each entity individually.
     - **Shared by all entities**: a result common to every entity (explicit counting condition matching all entities).
     - **Across all entities together**: a single combined result over all entities as a whole.
  2. *Implicit quantifiers over related rows (e.g., "single-bonded molecules")*: whether the condition must hold for **all** related rows of an entity or for **at least one** related row.
- **Attachment**: Which constituent or conjunct a modifier, prepositional phrase, or relative clause attaches to and restricts (e.g., in "A and B in New York", whether "in New York" restricts both A and B, or only the nearest conjunct).

#### Stage 2 — Row Set (attributes, relationships, conditions identifying rows)
- **Column**: Which attribute a concept or phrase maps to (competing columns within the same table or across tables).
- **Join**: Which source table supplies an attribute when multiple tables hold overlapping attributes (direct table read vs. joining another table).
- **Value**: Which stored form of a value to match in a column, when candidate literals differ in case, abbreviation, spelling, or format.
- **NULL**: Whether rows with missing (`NULL`) values in a target column should be excluded (`EXCLUDE_NULL`) or kept (`KEEP_NULL`).

#### Stage 3 — Measure and Output (how rows are measured, ordered, returned)
- **Aggregate**: How a measure is defined—a stored summary column vs. a computed expression over raw columns, or competing aggregation formulas (e.g., SUM vs. AVG).
- **Project**: Which set and format of output columns to return in `SELECT` (one attribute vs. multiple; separate columns vs. concatenated).
- **Tie**: Whether all rows tied at an extreme value (`MAX`/`MIN`) are returned, or only a single row (`LIMIT` 1).

### Output Protocol (Strict JSON)
1. Output MUST be a valid JSON object mapping each ambiguous question span (exact substring from the question) to:
   `{"type": "<one of the 9 types>", "candidates": [candidate_1, candidate_2, ...]}`
2. **Candidate JSON Shapes by Type**:
   - **Scope / Attachment**: `["<short reading 1>", "<short reading 2>", ...]` — short sentences/phrases, each stating one distinct reading.
   - **Column / Join / Aggregate / Project**: `[{"table_name": ["column_or_expression"]}, ...]` — schema identifiers or expressions only; NEVER put sample cell values or literals inside a `Column`/`Join` candidate.
   - **Value**: `[{"table_name.column_name": "literal_value"}, ...]` — use only when the question mentions a specific value whose stored format is ambiguous.
   - **NULL**: `[{"table_name.column_name": "EXCLUDE_NULL"}, {"table_name.column_name": "KEEP_NULL"}]`.
   - **Tie**: `[{"table_name.column_name": "LIMIT"}, {"table_name.column_name": "MAX"}]`.
3. **Column vs. Value**: Sample values shown in the schema (e.g., `(e.g., "Director")`) illustrate what a column means; they are NOT `Value` candidates unless the question mentions a specific entity/literal whose stored formatting is uncertain.
4. Do not flag a span if `Note / Evidence` already settles the reading. Emit each span at most once, under its most specific type.
5. Output ONLY the JSON block within ```json ... ```. If no ambiguity exists, output ```json {} ```.

---

### Few-Shot Demonstrations

[Example 1: Scope — Explicit Quantifier]
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

[Example 4: Column — Attribute That a Concept Maps To]
Schema: [1] head : head_id, title (job title of head, e.g. "Director"), head_name (actual name of head, e.g. "John Doe"), age
Question: List the head name and age ordered by age.
Note / Evidence: NULL
Ambiguity Mapping:
```json
{
  "head name": {
    "type": "Column",
    "candidates": [
      {"head": ["title"]},
      {"head": ["head_name"]}
    ]
  }
}
```

[Example 5: Join — Source Table Supplying an Attribute]
Schema: [1] head : head_id, name, age, born_state [2] head_born : head_id, born_state
Question: List the name, age, and born state of department heads.
Note / Evidence: NULL
Ambiguity Mapping:
```json
{
  "born state": {
    "type": "Join",
    "candidates": [
      {"head": ["born_state"]},
      {"head_born": ["born_state"]}
    ]
  }
}
```

[Example 6: Value — Stored Form of a Value]
Schema: [1] district : A1 (district id), A3 (region name, e.g. "East Bohemia", "Prague")
Question: Find all bank accounts in East Bohemia region.
Note / Evidence: NULL
Ambiguity Mapping:
```json
{
  "East Bohemia": {
    "type": "Value",
    "candidates": [
      {"district.A3": "east Bohemia"},
      {"district.A3": "East Bohemia"}
    ]
  }
}
```

[Example 7: NULL — Treatment of Rows with Missing Values]
Schema: [1] satscores : cds, sname, AvgScrWrite (writing score, nullable)
Question: List all school names and their writing scores.
Note / Evidence: NULL
Ambiguity Mapping:
```json
{
  "writing scores": {
    "type": "NULL",
    "candidates": [
      {"satscores.AvgScrWrite": "EXCLUDE_NULL"},
      {"satscores.AvgScrWrite": "KEEP_NULL"}
    ]
  }
}
```

[Example 8: Aggregate — Definition of a Measure]
Schema: [1] frpm : CDSCode, Percent (free meal percentage, e.g. 85.5), Count (free meal count), Enrollment (total students)
Question: What is the eligible free meal rate of schools?
Note / Evidence: NULL
Ambiguity Mapping:
```json
{
  "eligible free meal rate": {
    "type": "Aggregate",
    "candidates": [
      {"frpm": ["Percent"]},
      {"frpm": ["Count / Enrollment * 100"]}
    ]
  }
}
```

[Example 9: Project — Set and Format of Output Columns]
Schema: [1] Personal_Devices : device_id, first_name, last_name, device_model
Question: Who has desktops and laptops with Linux?
Note / Evidence: NULL
Ambiguity Mapping:
```json
{
  "Who": {
    "type": "Project",
    "candidates": [
      {"Personal_Devices": ["first_name"]},
      {"Personal_Devices": ["first_name", "last_name"]}
    ]
  }
}
```

[Example 10: Tie — Treatment of Rows Tied at an Extreme Value]
Schema: [1] results : raceId, time, constructorId
Question: Which constructor won the race?
Note / Evidence: NULL
Ambiguity Mapping:
```json
{
  "won": {
    "type": "Tie",
    "candidates": [
      {"results.time": "LIMIT"},
      {"results.time": "MAX"}
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
