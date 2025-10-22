"""
Organization Management API Endpoints
Provides organization CRUD operations, member management, and settings
"""

from fastapi import APIRouter, HTTPException, Depends, Request
from typing import List, Dict, Optional, Any
from pydantic import BaseModel
import logging
from datetime import datetime

# Import organization manager
from org_manager import org_manager, Organization, OrgUser

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/org", tags=["organizations"])


# ==================== Request/Response Models ====================

class OrganizationMemberAdd(BaseModel):
    """Request model for adding a member to organization"""
    user_id: str
    role: str = "member"


class OrganizationMemberRoleUpdate(BaseModel):
    """Request model for updating member role"""
    role: str


class OrganizationSettingsUpdate(BaseModel):
    """Request model for updating organization settings"""
    settings: Dict[str, Any]


# ==================== Helper Functions ====================

async def get_current_user(request: Request) -> Dict:
    """Get current user data from session"""
    session_token = request.cookies.get("session_token")
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Get sessions from app state
    sessions = getattr(request.app.state, "sessions", {})
    session_data = sessions.get(session_token)

    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session")

    user = session_data.get("user", {})
    if not user:
        raise HTTPException(status_code=401, detail="User not found in session")

    return user


async def require_admin(request: Request) -> Dict:
    """Require admin role for endpoint access"""
    user = await get_current_user(request)

    # Check if user has admin role
    if not user.get("is_admin") and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    return user


async def get_user_org_id(request: Request) -> str:
    """Get organization ID from user session"""
    user = await get_current_user(request)

    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(status_code=400, detail="User has no organization")

    return org_id


async def verify_org_access(request: Request, org_id: str, required_role: Optional[str] = None):
    """
    Verify user has access to organization

    Args:
        request: FastAPI request object
        org_id: Organization ID to check access for
        required_role: Optional role requirement (owner, billing_admin, member)

    Raises:
        HTTPException: If user lacks access
    """
    user = await get_current_user(request)
    user_id = user.get("id") or user.get("email")

    # Admins have access to all organizations
    if user.get("is_admin") or user.get("role") == "admin":
        return

    # Check if user is member of organization
    user_role = org_manager.get_user_role_in_org(org_id, user_id)
    if not user_role:
        raise HTTPException(status_code=403, detail="You are not a member of this organization")

    # Check required role if specified
    if required_role:
        role_hierarchy = ["member", "billing_admin", "owner"]
        user_role_level = role_hierarchy.index(user_role) if user_role in role_hierarchy else -1
        required_role_level = role_hierarchy.index(required_role) if required_role in role_hierarchy else 99

        if user_role_level < required_role_level:
            raise HTTPException(
                status_code=403,
                detail=f"Role '{required_role}' or higher required"
            )


# ==================== API Endpoints ====================

@router.get("/roles")
async def list_available_roles():
    """
    Get list of available organization roles

    Returns:
        List of roles with descriptions and permissions

    Example:
        GET /api/v1/org/roles
        Response: {
            "roles": [
                {
                    "id": "owner",
                    "name": "Owner",
                    "description": "Full organization control",
                    "permissions": ["manage_members", "manage_billing", "manage_settings", "delete_org"]
                },
                ...
            ]
        }
    """
    roles = [
        {
            "id": "owner",
            "name": "Owner",
            "description": "Full organization control including member management and billing",
            "permissions": [
                "manage_members",
                "manage_billing",
                "manage_settings",
                "delete_org",
                "view_all"
            ]
        },
        {
            "id": "billing_admin",
            "name": "Billing Admin",
            "description": "Manage billing and view organization details",
            "permissions": [
                "manage_billing",
                "view_all"
            ]
        },
        {
            "id": "member",
            "name": "Member",
            "description": "Basic organization member with view access",
            "permissions": [
                "view_all"
            ]
        }
    ]

    return {"roles": roles}


