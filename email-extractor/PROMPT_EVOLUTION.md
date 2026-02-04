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
**Accuracy:** 100%

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

## Version Comparison Summary

| Version | Accuracy | Key Improvement |
|---------|----------|-----------------|
| v1 | 62% | Baseline |
| v2 | 78% | UN/LOCODE format |
| v3 | 88%+ | Business rules + conflict resolution |

---

## How to Add New Versions

1. Update `prompts.py` with a new version in `PROMPT_VERSIONS` dict
2. Set `CURRENT_VERSION` to the new version number
3. Document changes in this file following the format above
4. Run extraction and evaluate accuracy
5. Record specific email IDs that improved/regressed
