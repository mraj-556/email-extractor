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


# Constants
DATA_DIR = Path("/data") if Path("/data").exists() else Path("..")
INPUT_FILE = DATA_DIR / "emails_input.json"
PORT_CODES_FILE = DATA_DIR / "port_codes_reference.json"
OUTPUT_FILE = DATA_DIR / "output.json"

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MODEL_NAME = os.getenv("MODEL_NAME")
TEMPERATURE = 0.0

def load_json(path: Path):
    if not path.exists():
        logger.error(f"File not found: {path}")
        sys.exit(1)
    with open(path, 'r') as f:
        return json.load(f)

def normalize_port_name(name: str) -> str:
    """
    Normalize a port name for flexible matching.
    Splits by '/', strips whitespace, sorts alphabetically, and rejoins.
    
    Example: "Chennai ICD / Bangalore ICD / Hyderabad ICD" 
          -> "BANGALORE ICD|CHENNAI ICD|HYDERABAD ICD"
    """
    parts = [p.strip().upper() for p in name.split("/") if p.strip()]
    parts.sort()
    return "|".join(parts)


def create_port_mapping(port_codes_data: List[Dict]) -> tuple[Dict[str, str], Dict[str, str], Dict[str, List[str]], Dict[str, List[str]]]:
    """
    Creates four mappings:
    1. name_to_code: Exact name -> first code found
    2. normalized_to_code: Normalized name -> first code found  
    3. name_to_all_codes: Exact name -> list of ALL codes
    4. normalized_to_all_codes: Normalized name -> list of ALL codes
    
    The "all_codes" mappings allow country-preference filtering when multiple codes exist.
    """
    name_to_code: Dict[str, str] = {}
    normalized_to_code: Dict[str, str] = {}
    name_to_all_codes: Dict[str, List[str]] = {}
    normalized_to_all_codes: Dict[str, List[str]] = {}
    
    for item in port_codes_data:
        code = item.get("code", "").strip()
        name = item.get("name", "").strip()
        
        if not code or not name:
            continue
        
        upper_name = name.upper()
        normalized_name = normalize_port_name(name)
        
        # First occurrence as default
        if upper_name not in name_to_code:
            name_to_code[upper_name] = code
        if normalized_name not in normalized_to_code:
            normalized_to_code[normalized_name] = code
        
        # Track ALL codes for each name
        if upper_name not in name_to_all_codes:
            name_to_all_codes[upper_name] = []
        if code not in name_to_all_codes[upper_name]:
            name_to_all_codes[upper_name].append(code)
            
        if normalized_name not in normalized_to_all_codes:
            normalized_to_all_codes[normalized_name] = []
        if code not in normalized_to_all_codes[normalized_name]:
            normalized_to_all_codes[normalized_name].append(code)
            
    return name_to_code, normalized_to_code, name_to_all_codes, normalized_to_all_codes


def find_port_code(
    port_name: str, 
    name_to_all_codes: Dict[str, List[str]], 
    normalized_to_all_codes: Dict[str, List[str]],
    country_prefix: Optional[str] = None
) -> Optional[str]:
    """
    Find port code by trying exact match first, then normalized match.
    If multiple codes exist for a name, prefer codes matching the country_prefix.
    """
    upper_name = port_name.upper()
    normalized_name = normalize_port_name(port_name)
    
    # Get all matching codes (try exact first, then normalized)
    codes = name_to_all_codes.get(upper_name, [])
    if not codes:
        codes = normalized_to_all_codes.get(normalized_name, [])
        if codes:
            logger.info(f"Matched '{port_name}' via normalized lookup")
    
    if not codes:
        return None
    
    # If only one code, return it
    if len(codes) == 1:
        return codes[0]
    
    # Multiple codes exist - prefer country_prefix match
    if country_prefix:
        matching = [c for c in codes if c.startswith(country_prefix.upper())]
        if matching:
            logger.info(f"Multiple codes for '{port_name}': {codes}. Selected '{matching[0]}' (matches {country_prefix} prefix)")
            return matching[0]
    
    # No preference or no match - return first
    logger.info(f"Multiple codes for '{port_name}': {codes}. Using first: '{codes[0]}'")
    return codes[0]


def post_process_result(
    result: ExtractionResult, 
    name_to_all_codes: Dict[str, List[str]],
    normalized_to_all_codes: Dict[str, List[str]]
) -> ExtractionResult:
    """
    Apply business rules and normalization.
    Uses product_line to determine country context for port selection.
    """
    
    # Determine country context based on product_line
    is_import_to_india = result.product_line == "pl_sea_import_lcl"
    is_export_from_india = result.product_line == "pl_sea_export_lcl"
    
    # Look up Origin Port Code from Name
    if result.origin_port_name:
        # For exports FROM India, origin should be Indian port (IN prefix)
        origin_prefix = "IN" if is_export_from_india else None
        logging.info(f"Looking up origin code for: {result.origin_port_name} (prefer: {origin_prefix})")
        result.origin_port_code = find_port_code(
            result.origin_port_name, name_to_all_codes, normalized_to_all_codes, origin_prefix
        )
    else:
        result.origin_port_code = None

    # Look up Destination Port Code from Name  
    if result.destination_port_name:
        # For imports TO India, destination should be Indian port (IN prefix)
        dest_prefix = "IN" if is_import_to_india else None
        logging.info(f"Looking up destination code for: {result.destination_port_name} (prefer: {dest_prefix})")
        result.destination_port_code = find_port_code(
            result.destination_port_name, name_to_all_codes, normalized_to_all_codes, dest_prefix
        )
    else:
        result.destination_port_code = None

    return result


def process_email(
    client: Groq, 
    email_data: Dict, 
    name_to_all_codes: Dict[str, List[str]],
    normalized_to_all_codes: Dict[str, List[str]]
) -> Optional[Dict]:
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
            
            # Post Process with country-aware port code selection
            final_result = post_process_result(result, name_to_all_codes, normalized_to_all_codes)
            
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
    
    name_to_code, normalized_to_code, name_to_all_codes, normalized_to_all_codes = create_port_mapping(port_codes)
    logger.info(f"Loaded {len(emails)} emails and {len(name_to_code)} port name entries.")

    results = []
    
    logger.info("Starting Extraction...")
    for i, email in enumerate(tqdm(emails, desc="Processing Emails")):
        result = process_email(client, email, name_to_all_codes, normalized_to_all_codes)
        # logging.info(f"Input email : {email} \n Output data : {result} ")
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
        # if (i + 1) % 5 == 0:
        with open(OUTPUT_FILE, 'w') as f:
            json.dump(results, f, indent=2)

    logger.info(f"Extraction complete. Saving final results to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(results, f, indent=2)
    logger.info("Done.")

if __name__ == "__main__":
    main()
