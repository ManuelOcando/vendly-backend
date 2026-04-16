"""
Legal terms and privacy policy endpoints
Handles user acceptance of terms during registration
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from db.supabase import get_supabase_client
from api.deps import get_current_user

router = APIRouter(prefix="/legal")


class TermsAcceptance(BaseModel):
    accepted_privacy_policy: bool
    accepted_terms_of_service: bool
    privacy_policy_version: str
    terms_version: str
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


class TermsStatusResponse(BaseModel):
    accepted_privacy_policy: bool
    accepted_terms_of_service: bool
    privacy_policy_version: str
    terms_version: str
    accepted_at: Optional[datetime] = None


# Current versions - update these when terms change
CURRENT_PRIVACY_VERSION = "1.0"
CURRENT_TERMS_VERSION = "1.0"


@router.get("/current-versions")
async def get_current_versions():
    """Get current versions of legal documents"""
    return {
        "privacy_policy": {
            "version": CURRENT_PRIVACY_VERSION,
            "url": "/privacy-policy",
            "last_updated": "2026-04-16"
        },
        "terms_of_service": {
            "version": CURRENT_TERMS_VERSION,
            "url": "/terms-of-service",
            "last_updated": "2026-04-16"
        }
    }


@router.post("/accept", response_model=dict)
async def accept_terms(
    acceptance: TermsAcceptance,
    current_user: dict = Depends(get_current_user)
):
    """
    Record user's acceptance of terms and privacy policy.
    Required before completing registration.
    """
    if not acceptance.accepted_privacy_policy or not acceptance.accepted_terms_of_service:
        raise HTTPException(
            status_code=400,
            detail="Debes aceptar tanto la Política de Privacidad como los Términos de Servicio"
        )
    
    db = get_supabase_client()
    
    # Check if user already has a record
    existing = db.table("user_legal_acceptance").select("*").eq(
        "user_id", current_user["id"]
    ).execute()
    
    acceptance_data = {
        "user_id": current_user["id"],
        "accepted_privacy_policy": acceptance.accepted_privacy_policy,
        "accepted_terms_of_service": acceptance.accepted_terms_of_service,
        "privacy_policy_version": acceptance.privacy_policy_version or CURRENT_PRIVACY_VERSION,
        "terms_version": acceptance.terms_version or CURRENT_TERMS_VERSION,
        "ip_address": acceptance.ip_address,
        "user_agent": acceptance.user_agent,
        "accepted_at": datetime.utcnow().isoformat()
    }
    
    if existing.data:
        # Update existing record
        result = db.table("user_legal_acceptance").update(acceptance_data).eq(
            "user_id", current_user["id"]
        ).execute()
    else:
        # Create new record
        result = db.table("user_legal_acceptance").insert(acceptance_data).execute()
    
    return {
        "success": True,
        "message": "Términos aceptados correctamente",
        "accepted_at": acceptance_data["accepted_at"]
    }


@router.get("/status/{user_id}", response_model=TermsStatusResponse)
async def get_terms_status(
    user_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get terms acceptance status for a user"""
    # Users can only check their own status unless admin
    if current_user["id"] != user_id and not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="No autorizado")
    
    db = get_supabase_client()
    
    result = db.table("user_legal_acceptance").select("*").eq(
        "user_id", user_id
    ).execute()
    
    if not result.data:
        return TermsStatusResponse(
            accepted_privacy_policy=False,
            accepted_terms_of_service=False,
            privacy_policy_version="",
            terms_version=""
        )
    
    record = result.data[0]
    return TermsStatusResponse(
        accepted_privacy_policy=record.get("accepted_privacy_policy", False),
        accepted_terms_of_service=record.get("accepted_terms_of_service", False),
        privacy_policy_version=record.get("privacy_policy_version", ""),
        terms_version=record.get("terms_version", ""),
        accepted_at=record.get("accepted_at")
    )


@router.get("/my-status", response_model=TermsStatusResponse)
async def get_my_terms_status(current_user: dict = Depends(get_current_user)):
    """Get current user's terms acceptance status"""
    db = get_supabase_client()
    
    result = db.table("user_legal_acceptance").select("*").eq(
        "user_id", current_user["id"]
    ).execute()
    
    if not result.data:
        return TermsStatusResponse(
            accepted_privacy_policy=False,
            accepted_terms_of_service=False,
            privacy_policy_version="",
            terms_version=""
        )
    
    record = result.data[0]
    
    # Check if terms have been updated since user accepted
    privacy_outdated = record.get("privacy_policy_version") != CURRENT_PRIVACY_VERSION
    terms_outdated = record.get("terms_version") != CURRENT_TERMS_VERSION
    
    return {
        "accepted_privacy_policy": record.get("accepted_privacy_policy", False),
        "accepted_terms_of_service": record.get("accepted_terms_of_service", False),
        "privacy_policy_version": record.get("privacy_policy_version", ""),
        "terms_version": record.get("terms_version", ""),
        "accepted_at": record.get("accepted_at"),
        "privacy_outdated": privacy_outdated,
        "terms_outdated": terms_outdated,
        "requires_reacceptance": privacy_outdated or terms_outdated
    }


@router.get("/required", response_model=dict)
async def check_terms_required():
    """Check if terms acceptance is required for registration"""
    return {
        "required": True,
        "privacy_policy_url": "/privacy-policy",
        "terms_url": "/terms-of-service",
        "privacy_version": CURRENT_PRIVACY_VERSION,
        "terms_version": CURRENT_TERMS_VERSION
    }
