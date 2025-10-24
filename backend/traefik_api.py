"""
Traefik Configuration Management API - Simplified for Pydantic v2 Compatibility
Epic 1.3: Traefik Configuration Management

This is a simplified version focused on core functionality.
Full comprehensive version with complex validators will be developed in future iteration.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging

from traefik_manager import (
    TraefikManager,
    TraefikError,
    CertificateError,
    RouteError,
    MiddlewareError,
    ConfigurationError
)

router = APIRouter(prefix="/api/v1/traefik", tags=["Traefik Management (Epic 1.3)"])
logger = logging.getLogger(__name__)

# Initialize Traefik manager
traefik_manager = TraefikManager()


# ==================== Simple Request Models ====================

class RouteCreate(BaseModel):
    """Simplified route creation model"""
    name: str = Field(..., description="Route name")
    rule: str = Field(..., description="Traefik rule (e.g., Host(`example.com`))")
    service: str = Field(..., description="Target service name")
    entrypoints: List[str] = Field(default=["http"], description="Entry points")
    priority: int = Field(default=100, description="Route priority")
    middlewares: List[str] = Field(default=[], description="Middleware names")


class RouteUpdate(BaseModel):
    """Route update model"""
    rule: Optional[str] = Field(None, description="Traefik rule")
    service: Optional[str] = Field(None, description="Target service name")
    priority: Optional[int] = Field(None, description="Route priority")
    middlewares: Optional[List[str]] = Field(None, description="Middleware names")


class ServiceCreate(BaseModel):
    """Simplified service creation model"""
    name: str = Field(..., description="Service name")
    url: str = Field(..., description="Backend URL (e.g., http://backend:8080)")
    healthcheck_path: Optional[str] = Field(None, description="Health check path")


class ServiceUpdate(BaseModel):
    """Service update model"""
    url: Optional[str] = Field(None, description="Backend URL")
    healthcheck_path: Optional[str] = Field(None, description="Health check path")


class MiddlewareCreate(BaseModel):
    """Simplified middleware creation model"""
    name: str = Field(..., description="Middleware name")
    type: str = Field(..., description="Middleware type (compress, ratelimit, etc.)")
    config: Dict[str, Any] = Field(default={}, description="Middleware configuration")


class MiddlewareUpdate(BaseModel):
    """Middleware update model"""
    config: Optional[Dict[str, Any]] = Field(None, description="Middleware configuration")


# ==================== Health & Status Endpoints ====================

@router.get("/health")
async def health_check():
    """Health check endpoint for Traefik management API"""
    return {
        "status": "healthy",
        "service": "traefik-management-api",
        "version": "1.0.0-simplified",
        "epic": "1.3"
    }


@router.get("/status")
async def get_traefik_status():
    """Get overall Traefik status"""
    try:
        routes = traefik_manager.list_routes()
        certificates = traefik_manager.list_certificates()

        return {
            "status": "operational",
            "routes_count": len(routes),
            "certificates_count": len(certificates),
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to get Traefik status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Route Management ====================

@router.get("/routes")
async def list_routes():
    """List all Traefik routes"""
    try:
        routes = traefik_manager.list_routes()
        return {"routes": routes, "count": len(routes)}
    except TraefikError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/routes", status_code=201)
async def create_route(route: RouteCreate):
    """Create a new Traefik route"""
    try:
        result = traefik_manager.create_route(
            name=route.name,
            rule=route.rule,
            service=route.service,
            entrypoints=route.entrypoints,
            middlewares=route.middlewares,
            priority=route.priority,
            username="api-user"
        )
        return result
    except RouteError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create route: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/routes/{route_name}")
async def get_route(route_name: str):
    """Get details of a specific route"""
    try:
        routes = traefik_manager.list_routes()
        route = next((r for r in routes if r['name'] == route_name), None)

        if not route:
            raise HTTPException(status_code=404, detail=f"Route '{route_name}' not found")

        return {"route": route}
    except RouteError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/routes/{route_name}")
async def update_route(route_name: str, updates: RouteUpdate):
    """Update an existing route"""
    try:
        # Convert Pydantic model to dict, excluding None values
        update_dict = {k: v for k, v in updates.dict().items() if v is not None}

        if not update_dict:
            raise HTTPException(status_code=400, detail="No updates provided")

        result = traefik_manager.update_route(
            name=route_name,
            updates=update_dict,
            username="api-user"
        )
        return result
    except RouteError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update route: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/routes/{route_name}")
async def delete_route(route_name: str):
    """Delete a Traefik route"""
    try:
        result = traefik_manager.delete_route(name=route_name, username="api-user")
        return result
    except RouteError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to delete route: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== SSL Certificate Management ====================

@router.get("/certificates")
async def list_certificates():
    """List all SSL certificates"""
    try:
        certificates = traefik_manager.list_certificates()
        return {"certificates": certificates, "count": len(certificates)}
    except CertificateError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/certificates/{domain}")
async def get_certificate(domain: str):
    """Get SSL certificate information for a domain"""
    try:
        cert_info = traefik_manager.get_certificate_info(domain)
        return {"certificate": cert_info}
    except CertificateError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/acme/status")
async def get_acme_status():
    """Get ACME (Let's Encrypt) status"""
    try:
        status = traefik_manager.get_acme_status()
        return {"acme_status": status}
    except TraefikError as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Service Management ====================

@router.get("/services")
async def list_services():
    """List all Traefik services"""
    try:
        services = []
        for config_path in traefik_manager.dynamic_dir.glob("*.yml"):
            try:
                import yaml
                with open(config_path, 'r') as f:
                    config = yaml.safe_load(f)

                if config and 'http' in config and 'services' in config['http']:
                    for name, service in config['http']['services'].items():
                        services.append({
                            'name': name,
                            'type': 'loadBalancer' if 'loadBalancer' in service else 'unknown',
                            'servers': service.get('loadBalancer', {}).get('servers', []),
                            'healthCheck': service.get('loadBalancer', {}).get('healthCheck', None),
                            'source_file': config_path.name
                        })
            except Exception as e:
                logger.warning(f"Failed to parse {config_path.name}: {e}")

        return {"services": services, "count": len(services)}
    except Exception as e:
        logger.error(f"Failed to list services: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/services", status_code=201)
async def create_service(service: ServiceCreate):
    """Create a new Traefik service"""
    try:
        import yaml
        services_file = traefik_manager.dynamic_dir / "services.yml"

        if services_file.exists():
            with open(services_file, 'r') as f:
                config = yaml.safe_load(f) or {}
        else:
            config = {'http': {'services': {}}}

        if 'http' not in config:
            config['http'] = {}
        if 'services' not in config['http']:
            config['http']['services'] = {}

        if service.name in config['http']['services']:
            raise HTTPException(status_code=400, detail=f"Service '{service.name}' already exists")

        # Build service configuration
        service_config = {
            'loadBalancer': {
                'servers': [{'url': service.url}]
            }
        }

        if service.healthcheck_path:
            service_config['loadBalancer']['healthCheck'] = {
                'path': service.healthcheck_path,
                'interval': '10s',
                'timeout': '3s'
            }

        config['http']['services'][service.name] = service_config

        # Save configuration
        with open(services_file, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

        # Reload Traefik
        traefik_manager.reload_traefik()

        logger.info(f"Service created: {service.name}")

        return {
            'success': True,
            'message': f"Service '{service.name}' created successfully",
            'service': {
                'name': service.name,
                'url': service.url,
                'healthcheck_path': service.healthcheck_path
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create service: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/services/{service_name}")
async def get_service(service_name: str):
    """Get details of a specific service"""
    try:
        import yaml
        for config_path in traefik_manager.dynamic_dir.glob("*.yml"):
            try:
                with open(config_path, 'r') as f:
                    config = yaml.safe_load(f)

                if config and 'http' in config and 'services' in config['http']:
                    if service_name in config['http']['services']:
                        service_data = config['http']['services'][service_name]
                        return {
                            'service': {
                                'name': service_name,
                                'config': service_data,
                                'source_file': config_path.name
                            }
                        }
            except Exception as e:
                logger.warning(f"Failed to parse {config_path.name}: {e}")

        raise HTTPException(status_code=404, detail=f"Service '{service_name}' not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get service: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/services/{service_name}")
async def delete_service(service_name: str):
    """Delete a Traefik service"""
    try:
        import yaml
        deleted = False

        for config_path in traefik_manager.dynamic_dir.glob("*.yml"):
            try:
                with open(config_path, 'r') as f:
                    config = yaml.safe_load(f)

                if config and 'http' in config and 'services' in config['http']:
                    if service_name in config['http']['services']:
                        del config['http']['services'][service_name]

                        with open(config_path, 'w') as f:
                            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

                        deleted = True
                        break
            except Exception as e:
                logger.warning(f"Failed to process {config_path.name}: {e}")

        if not deleted:
            raise HTTPException(status_code=404, detail=f"Service '{service_name}' not found")

        # Reload Traefik
        traefik_manager.reload_traefik()

        logger.info(f"Service deleted: {service_name}")

        return {
            'success': True,
            'message': f"Service '{service_name}' deleted successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete service: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Middleware Management ====================

@router.get("/middlewares")
async def list_middlewares():
    """List all Traefik middlewares"""
    try:
        middleware_list = traefik_manager.list_middleware()
        return {"middlewares": middleware_list, "count": len(middleware_list)}
    except MiddlewareError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/middlewares", status_code=201)
async def create_middleware(middleware: MiddlewareCreate):
    """Create a new Traefik middleware"""
    try:
        result = traefik_manager.create_middleware(
            name=middleware.name,
            type=middleware.type,
            config=middleware.config,
            username="api-user"
        )
        return result
    except MiddlewareError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create middleware: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/middlewares/{middleware_name}")
async def get_middleware(middleware_name: str):
    """Get details of a specific middleware"""
    try:
        middleware_list = traefik_manager.list_middleware()
        middleware = next((m for m in middleware_list if m['name'] == middleware_name), None)

        if not middleware:
            raise HTTPException(status_code=404, detail=f"Middleware '{middleware_name}' not found")

        return {"middleware": middleware}
    except MiddlewareError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/middlewares/{middleware_name}")
async def update_middleware(middleware_name: str, updates: MiddlewareUpdate):
    """Update an existing middleware"""
    try:
        if not updates.config:
            raise HTTPException(status_code=400, detail="No config updates provided")

        result = traefik_manager.update_middleware(
            name=middleware_name,
            config=updates.config,
            username="api-user"
        )
        return result
    except MiddlewareError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update middleware: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/middlewares/{middleware_name}")
async def delete_middleware(middleware_name: str):
    """Delete a Traefik middleware"""
    try:
        result = traefik_manager.delete_middleware(name=middleware_name, username="api-user")
        return result
    except MiddlewareError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to delete middleware: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Configuration Management ====================

@router.get("/config/summary")
async def get_config_summary():
    """Get Traefik configuration summary"""
    try:
        routes = traefik_manager.list_routes()
        certificates = traefik_manager.list_certificates()

        return {
            "summary": {
                "routes": len(routes),
                "certificates": len(certificates)
            },
            "timestamp": datetime.utcnow().isoformat()
        }
    except TraefikError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config/reload")
async def reload_config():
    """Reload Traefik configuration"""
    try:
        result = traefik_manager.reload_traefik()
        return result
    except TraefikError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config/validate")
async def validate_config():
    """Validate Traefik configuration"""
    try:
        is_valid = traefik_manager.validate_config()
        return {
            "valid": is_valid,
            "message": "Configuration is valid" if is_valid else "Configuration is invalid",
            "timestamp": datetime.utcnow().isoformat()
        }
    except ConfigurationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to validate config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


logger.info("Traefik Management API (Epic 1.3) initialized - Full CRUD version")