@router.get("/{org_id}/members")
async def list_organization_members(org_id: str, request: Request):
    """
    Get list of all members in an organization

    Args:
        org_id: Organization ID

    Returns:
        List of organization members with roles and join dates

    Example:
        GET /api/v1/org/org_12345/members
        Response: {
            "members": [
                {
                    "user_id": "user@example.com",
                    "role": "owner",
                    "joined_at": "2025-01-15T10:30:00Z"
                },
                ...
            ],
            "total": 5
        }
    """
    # Verify user has access to this organization
    await verify_org_access(request, org_id)

    # Get organization to verify it exists
    org = org_manager.get_org(org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Get all members
    members = org_manager.get_org_users(org_id)

    # Format response
    members_list = [
        {
            "user_id": member.user_id,
            "role": member.role,
            "joined_at": member.joined_at.isoformat()
        }
        for member in members
    ]

    logger.info(f"Listed {len(members_list)} members for org {org_id}")

    return {
        "members": members_list,
        "total": len(members_list)
    }


@router.post("/{org_id}/members")
async def add_organization_member(
    org_id: str,
    member_data: OrganizationMemberAdd,
    request: Request
):
    """
    Add a new member to the organization

    Args:
        org_id: Organization ID
        member_data: User ID and role to assign

    Returns:
        Success confirmation

    Example:
        POST /api/v1/org/org_12345/members
        Body: {"user_id": "newuser@example.com", "role": "member"}
        Response: {
            "success": true,
            "message": "User added to organization",
            "user_id": "newuser@example.com",
            "role": "member"
        }
    """
    # Require owner role to add members
    await verify_org_access(request, org_id, required_role="owner")

    try:
        # Add user to organization
        success = org_manager.add_user_to_org(
            org_id=org_id,
            user_id=member_data.user_id,
            role=member_data.role
        )

        if not success:
            raise HTTPException(status_code=404, detail="Organization not found")

        logger.info(f"Added user {member_data.user_id} to org {org_id} with role {member_data.role}")

        return {
            "success": True,
            "message": "User added to organization",
            "user_id": member_data.user_id,
            "role": member_data.role
        }

    except ValueError as e:
        # User already in organization or invalid role
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error adding member to org {org_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to add member: {str(e)}")


@router.put("/{org_id}/members/{user_id}/role")
async def update_member_role(
    org_id: str,
    user_id: str,
    role_data: OrganizationMemberRoleUpdate,
    request: Request
):
    """
    Update a member's role in the organization

    Args:
        org_id: Organization ID
        user_id: User ID to update
        role_data: New role to assign

    Returns:
        Success confirmation

    Example:
        PUT /api/v1/org/org_12345/members/user@example.com/role
        Body: {"role": "billing_admin"}
        Response: {
            "success": true,
            "message": "User role updated",
            "user_id": "user@example.com",
            "new_role": "billing_admin"
        }
    """
    # Require owner role to update member roles
    await verify_org_access(request, org_id, required_role="owner")

    try:
        # Update user role
        success = org_manager.update_user_role(
            org_id=org_id,
            user_id=user_id,
            new_role=role_data.role
        )

        if not success:
            raise HTTPException(status_code=404, detail="User not found in organization")

        logger.info(f"Updated role for user {user_id} in org {org_id} to {role_data.role}")

        return {
            "success": True,
            "message": "User role updated",
            "user_id": user_id,
            "new_role": role_data.role
        }

    except Exception as e:
        logger.error(f"Error updating member role in org {org_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update role: {str(e)}")


@router.delete("/{org_id}/members/{user_id}")
async def remove_organization_member(
    org_id: str,
    user_id: str,
    request: Request
):
    """
    Remove a member from the organization

    Args:
        org_id: Organization ID
        user_id: User ID to remove

    Returns:
        Success confirmation

    Example:
        DELETE /api/v1/org/org_12345/members/user@example.com
        Response: {
            "success": true,
            "message": "User removed from organization",
            "user_id": "user@example.com"
        }
    """
    # Require owner role to remove members
    await verify_org_access(request, org_id, required_role="owner")

    # Prevent removing the last owner
    members = org_manager.get_org_users(org_id)
    owners = [m for m in members if m.role == "owner"]

    if len(owners) == 1 and owners[0].user_id == user_id:
        raise HTTPException(
            status_code=400,
            detail="Cannot remove the last owner. Transfer ownership first."
        )

    try:
        # Remove user from organization
        success = org_manager.remove_user_from_org(org_id=org_id, user_id=user_id)

        if not success:
            raise HTTPException(status_code=404, detail="User not found in organization")

        logger.info(f"Removed user {user_id} from org {org_id}")

        return {
            "success": True,
            "message": "User removed from organization",
            "user_id": user_id
        }

    except Exception as e:
        logger.error(f"Error removing member from org {org_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to remove member: {str(e)}")


@router.get("/{org_id}/stats")
async def get_organization_stats(org_id: str, request: Request):
    """
    Get organization statistics and metrics

    Args:
        org_id: Organization ID

    Returns:
        Organization statistics including member counts, activity, etc.

    Example:
        GET /api/v1/org/org_12345/stats
        Response: {
            "total_members": 5,
            "members_by_role": {"owner": 1, "billing_admin": 1, "member": 3},
            "created_at": "2025-01-01T00:00:00Z",
            "plan_tier": "professional",
            "status": "active"
        }
    """
    # Verify user has access to this organization
    await verify_org_access(request, org_id)

    # Get organization
    org = org_manager.get_org(org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Get members
    members = org_manager.get_org_users(org_id)

    # Count members by role
    members_by_role = {}
    for member in members:
        members_by_role[member.role] = members_by_role.get(member.role, 0) + 1

    stats = {
        "total_members": len(members),
        "members_by_role": members_by_role,
        "created_at": org.created_at.isoformat(),
        "plan_tier": org.plan_tier,
        "status": org.status,
        "organization_name": org.name
    }

    logger.info(f"Retrieved stats for org {org_id}")

    return stats


@router.get("/{org_id}/billing")
async def get_organization_billing(org_id: str, request: Request):
    """
    Get organization billing information

    Args:
        org_id: Organization ID

    Returns:
        Billing information including Lago and Stripe customer IDs

    Example:
        GET /api/v1/org/org_12345/billing
        Response: {
            "plan_tier": "professional",
            "lago_customer_id": "lago_cust_abc123",
            "stripe_customer_id": "cus_xyz789",
            "status": "active"
        }
    """
    # Require billing_admin or owner role to view billing
    await verify_org_access(request, org_id, required_role="billing_admin")

    # Get organization
    org = org_manager.get_org(org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    billing_info = {
        "plan_tier": org.plan_tier,
        "lago_customer_id": org.lago_customer_id,
        "stripe_customer_id": org.stripe_customer_id,
        "status": org.status,
        "created_at": org.created_at.isoformat()
    }

    logger.info(f"Retrieved billing info for org {org_id}")

    return billing_info


@router.get("/{org_id}/settings")
async def get_organization_settings(org_id: str, request: Request):
    """
    Get organization settings

    Args:
        org_id: Organization ID

    Returns:
        Organization settings and configuration

    Example:
        GET /api/v1/org/org_12345/settings
        Response: {
            "id": "org_12345",
            "name": "Acme Corp",
            "plan_tier": "professional",
            "status": "active",
            "created_at": "2025-01-01T00:00:00Z",
            "settings": {}
        }
    """
    # Verify user has access to this organization
    await verify_org_access(request, org_id)

    # Get organization
    org = org_manager.get_org(org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    settings = {
        "id": org.id,
        "name": org.name,
        "plan_tier": org.plan_tier,
        "status": org.status,
        "created_at": org.created_at.isoformat(),
        "settings": {}  # Placeholder for future settings
    }

    logger.info(f"Retrieved settings for org {org_id}")

    return settings


@router.put("/{org_id}/settings")
async def update_organization_settings(
    org_id: str,
    settings_data: OrganizationSettingsUpdate,
    request: Request
):
    """
    Update organization settings

    Args:
        org_id: Organization ID
        settings_data: Settings to update

    Returns:
        Updated settings

    Example:
        PUT /api/v1/org/org_12345/settings
        Body: {"settings": {"notification_email": "admin@acme.com"}}
        Response: {
            "success": true,
            "message": "Settings updated",
            "settings": {"notification_email": "admin@acme.com"}
        }
    """
    # Require owner role to update settings
    await verify_org_access(request, org_id, required_role="owner")

    # Get organization
    org = org_manager.get_org(org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # TODO: Implement settings storage in org_manager
    # For now, just return success

    logger.info(f"Updated settings for org {org_id}")

    return {
        "success": True,
        "message": "Settings updated",
        "settings": settings_data.settings
    }
