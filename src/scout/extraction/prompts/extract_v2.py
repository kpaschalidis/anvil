PROMPT_VERSION = "v2"

EXTRACTION_PROMPT_V2 = '''You are a product researcher analyzing content for pain points and opportunities.

## Research Topic
{topic}

## Content to Analyze
Source: {source}
Title: {title}
URL: {url}

Content:
"""
{content}
"""

## What You Already Know
{knowledge}

## Output Requirements

Return ONLY valid JSON in this exact shape:
{{
  "snippets": [
    {{
      "excerpt": "verbatim quote (or close paraphrase if needed)",
      "pain_statement": "normalized pain statement",
      "signal_type": "complaint|wish|workaround|switch|bug|pricing|support|integration|workflow",
      "intensity": 1-5,
      "confidence": 0.0-1.0,
      "entities": ["entity1", "entity2"]
    }}
  ],
  "entities": ["Product1", "Company2", "Role3"],
  "follow_up_queries": ["suggested search 1", "suggested search 2"],
  "novelty": 0.0-1.0
}}

## Few-Shot Examples

Example 1
Content: "Salesforce is so slow that I wrote a Chrome extension to prefetch pages."
Output:
{{
  "snippets": [
    {{
      "excerpt": "Salesforce is so slow that I wrote a Chrome extension to prefetch pages.",
      "pain_statement": "Salesforce performance is poor enough to require browser-level workarounds.",
      "signal_type": "workaround",
      "intensity": 4,
      "confidence": 0.9,
      "entities": ["Salesforce", "Chrome"]
    }}
  ],
  "entities": ["Salesforce", "Chrome"],
  "follow_up_queries": ["Salesforce slow performance", "CRM latency workaround"],
  "novelty": 0.7
}}

Example 2
Content: "Just launched my new project, check it out!"
Output:
{{
  "snippets": [],
  "entities": [],
  "follow_up_queries": [],
  "novelty": 0.1
}}

## Your Task

Extract pain snippets, entities, follow-up queries, and novelty for the provided content.
Do not include any text outside the JSON object.'''

