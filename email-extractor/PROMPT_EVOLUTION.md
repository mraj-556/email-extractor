# Prompt Evolution Log

This document tracks the evolution of prompts used in the email extraction system with specific examples and accuracy metrics.

---

## v1: Basic Extraction
**Version:** 1.0  
**Date:** 2026-02-04  
**Accuracy:** ~88%

### Prompt Summary
Basic extraction prompt without explicit business rules or port code handling.

### Issues Found
- Port codes extracted as names instead of UN/LOCODE format
- Missing incoterms not defaulting to FOB
- India detection logic not working

---

## v2: Added UN/LOCODE Examples
**Version:** 2.0  
**Date:** 2026-02-04  
**Accuracy:** 88.89%

### Changes Made
- Added explicit UN/LOCODE format examples in prompt
- Included port reference guidance
- Added incoterm default rule

### Issues Found
- India detection failing for some ports (ICD ports)
- Detect proper Port names and codes


---

## v3: Explicit Business Rules (Current)
**Version:** 3.0  
**Date:** 2026-02-04  
**Accuracy:** 94%

### Changes Made
- Explicit India detection rule (ports starting with `IN`)
- Added all valid incoterms list
- Dangerous goods detection keywords
- Body vs Subject conflict resolution
- Unit conversion rules (lbs → kg, tonnes → kg)
- Added some sample input and output

### Remaining Issues
- Edge cases with multiple ports mentioned in same email
- Transshipment port confusion

---

## v4: RT Handling, Code-to-Name, Post-Processing (Current)
**Version:** 4.0  
**Date:** 2026-02-06  
**Accuracy:** 97.78

### Changes Made

#### Prompt Improvements
- **RT (Revenue Ton) Handling**: `X RT` → `cargo_cbm = X`, `cargo_weight_kg = X * 1000`
- **Port Code to Name Conversion**: LLM instructed to convert PUS→Busan, MAA→Chennai, etc.
- **Multi-DG First Item Rule**: Extract ONLY first DG item's weight/CBM
- **Incoterm CIF Detection**: Better handling of "CIF [port]" pattern
- **Port Name Format**: Use " / " (space-slash-space) for multi-port names
- **Clean Port Names**: Don't append city suffixes (Ambarli, not Ambarli, Istanbul)
- **Title Case**: Use proper Title Case (Shanghai, not SHANGHAI)

#### Post-Processing (`extract.py`) Improvements
- `normalize_port_name_display()`: Title Case, slash spacing, city suffix removal
- `PORT_CODE_TO_NAME`: Fallback mapping for common 3-letter codes

### Target Fixes
| Email ID | Issue | Fix Applied |
|----------|-------|-------------|
| EMAIL_021 | SHANGHAI → Shanghai | Title Case normalization |
| EMAIL_022 | Summed weight/CBM → First item only | Multi-DG rule |
| EMAIL_024 | RT not converted to weight/CBM | RT handling rule |
| EMAIL_025 | Missing origin from subject | Subject fallback rule |
| EMAIL_026 | Xingang/Tianjin spacing | Slash normalization |
| EMAIL_027 | "Ambarli, Istanbul" | City suffix removal |
| EMAIL_034, 035 | RT not converted | RT handling rule |
| EMAIL_038 | Tianjin/Xingang spacing | Slash normalization |
| EMAIL_039 | PUS/MAA as names | Code-to-name conversion |

### Ground Truth Errors Found
- EMAIL_018: destination_port_code should be INMAA, not KRPUS
- EMAIL_028: destination_port_code should be INBLR, not INMAA
- EMAIL_032: cargo_weight_kg should be null (no weight in email)
- EMAIL_050: destination_port_name "Chennai" is valid per body-priority rule

---

## Version Comparison Summary

| Version | Accuracy | Key Improvement |
|---------|----------|-----------------|
| v1 | 88% | Baseline |
| v2 | 88.89% | UN/LOCODE format |
| v3 | 94%+ | Business rules + conflict resolution |
| v4 | 97.78 | RT conversion + code-to-name + post-processing |

---
