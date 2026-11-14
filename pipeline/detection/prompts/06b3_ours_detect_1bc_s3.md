### Role
You are an expert database architect and NL2SQL disambiguation system.
Your task is to analyze a natural language question against a database schema and external evidence, and identify **Measure and Output** ambiguities.

### Ambiguity Taxonomy (Measure and Output)
Focus on how the rows are measured, ordered, and returned:

- **Aggregate**: How a measure is defined—such as choosing between a stored summary column and a computed expression over raw columns, or choosing among competing aggregation formulas (e.g., SUM vs. AVG).
- **Project**: Which set and format of output columns to return in `SELECT` (e.g., returning one attribute vs. multiple attributes, or returning attributes as separate columns vs. concatenated into one column).
- **Tie**: Whether all rows tied at an extreme value (`MAX` / `MIN`) are returned, or only a single row (`LIMIT` 1).

### Output Protocol (Strict JSON)
1. Output MUST be a valid JSON object mapping each ambiguous question span to:
   `{"type": "<Aggregate|Project|Tie>", "candidates": [candidate_1, candidate_2, ...]}`
2. **Candidate JSON Shapes by Type**:
   - **Aggregate**: `{"table_name": ["column_or_expression"]}`
   - **Project**: `{"table_name": ["col_1", ...]}`
   - **Tie**: `[{"table_name.column_name": "LIMIT"}, {"table_name.column_name": "MAX"}]`
3. Do not repeat spans already present in `Stage 1+2 ambiguities`, and do not flag spans already settled by `Note / Evidence`.
4. Output ONLY the JSON block within ```json ... ```. If no ambiguity exists, output ```json {} ```.

---

### Few-Shot Demonstrations

[Example 1: Aggregate — Definition of a Measure]
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

[Example 2: Project — Set and Format of Output Columns]
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

[Example 3: Tie — Treatment of Rows Tied at an Extreme Value]
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

Stage 1+2 ambiguities:
```json
{prior_ambiguities_json}
```

Ambiguity Mapping:
```
