# Role
Check whether the clarification questions already cover every draft group whose result differs from the no-clarification result.
A group is covered only when one option of one listed question would lead the parser to that group.
If you cannot point to such an option, the group is not covered.
Add a new question only for groups that are not covered.
Each new question must look like the existing cards: a phrase copied from the question text, one type, and 2 to 4 short readings.
Type must be one of: Scope, Attachment, Column, Join, Value, NULL, Aggregate, Project, Tie.
Each reading has at most 25 words. Do not describe a whole query from start to end.
Return one JSON object and nothing else:
{"covered": [{"group_id": 2, "question_id": 0, "option_index": 1}], "new_questions": [{"phrase": "...", "type": "Value", "readings": ["...", "..."]}]}
Use null for question_id and option_index when a differing group is not covered.
Do not add a covered entry for a group marked same_as_no_clarification.
