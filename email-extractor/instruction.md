# Email Extraction System

## 1. Setup Instructions

```bash
"""
install docker and docker-compose : https://docs.docker.com/compose/install/

Copy the .env.example file to same dir where Dockerfile and docker-compose.yml file 
exists and rename it to .env .Then replace GROQ_API_KEY value with your own API key.

You can also configure the input/output file paths in the .env file if needed:
INPUT_FILE="/data/emails_input.json"
PORT_CODES_FILE="/data/port_codes_reference.json"
OUTPUT_FILE="/data/output.json"
GROUND_TRUTH_FILE="/data/ground_truth.json"

Copy paste your test emails into the emails_input.json file that exists without changing the name same for ground truth and post_codes_reference also. 
"""

# start with docker
docker compose --env-file .env up --build
```

## 2. Prompt Evolution Log

### v1: Basic Extraction
- **Accuracy**: ~88%
- **Issues**: Port codes extracted as names, missing incoterms, India detection logic missing.
- **Example**: EMAIL_007 extracted "Chennai" instead of "INMAA".

### v2: Added UN/LOCODE Examples
- **Accuracy**: ~88.89%
- **Issues**: India detection failing for some ports (ICD ports).
- **Example**: EMAIL_023 incorrectly deduced product_line.

### v3: Explicit Business Rules
- **Accuracy**: ~94%
- **Issues**: Edge cases with multiple ports, transshipment confusion, and complex port names.

### v4: RT Handling, Code-to-Name, Post-Processing (Current)
- **Accuracy**: 97.78%
- **Improvements**: 
    - **RT Handling**: Converted "Revenue Ton" to Weight/CBM.
    - **Multi-Shipment**: Aggregated multiple origins/destinations.
    - **Transshipment**: Logic to pick final destination over POD.
    - **Port Name Cleaning**: Normalized "SHANGHAI" -> "Shanghai", removed city suffixes.

## 3. Accuracy Metrics

Current metrics based on `evaluate.py`:
- **Overall accuracy**: 97.78% (Correct fields / Total fields)
- **Product Line**: 100%
- **Port Codes**: 98%
- **Incoterms**: 100%
- **Cargo Metrics**: 96%
- **Dangerous Goods**: 100%

## 4. Edge Cases Handled

### Case 1: Multi-Shipment Aggregation
- **Email ID**: `EMAIL_007`
- **Problem**: Email listed 3 routes: "JED->MAA; DAM->BLR; RUH->HYD". v3 only extracted the first one.
- **Solution**: Added specific instruction to "combine ALL origins and ALL destinations with ' / '" when semicolons separators are present.

### Case 2: Transshipment vs Final Destination
- **Email ID**: `EMAIL_019`
- **Problem**: Email said "HAM to ICD WHITEFIELD, routed via Chennai". Model extracted "Chennai" as destination.
- **Solution**: Added "Transshipment vs Final Destination" rule to explicitly prefer "final destination" or "to [port]" over "via [port]".

### Case 3: Revenue Ton (RT) Units
- **Email ID**: `EMAIL_024`
- **Problem**: Input was "2.4 RT". Model returned null weight/cbm or raw string.
- **Solution**: Added "Revenue Ton Handling" rule: extract CBM = RT value, Weight = RT * 1000.

## 5. System Design Questions

### 1. Scaling to 10,000 emails/day
**Architecture**: 
I would implement an asynchronous queue-based architecture. Emails would be ingested into a message queue (e.g., AWS SQS, RabbitMQ). A pool of worker services (Kubernetes pods or AWS Lambda) would consume messages and call the LLM API. 

**Budget**: To stay under $500/month, we can't use GPT-4 for everything. I would use a router: 
- Use a cheaper, faster model (e.g., Llama-3-8b, GPT-3.5) for simple emails.
- Fallback to larger models (Llama-3-70b) only for low-confidence results or complex multi-shipment emails.
- Implement caching for identical email bodies (common in automated quotes).

### 2. Monitoring Accuracy Drop
**Detection**: 
Implement "Drift Monitoring" on the output distributions. If the percentage of `null` values spikes, or if the distribution of `product_line` shifts drastically (e.g., 90% became export suddenly), trigger an alert.

**Investigation**: 
1. Isolate the "drifted" emails.
2. Check for new sender templates (e.g., a major agent changed their email format).
3. Manually label a sample of the problematic emails to create a new "golden set" regular evaluation.

### 3. Multilingual Support (Mandarin/Hindi)
**Approach**:
Since modern LLMs (like Llama 3, GPT-4) have strong multilingual capabilities, the first step is to adjust the system prompt to explicitly allow processing non-English text but **enforce English/JSON output**.
**Changes**:
- Update Prompt: "You may receive emails in Mandarin or Hindi. Translate context internally and extract details in English."
- Validation: Create a test set of 20-30 non-English emails to verify if the model hallucinates or fails to detect extraction fields.
- Fallback: If direct extraction quality is low, add a dedicated translation step (Google Translate API or a small translation model) before feeding text to the extraction LLM.
