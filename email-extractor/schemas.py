from typing import Optional
from pydantic import BaseModel, Field, field_validator
from enum import Enum

class ProductLine(str, Enum):
    IMPORT_LCL = "pl_sea_import_lcl"
    EXPORT_LCL = "pl_sea_export_lcl"

class Incoterm(str, Enum):
    FOB = "FOB"
    CIF = "CIF"
    CFR = "CFR"
    EXW = "EXW"
    DDP = "DDP"
    DAP = "DAP"
    FCA = "FCA"
    CPT = "CPT"
    CIP = "CIP"
    DPU = "DPU"

class ExtractionResult(BaseModel):
    id: str
    product_line: Optional[ProductLine] = None
    origin_port_code: Optional[str] = None
    origin_port_name: Optional[str] = None
    destination_port_code: Optional[str] = None
    destination_port_name: Optional[str] = None
    incoterm: Optional[Incoterm] = None
    cargo_weight_kg: Optional[float] = None
    cargo_cbm: Optional[float] = None
    is_dangerous: bool = False

    @field_validator('incoterm', mode='before')
    def normalize_incoterm(cls, v):
        if v:
            return v.upper()
        return v
