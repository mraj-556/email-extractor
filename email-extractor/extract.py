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

def create_port_mapping(port_codes_data: List[Dict]) -> tuple[Dict[str, str], Dict[str, List[str]]]:
    """
    Creates two mappings:
    1. name_to_code: Port Name -> Primary Code (for backward compatibility)
    2. name_to_all_codes: Port Name -> List of ALL codes for that name
    
    This handles cases where the same port name maps to multiple codes
    (e.g., "Chennai" -> ["INMAA", "KRPUS"])
    
    Example: For INMAA, prefer "Chennai" over "Bangalore ICD" or "Chennai ICD"
    """
    name_to_code: Dict[str, str] = {}
    name_to_all_codes: Dict[str, List[str]] = {}
    
    for item in port_codes_data:
        code = item.get("code", "").strip()
        name = item.get("name", "").strip()
        
        if not code or not name:
            continue
            
        # Split and clean in one go
        name_parts = [
            cleaned 
            for part in name.split("/")
            if (cleaned := part.strip())  # walrus operator - Python 3.8+
        ]
        
        for cleaned_name in name_parts:
            upper_name = cleaned_name.upper()
            
            # Add to all_codes list
            if upper_name not in name_to_all_codes:
                name_to_all_codes[upper_name] = []
            if code not in name_to_all_codes[upper_name]:
                name_to_all_codes[upper_name].append(code)
            
            # Keep first occurrence as primary (backward compatible)
            if upper_name not in name_to_code:
                name_to_code[upper_name] = code
            
    return name_to_code, name_to_all_codes


def get_port_code_with_country_preference(
    port_name: str, 
    name_to_all_codes: Dict[str, List[str]], 
    country_prefix: Optional[str] = None
) -> Optional[str]:
    """
    Get port code for a port name, preferring codes that match the country prefix.
    
    Args:
        port_name: The port name to look up (e.g., "Chennai")
        name_to_all_codes: Mapping of port names to all their codes
        country_prefix: Expected country code prefix (e.g., "IN" for India)
    
    Returns:
        The best matching port code, or None if not found
    
    Example:
        "Chennai" with country_prefix="IN" -> "INMAA" (not "KRPUS")
        "Chennai" with country_prefix=None -> first available code
    """
    upper_name = port_name.upper()
    codes = name_to_all_codes.get(upper_name, [])
    
    if not codes:
        return None
    
    # If only one code, return it
    if len(codes) == 1:
        return codes[0]
    
    # Multiple codes exist - filter by country prefix if provided
    if country_prefix:
        matching_codes = [c for c in codes if c.startswith(country_prefix.upper())]
        if matching_codes:
            logger.info(f"Multiple codes for '{port_name}': {codes}. Selected '{matching_codes[0]}' (matches {country_prefix} prefix)")
            return matching_codes[0]
    
    # No country preference or no match - return first code
    logger.info(f"Multiple codes for '{port_name}': {codes}. Using first: '{codes[0]}'")
    return codes[0]

def post_process_result(
    result: ExtractionResult, 
    name_to_all_codes: Dict[str, List[str]]
) -> ExtractionResult:
    """
    Apply business rules and normalization.
    Look up port codes from port names using country-aware selection.
    
    Business Logic:
    - For imports (destination=India): destination should have IN prefix
    - For exports (origin=India): origin should have IN prefix
    - Uses product_line to determine direction
    """
    
    # Determine country context based on product_line
    is_import_to_india = result.product_line == "pl_sea_import_lcl"
    is_export_from_india = result.product_line == "pl_sea_export_lcl"
    
    # Look up Origin Port Code from Name
    if result.origin_port_name:
        # For exports from India, prefer IN prefix for origin
        origin_country_prefix = "IN" if is_export_from_india else None
        logging.info(f"Looking up origin code for: {result.origin_port_name} (country_preference: {origin_country_prefix})")
        
        result.origin_port_code = get_port_code_with_country_preference(
            result.origin_port_name, 
            name_to_all_codes, 
            country_prefix=origin_country_prefix
        )
    else:
        result.origin_port_code = None

    # Look up Destination Port Code from Name  
    if result.destination_port_name:
        # For imports to India, prefer IN prefix for destination
        dest_country_prefix = "IN" if is_import_to_india else None
        logging.info(f"Looking up destination code for: {result.destination_port_name} (country_preference: {dest_country_prefix})")
        
        result.destination_port_code = get_port_code_with_country_preference(
            result.destination_port_name, 
            name_to_all_codes, 
            country_prefix=dest_country_prefix
        )
    else:
        result.destination_port_code = None

    return result

def process_email(
    client: Groq, 
    email_data: Dict, 
    name_to_all_codes: Dict[str, List[str]]
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
            final_result = post_process_result(result, name_to_all_codes)
            
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
    
    name_to_code, name_to_all_codes = create_port_mapping(port_codes)
    logger.info(f"Loaded {len(emails)} emails and {len(name_to_all_codes)} unique port names.")

    results = []
    
    logger.info("Starting Extraction...")
    for i, email in enumerate(tqdm(emails, desc="Processing Emails")):
        result = process_email(client, email, name_to_all_codes)
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
        break
        
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
