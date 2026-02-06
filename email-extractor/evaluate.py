import json
import logging
import sys
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from pathlib import Path
from typing import List, Dict, Any

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s', # Simple format for metrics
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Constants
DATA_DIR = Path("/data") if Path("/data").exists() else Path("..")
GROUND_TRUTH_FILE = Path(os.getenv("GROUND_TRUTH_FILE", str(DATA_DIR / "ground_truth.json")))
OUTPUT_FILE = Path(os.getenv("OUTPUT_FILE", str(DATA_DIR / "output.json")))

FIELDS_TO_EVALUATE = [
    "product_line",
    "origin_port_code",
    "origin_port_name",
    "destination_port_code",
    "destination_port_name",
    "incoterm",
    "cargo_weight_kg",
    "cargo_cbm",
    "is_dangerous"
]

def normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, float):
        return round(value, 2)
    return value

def compare_values(pred: Any, truth: Any) -> bool:
    norm_pred = normalize_value(pred)
    norm_truth = normalize_value(truth)
    
    # Null handling
    if norm_pred is None and norm_truth is None:
        return True
    if norm_pred is None or norm_truth is None:
        return False
        
    return norm_pred == norm_truth

def evaluate(ground_truth: List[Dict], predictions: List[Dict]):
    gt_map = {item["id"]: item for item in ground_truth}
    pred_map = {item["id"]: item for item in predictions}

    correct_counts = {field: 0 for field in FIELDS_TO_EVALUATE}
    total_counts = {field: 0 for field in FIELDS_TO_EVALUATE}
    
    total_fields_evaluated = 0
    total_fields_correct = 0

    for email_id, gt_data in gt_map.items():
        if email_id not in pred_map:
            logger.warning(f"Missing prediction for {email_id}")
            continue
            
        pred_data = pred_map[email_id]
        
        for field in FIELDS_TO_EVALUATE:
            gt_val = gt_data.get(field)
            pred_val = pred_data.get(field)
            
            is_correct = compare_values(pred_val, gt_val)
            
            if is_correct:
                correct_counts[field] += 1
                total_fields_correct += 1
            else:
                 # Optional: Log mismatches for debugging
                 # logger.debug(f"Mismatch {email_id} {field}: Pred={pred_val}, Truth={gt_val}")
                 pass
            
            total_counts[field] += 1
            total_fields_evaluated += 1

    logger.info("------ Evaluation Metrics ------")
    for field in FIELDS_TO_EVALUATE:
        correct = correct_counts[field]
        total = total_counts[field]
        if total > 0:
            accuracy = (correct / total) * 100
        else:
            accuracy = 0.0
        logger.info(f"{field}: {accuracy:.2f}% ({correct}/{total})")
    
    if total_fields_evaluated > 0:
        overall_accuracy = (total_fields_correct / total_fields_evaluated) * 100
    else:
        overall_accuracy = 0.0
        
    logger.info("--------------------------------")
    logger.info(f"OVERALL ACCURACY: {overall_accuracy:.2f}%")
    logger.info("--------------------------------")

def main():
    if not OUTPUT_FILE.exists():
        logger.error(f"Output file not found: {OUTPUT_FILE}")
        sys.exit(1)
        
    with open(GROUND_TRUTH_FILE, 'r') as f:
        ground_truth = json.load(f)
        
    with open(OUTPUT_FILE, 'r') as f:
        predictions = json.load(f)
        
    evaluate(ground_truth, predictions)

if __name__ == "__main__":
    main()
