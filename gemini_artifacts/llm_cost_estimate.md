# GeoFlow LLM Cloud API Strategy & Cost Estimate

This document provides a compatibility matrix and cost estimate for utilizing Cloud-based Large Language Models (LLMs) with the GeoFlow application. 

> [!IMPORTANT]
> Based on your engineering constraints (50+ tasks/day, no internal GPUs, high complexity reasoning required), this report focuses exclusively on **Cloud APIs**. 

---

## 1. Workload Assumptions

To generate a realistic estimate, we model the daily workflow on the following token consumption per task (including automatic retries when scripts fail):

- **Average Input per Task:** ~4,000 tokens (System prompt, data schemas, code context, error traces)
- **Average Output per Task:** ~1,000 tokens (Generated Python scripts and plans)
- **Volume:** 50 tasks / day
- **Monthly Volume (30 days):** 6,000,000 Input Tokens | 1,500,000 Output Tokens

---

## 2. Recommended Tier 1 Models (High Reasoning)

For generating complex geospatial Python scripts (GeoPandas, Rasterio, Shapely), you need models with elite coding capabilities. We strongly recommend these models as the default for GeoFlow.

### A. Claude 3.5 Sonnet (Anthropic) - 🏆 *Top Recommendation*
Currently the highest-performing model for raw coding tasks and pipeline generation.
- **Input Cost:** $3.00 / 1M tokens
- **Output Cost:** $15.00 / 1M tokens
- **Estimated Monthly Cost:** **~$40.50 / month**
- **Compatibility:** **Native** (Integrated via Anthropic SDK in `geodb/agent_factory/llm_client.py`)

### B. Gemini 1.5 Pro (Google)
Extremely massive context window (up to 2M tokens) and highly cost-effective for complex reasoning.
- **Input Cost:** $3.50 / 1M tokens
- **Output Cost:** $10.50 / 1M tokens
- **Estimated Monthly Cost:** **~$36.75 / month**
- **Compatibility:** **Native** (Integrated via OpenAI compatibility REST layer)

### C. GPT-4o (OpenAI)
OpenAI's flagship model. Extremely fast and highly reliable for Python generation.
- **Input Cost:** $5.00 / 1M tokens
- **Output Cost:** $15.00 / 1M tokens
- **Estimated Monthly Cost:** **~$52.50 / month**
- **Compatibility:** **Native** (Integrated via standard OpenAI endpoint)

---

## 3. Tier 2 Models (Cost-Optimized / High Speed)

If the engineering team wants to minimize costs for simpler transformations, or build a hybrid router later (where simple tasks are sent to cheap models), these are the best alternatives.

### A. GPT-4o-mini (OpenAI)
Unbeatable price-to-performance ratio for everyday scripting.
- **Input Cost:** $0.15 / 1M tokens
- **Output Cost:** $0.60 / 1M tokens
- **Estimated Monthly Cost:** **~$1.80 / month**
- **Compatibility:** **Native**

### B. Claude 3 Haiku (Anthropic)
Incredibly fast response times.
- **Input Cost:** $0.25 / 1M tokens
- **Output Cost:** $1.25 / 1M tokens
- **Estimated Monthly Cost:** **~$3.37 / month**
- **Compatibility:** **Native**

---

## 4. Engineering Summary & Next Steps

> [!TIP]
> **Conclusion:** Even at 50+ tasks per day, running the absolute smartest models on the market will only cost your team **~$35 to $55 per month**. 

Given how inexpensive this is relative to engineering salaries, **we highly recommend acquiring an API key for Claude 3.5 Sonnet or OpenAI (GPT-4o)** to maximize the codebase's capability. 

### How to configure the API key in GeoFlow:
Once engineering provides the key, simply run:
```bash
# For Anthropic (Claude 3.5 Sonnet)
python -m geodb.transform config --provider anthropic --model claude-3-5-sonnet-20240620 --api-key YOUR_KEY

# For OpenAI (GPT-4o)
python -m geodb.transform config --provider openai --model gpt-4o --api-key YOUR_KEY
```
