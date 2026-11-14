Text-to-SQL task
The task is to write SQL queries based on the provided questions in English.
Questions can take the form of an instruction or command.
Do not include any explanations, and do not select extra columns beyond those requested in the question.
Use Evidence / user clarifications when present.
Target database is SQLite. Do NOT copy MySQL/generic functions from Evidence.
Forbidden: YEAR(), MONTH(), DAY(), SUBSTRING(), SUBTRACT(), CURDATE().
Use strftime('%Y', col), strftime('%m', col), substr(col, ...), and CAST(... AS INTEGER) instead.
Mapping snippets are already table.column — do not concatenate the column name again
(never emit table.col.col or alias."col.col").
Given the following SQLite database schema:

[SCHEMA_WITH_CONTENT]

Evidence: [EVIDENCE]

Answer the following: [QUESTION]

SQL: