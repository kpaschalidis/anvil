PROMPT_VERSION = "v1"

EXTRACTION_PROMPT_V1 = '''You are a product researcher analyzing content for pain points and opportunities.

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

## Your Task

Analyze this content and extract:

1. **Pain Snippets**: Direct quotes or paraphrases that express problems, frustrations, wishes, or workarounds. For each snippet:
   - excerpt: The exact verbatim quote (or close paraphrase if needed)
   - pain_statement: A normalized, clear statement of the pain point
   - signal_type: One of: complaint, wish, workaround, switch, bug, pricing, support, integration, workflow
   - intensity: 1-5 (1=mild annoyance, 5=critical blocker)
   - confidence: 0.0-1.0 (how confident you are this is a real pain point)
   - entities: Products, tools, companies, or roles mentioned

2. **Entities**: All products, tools, companies, competitors, or job roles mentioned

3. **Follow-up Queries**: Suggested search queries to explore related pain points

4. **Novelty Score**: How much new information this contains vs what you already know (0.0=completely redundant, 1.0=completely new)

## Response Format

Respond with ONLY valid JSON in this exact format:
{{
  "snippets": [
    {{
      "excerpt": "exact quote from the content",
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

If the content has no pain points, return empty arrays but still provide entities if mentioned.
Do NOT include any text outside the JSON object.'''

