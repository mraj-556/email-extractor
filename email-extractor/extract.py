import os
import json
import logging
import time
import sys
from typing import List, Dict, Optional
from pathlib import Path

from groq import Groq, RateLimitError, APITimeoutError, APIError
from dotenv import load_dotenv
from tqdm import tqdm
from pydantic import ValidationError

from schemas import ExtractionResult, ProductLine, Incoterm
from prompts import SYSTEM_PROMPT

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Load Environment Variables
load_dotenv()

# Constants
DATA_DIR = Path("/data") if Path("/data").exists() else Path("..")
INPUT_FILE = DATA_DIR / "emails_input.json"
PORT_CODES_FILE = DATA_DIR / "port_codes_reference.json"
OUTPUT_FILE = DATA_DIR / "output.json"

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MODEL_NAME = "llama-3.3-70b-versatile"
TEMPERATURE = 0.0

def load_json(path: Path):
    if not path.exists():
        logger.error(f"File not found: {path}")
        sys.exit(1)
    with open(path, 'r') as f:
        return json.load(f)

def create_port_mapping(port_codes_data: List[Dict]) -> Dict[str, str]:
    """
    Creates a mapping from Port Code to Canonical Port Name.
    Handles duplicates? The Reference file says: 
    "Some ports have multiple name entries mapping to the same code"
    We should probably create a mapping of Code -> Name. 
    If multiple names exist, maybe take the first one or a specific one? 
    The README says: "Always use the canonical name from port_codes_reference.json for the matched code"
    Let's assume the first entry for a code in the list is the canonical one, or just map all code occurrences.
    """
    mapping = {}
    for entry in port_codes_data:
        code = entry.get("code")
        name = entry.get("name")
        if code and name:
            # If code already exists, do we overwrite? 
            # Example: INMAA -> Chennai, INMAA -> Chennai ICD.
            # Usually the first one is simpler, or we prefer the one that matches text.
            # But here we need a canonical name. Let's stick to the first one found or overwrite?
            # README says "regardless of how the port was named in the email".
            # Let's map code -> name.
            if code not in mapping:
                mapping[code] = name
    return mapping

def post_process_result(result: ExtractionResult, port_mapping: Dict[str, str]) -> ExtractionResult:
    """
    Apply business rules and normalization.
    1. Canonical Port Names from Reference.
    2. Null handling for Port Codes not in Reference? 
       README: "If a port isn't in the reference file, use null for the code"
       This implies if LLM hallucinates a code not in provided list, we should null it.
    """
    
    # Normalize Origin Port
    if result.origin_port_code:
        canonical_name = port_mapping.get(result.origin_port_code)
        if canonical_name:
            result.origin_port_name = canonical_name
        else:
            # Code not in reference
            result.origin_port_code = None
            result.origin_port_name = None
    else:
        result.origin_port_name = None

    # Normalize Destination Port
    if result.destination_port_code:
        canonical_name = port_mapping.get(result.destination_port_code)
        if canonical_name:
            result.destination_port_name = canonical_name
        else:
             # Code not in reference
            result.destination_port_code = None
            result.destination_port_name = None
    else:
        result.destination_port_name = None

    return result

def process_email(client: Groq, email_data: Dict, port_mapping: Dict[str, str]) -> Optional[Dict]:
    email_id = email_data.get("id")
    subject = email_data.get("subject", "")
    body = email_data.get("body", "")
    
    user_content = f"""
    Subject: {subject}
    Body: {body}
    """

    retries = 3
    base_delay = 2

    for attempt in range(retries):
        try:
            logger.debug(f"Processing {email_id} - Attempt {attempt + 1}")
            completion = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content}
                ],
                temperature=TEMPERATURE,
                response_format={"type": "json_object"}
            )
            
            response_content = completion.choices[0].message.content
            logger.info(f"Raw Response for {email_id}: {response_content}")

            parsed_data = json.loads(response_content)
            
            # Inject ID if missing (though Prompt asks to return without ID, we can add it)
            parsed_data["id"] = email_id
            
            # Validate with Pydantic
            result = ExtractionResult(**parsed_data)
            
            # Post Process
            final_result = post_process_result(result, port_mapping)
            
            return final_result.model_dump()

        except (RateLimitError, APITimeoutError) as e:
            wait_time = base_delay * (2 ** attempt)
            logger.warning(f"API Error processing {email_id}: {e}. Retrying in {wait_time}s...")
            time.sleep(wait_time)
        except ValidationError as e:
            logger.error(f"Validation Error for {email_id}: {e}")
            # If validation fails, we might want to return a null-filled object or retry?
            # README says: "include it in output.json with null for all extracted fields".
            return None
        except json.JSONDecodeError as e:
             logger.error(f"JSON Parse Error for {email_id}: {e}")
             return None
        except Exception as e:
            logger.error(f"Unexpected Error processing {email_id}: {e}")
            return None
    
    logger.error(f"Failed to process {email_id} after {retries} retries.")
    return None

def main():
    logging.info(f"Groq API key : {GROQ_API_KEY}")
    if not GROQ_API_KEY:
        logger.error("GROQ_API_KEY not found in environment variables.")
        sys.exit(1)

    client = Groq(api_key=GROQ_API_KEY)

    logger.info("Loading Data...")
    emails = load_json(INPUT_FILE)
    port_codes = load_json(PORT_CODES_FILE)
    
    port_mapping = create_port_mapping(port_codes)
    logger.info(f"Loaded {len(emails)} emails and {len(port_mapping)} port codes.")

    results = []
    
    logger.info("Starting Extraction...")
    for i, email in enumerate(tqdm(emails, desc="Processing Emails")):
        result = process_email(client, email, port_mapping)
        logging.info(f"Input email : {email} \n Output data : {result} ")
        if result:
            results.append(result)
        else:
            # Fallback for failed extraction: preserve ID, nulls elsewhere
            results.append({
                "id": email.get("id"),
                "product_line": None,
                "origin_port_code": None,
                "origin_port_name": None,
                "destination_port_code": None,
                "destination_port_name": None,
                "incoterm": None,
                "cargo_weight_kg": None,
                "cargo_cbm": None,
                "is_dangerous": False
            })
        
        # Save incrementally every 5 emails
        if (i + 1) % 5 == 0:
            with open(OUTPUT_FILE, 'w') as f:
                json.dump(results, f, indent=2)

    logger.info(f"Extraction complete. Saving final results to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(results, f, indent=2)
    logger.info("Done.")

if __name__ == "__main__":
    main()
