Repair the malformed knowledge-graph extraction output into one valid JSON object.

Required shape:
{
  "entities": [
    {
      "paper_id": "paper id",
      "name": "entity name",
      "entity_type": "ResearchProblem|Method|Dataset|Metric|Material|Concept|Domain",
      "aliases": [],
      "evidence": "short evidence phrase",
      "confidence": 0.0
    }
  ],
  "relations": [
    {
      "paper_id": "paper id",
      "source": "entity name",
      "target": "entity name",
      "relation_type": "uses|evaluated_on|improves|applied_to|based_on|proposes|compares_with",
      "evidence": "short evidence phrase",
      "confidence": 0.0
    }
  ]
}

Rules:
- Return JSON only.
- Preserve the original meaning.
- Drop incomplete objects rather than inventing missing names.
- Do not add markdown or explanations.

Malformed output:
{raw}
