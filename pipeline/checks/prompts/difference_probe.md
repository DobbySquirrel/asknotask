You generate controlled SQL queries to test the interpretations of ONE ambiguity in a natural-language question.

For each indexed candidate, produce exactly one read-only SQLite query that answers the original question under THAT candidate's interpretation.

The purpose is to test whether the candidate interpretations lead to different observable answers. Do not choose which interpretation is intended.

Inputs:
Question: {question}
Schema: {schema}
Evidence: {evidence}
Ambiguous span: {span}
Ambiguity type: {type}
Other unresolved ambiguities and their fixed readings: {other_fixed_readings}

The following list contains the FULL candidate payloads. Preserve the candidate indices and use each candidate's own payload:
{options}

Rules:

1. Return one query entry for every candidate index, exactly once. Do not omit, duplicate, renumber, or reorder indices.

2. Keep the original question, schema, evidence, and all unrelated choices fixed. Vary only the indexed ambiguity. Do not resolve other ambiguities differently across queries.

3. Each SQL must answer the complete original question under its candidate. Do not generate a local probe, partial query, or diagnostic-only query.

4. Implement the candidate's specific binding and operation explicitly:
   - Use the candidate's stated table, column, join endpoints, literal, predicate, aggregation, projection, NULL treatment, scope, attachment, or tie handling.
   - Do not replace a candidate with another plausible reading.
   - Do not silently ignore any operator or constraint in the candidate payload.
   - For Attachment, implement which part or parts of the question the modifier applies to. Preserve per-item versus collective scope where specified.
   - For Scope, implement the candidate's unit of comparison or aggregation (per-item versus collective, or the specified grouping window). Do not switch to the alternative scope.

5. Use only tables and columns present in the schema. Use exact stored literal spellings supported by the question, evidence, or schema. Do not invent values, bindings, or relationships.

6. If a candidate requires a binding or operation that cannot be implemented from the schema, return a null SQL for that candidate and explain the specific obstacle in "issue". Do not substitute a nearby column, entity, or interpretation.

7. Do not use LIMIT to shorten results unless the original question or this candidate explicitly requires a limit.

8. Keep result projections as faithful to the original question and candidate as possible. Do not add diagnostic columns solely to make queries distinguishable.

9. Use SQLite syntax. Queries must be read-only SELECT statements, including any required CTEs.

10. Do not use execution results, expected result sizes, likely user intent, or a preferred interpretation to decide what SQL to write.

Return only valid JSON in this exact structure:
{
  "queries": [
    {
      "index": 0,
      "candidate": <the exact candidate payload for this index>,
      "sql": "SELECT ...",
      "implemented_binding": "the concrete candidate-specific binding or operation represented by this SQL",
      "issue": null
    }
  ]
}

If a candidate is not implementable, use:
{
  "index": 0,
  "candidate": <the exact candidate payload for this index>,
  "sql": null,
  "implemented_binding": "",
  "issue": "Specific schema or semantic obstacle"
}

Return no prose or markdown outside the JSON.
