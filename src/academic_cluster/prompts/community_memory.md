You synthesize academic literature communities. Return only strict JSON.

Research topic:
{topic}

Cluster id: {cluster_id}
Cluster name: {cluster_name}

Papers:
{papers}

Evidence cards:
{evidence_cards}

KG entities:
{kg_entities}

KG relations:
{kg_relations}

Task:
Synthesize this research community for an academic survey. Follow SurveyG/AutoSurvey principles:
1. summarize the community as a coherent research direction, not a paper list;
2. identify method families, limitations, and future directions from the evidence;
3. flag weak coherence, outlier papers, and topic drift instead of forcing unrelated papers together;
4. do not invent paper_ids, evidence_card_ids, metrics, or claims.

Return strict JSON:
{{{{
  "community_summary": "Chinese synthesis, 3-5 sentences",
  "method_families": ["..."],
  "representative_claims": [
    {{{{"paper_id": "...", "evidence_card_id": "...", "claim": "...", "support": "...", "synthesis_role": "foundation|development|frontier|contrast|limitation"}}}}
  ],
  "limitations": ["..."],
  "future_directions": ["..."],
  "evidence_gaps": ["..."],
  "coherence_assessment": {{{{"score": 0.0, "rationale": "...", "outlier_paper_ids": ["..."]}}}},
  "topic_relevance": {{{{"score": 0.0, "rationale": "..."}}}}
}}}}
