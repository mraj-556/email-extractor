# Prompt Evolution Log

This document tracks the evolution of prompts used in the email extraction system with specific examples and accuracy metrics.

---

## v1: Basic Extraction
**Version:** 1.0  
**Date:** 2026-02-04  
**Accuracy:** ~62%

### Prompt Summary
Basic extraction prompt without explicit business rules or port code handling.

### Issues Found
- Port codes extracted as names instead of UN/LOCODE format
- Missing incoterms not defaulting to FOB
- India detection logic not reliable

### Specific Examples
| Email ID | Issue | Expected | Extracted |
|----------|-------|----------|-----------|
| EMAIL_007 | Port code format wrong | `INMAA` | `Chennai` |
| EMAIL_012 | Missing incoterm handling | `FOB` (default) | `null` |

---

## v2: Added UN/LOCODE Examples
**Version:** 2.0  
**Date:** 2026-02-04  
**Accuracy:** ~78%

### Changes Made
- Added explicit UN/LOCODE format examples in prompt
- Included port reference guidance
- Added incoterm default rule

### Issues Found
- India detection failing for some ports (ICD ports)
- Product line determination inconsistent

### Specific Examples
| Email ID | Issue | Expected | Extracted |
|----------|-------|----------|-----------|
| EMAIL_023 | India detection for Nhava Sheva | `pl_sea_import_lcl` | `pl_sea_export_lcl` |
| EMAIL_031 | ICD port not recognized | `INBLR` | `null` |

---

## v3: Explicit Business Rules (Current)
**Version:** 3.0  
**Date:** 2026-02-04  
**Accuracy:** ~88%+

### Changes Made
- Explicit India detection rule (ports starting with `IN`)
- Added all valid incoterms list
- Dangerous goods detection keywords
- Body vs Subject conflict resolution
- Unit conversion rules (lbs → kg, tonnes → kg)

### Remaining Issues
- Edge cases with multiple ports mentioned in same email
- Transshipment port confusion

### Specific Examples
| Email ID | Issue | Solution Applied |
|----------|-------|------------------|
| EMAIL_045 | Multiple ports, transshipment mentioned | Extract origin→destination pair only |
| EMAIL_048 | Weight in lbs | Convert using lbs × 0.453592 |

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
