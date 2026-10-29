"""Data contracts and validation models for the Export Classification Check Service."""

from __future__ import annotations

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, model_validator


class MaterialEnum(str, Enum):
    STAINLESS_STEEL = "stainless_steel"
    STEEL = "steel"
    IRON = "iron"
    PLASTIC = "plastic"
    GLASS = "glass"
    RUBBER = "rubber"
    WOOD = "wood"
    CERAMIC = "ceramic"
    COPPER = "copper"
    ALUMINIUM = "aluminium"
    BRASS = "brass"
    COMPOSITE = "composite"
    LITHIUM = "lithium"
    OTHER = "other"


class RunRequest(BaseModel):
    description: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Detailed product description (10-500 chars).",
        examples=["Stainless steel vacuum flask with a moulded plastic outer body."],
    )
    materials: List[MaterialEnum] = Field(
        ...,
        min_length=1,
        description="List of materials comprising the product (at least one required).",
        examples=[[MaterialEnum.STAINLESS_STEEL, MaterialEnum.PLASTIC]],
    )
    intended_use: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional intended use of the product.",
        examples=["Beverage thermal insulation for household/travel use"],
    )

    @model_validator(mode="after")
    def check_cross_field_consistency(self) -> RunRequest:
        desc_lower = self.description.lower()
        mat_values = {m.value.lower() for m in self.materials}

        # Check cross-field requirement: If description mentions a material word,
        # it must be declared in the materials list.
        material_keywords = {
            "steel": ["steel", "stainless_steel"],
            "iron": ["iron", "steel"],
            "plastic": ["plastic"],
            "glass": ["glass"],
            "rubber": ["rubber"],
            "wood": ["wood"],
            "aluminium": ["aluminium"],
            "copper": ["copper"],
        }

        for word, allowed_enums in material_keywords.items():
            if word in desc_lower:
                if not any(ae in mat_values for ae in allowed_enums):
                    raise ValueError(
                        f"Description mentions '{word}', but materials list does not include a corresponding material enum ({allowed_enums})."
                    )

        return self


class RunSubmitResponse(BaseModel):
    run_id: str
    status: str = "queued"
    message: str = "Request accepted and enqueued for classification."


class RunStatusResponse(BaseModel):
    run_id: str
    correlation_id: str
    status: str  # queued | running | done | failed
    route: Optional[str] = None  # clear-for-filing | seek-product-clarification | specialist-classification-review
    basis: Optional[str] = None
    resolved_heading: Optional[str] = None
    resolved_heading_title: Optional[str] = None
    tariff_code: Optional[str] = None
    gri_rule: Optional[str] = None
    export_policy: Optional[str] = None
    citations: List[str] = Field(default_factory=list)
    prompt_version: str = "classifier_v1"
    disclaimer: str = (
        "PROPOSAL ONLY: This service never files a declaration. A licensed customs broker must make the final determination."
    )
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
