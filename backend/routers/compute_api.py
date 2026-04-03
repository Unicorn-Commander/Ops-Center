"""
GPU Compute Fabric — Control Plane API
========================================
Provides REST endpoints for the GPU compute fabric:
- Node registration and heartbeat management
- Workload dispatch with auto-routing
- Named pipeline CRUD
- Maintenance mode (drain/resume)

Part of the Unicorn GPU Compute Fabric (Phases 2-3).

Author: GPU Compute Fabric Team
Created: 2026-04-02
"""

import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

if '/app' not in sys.path:
    sys.path.insert(0, '/app')

from database.connection import get_db_pool

logger = logging.getLogger(__name__)

# Node is considered offline if no heartbeat for this many seconds
HEARTBEAT_TIMEOUT = 90

router = APIRouter(
    prefix="/api/v1/compute",
    tags=["compute-fabric"],
    responses={
        400: {"description": "Bad request"},
        404: {"description": "Not found"},
        500: {"description": "Internal server error"},
    },
)


# =============================================================================
# Pydantic Models
# =============================================================================

class NodeRegistrationRequest(BaseModel):
    node_id: str
    hostname: Optional[str] = None
    ip: Optional[str] = None
    gpus: List[Dict[str, Any]] = []
    engines: List[Dict[str, Any]] = []
    capabilities: List[str] = []


class HeartbeatRequest(BaseModel):
    node_id: str
    status: Optional[str] = "active"
    gpus: List[Dict[str, Any]] = []
    loaded_models: List[Dict[str, Any]] = []
    queue_depth: Dict[str, int] = {}


class DispatchRequest(BaseModel):
    workload_type: str  # llm, image, music, embedding
    pipeline: Optional[str] = None  # named pipeline
    payload: Dict[str, Any] = {}
    routing: Optional[Dict[str, Any]] = None  # manual overrides


class DispatchResponse(BaseModel):
    job_id: str
    status: str  # dispatched, queued, failed
    target_node: Optional[str] = None
    target_gpu: Optional[int] = None
    routing_decision: Dict[str, Any] = {}
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class PipelineCreateRequest(BaseModel):
    name: str
    workload_type: str
    config: Dict[str, Any] = {}


class PipelineUpdateRequest(BaseModel):
    workload_type: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class PipelineResponse(BaseModel):
    id: str
    name: str
    workload_type: Optional[str]
    config: Dict[str, Any]
    created_by: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]


class NodeResponse(BaseModel):
    id: str
    node_id: str
    hostname: Optional[str]
    ip_address: Optional[str]
    status: str
    last_heartbeat: Optional[str]
    capabilities: List[str]
    gpu_info: List[Dict[str, Any]]
    engines: List[Dict[str, Any]]
    gpu_status: List[Dict[str, Any]]
    loaded_models: List[Dict[str, Any]]
    queue_depth: Dict[str, int]
    is_online: bool


# =============================================================================
# Helper Functions
# =============================================================================

async def _ensure_tables(pool):
    """Create tables if they don't exist (idempotent)."""
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS compute_nodes (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                node_id VARCHAR(64) UNIQUE NOT NULL,
                hostname VARCHAR(255),
                ip_address INET,
                status VARCHAR(20) DEFAULT 'active',
                last_heartbeat TIMESTAMPTZ,
                capabilities JSONB DEFAULT '[]'::jsonb,
                gpu_info JSONB DEFAULT '[]'::jsonb,
                engines JSONB DEFAULT '[]'::jsonb,
                gpu_status JSONB DEFAULT '[]'::jsonb,
                loaded_models JSONB DEFAULT '[]'::jsonb,
                queue_depth JSONB DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS compute_pipelines (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name VARCHAR(128) UNIQUE NOT NULL,
                workload_type VARCHAR(32),
                config JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_by VARCHAR(128),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS compute_jobs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workload_type VARCHAR(32),
                pipeline_name VARCHAR(128),
                target_node VARCHAR(64),
                target_gpu INTEGER,
                status VARCHAR(20) DEFAULT 'queued',
                routing_decision JSONB,
                payload JSONB,
                result JSONB,
                duration_ms INTEGER,
                error TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                completed_at TIMESTAMPTZ
            )
        """)


def _node_row_to_response(row) -> NodeResponse:
    """Convert a database row to a NodeResponse."""
    import json
    last_hb = row["last_heartbeat"]
    is_online = False
    if last_hb:
        if last_hb.tzinfo is None:
            last_hb = last_hb.replace(tzinfo=timezone.utc)
        is_online = (datetime.now(timezone.utc) - last_hb).total_seconds() < HEARTBEAT_TIMEOUT

    # Handle capabilities — might be a JSON string or already a list
    capabilities = row.get("capabilities") or []
    if isinstance(capabilities, str):
        try:
            capabilities = json.loads(capabilities)
        except (json.JSONDecodeError, TypeError):
            capabilities = []

    gpu_info = row.get("gpu_info") or []
    if isinstance(gpu_info, str):
        try:
            gpu_info = json.loads(gpu_info)
        except (json.JSONDecodeError, TypeError):
            gpu_info = []

    engines = row.get("engines") or []
    if isinstance(engines, str):
        try:
            engines = json.loads(engines)
        except (json.JSONDecodeError, TypeError):
            engines = []

    gpu_status = row.get("gpu_status") or []
    if isinstance(gpu_status, str):
        try:
            gpu_status = json.loads(gpu_status)
        except (json.JSONDecodeError, TypeError):
            gpu_status = []

    loaded_models = row.get("loaded_models") or []
    if isinstance(loaded_models, str):
        try:
            loaded_models = json.loads(loaded_models)
        except (json.JSONDecodeError, TypeError):
            loaded_models = []

    queue_depth = row.get("queue_depth") or {}
    if isinstance(queue_depth, str):
        try:
            queue_depth = json.loads(queue_depth)
        except (json.JSONDecodeError, TypeError):
            queue_depth = {}

    return NodeResponse(
        id=str(row["id"]),
        node_id=row["node_id"],
        hostname=row.get("hostname"),
        ip_address=str(row["ip_address"]) if row.get("ip_address") else None,
        status=row.get("status", "active"),
        last_heartbeat=last_hb.isoformat() if last_hb else None,
        capabilities=capabilities,
        gpu_info=gpu_info,
        engines=engines,
        gpu_status=gpu_status,
        loaded_models=loaded_models,
        queue_depth=queue_depth,
        is_online=is_online,
    )


# =============================================================================
# Node Registration & Heartbeat
# =============================================================================

@router.post("/register")
async def register_node(request: NodeRegistrationRequest):
    """
    Register a GPU node with the control plane.
    Called by the GPU Agent on startup.
    """
    pool = await get_db_pool()
    await _ensure_tables(pool)

    import json

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO compute_nodes (
                node_id, hostname, ip_address, capabilities, gpu_info, engines,
                last_heartbeat, updated_at
            )
            VALUES ($1, $2, $3::inet, $4::jsonb, $5::jsonb, $6::jsonb, NOW(), NOW())
            ON CONFLICT (node_id) DO UPDATE SET
                hostname = EXCLUDED.hostname,
                ip_address = EXCLUDED.ip_address,
                capabilities = EXCLUDED.capabilities,
                gpu_info = EXCLUDED.gpu_info,
                engines = EXCLUDED.engines,
                last_heartbeat = NOW(),
                updated_at = NOW(),
                status = 'active'
            RETURNING id, node_id
        """,
            request.node_id,
            request.hostname,
            request.ip,
            json.dumps(request.capabilities),
            json.dumps(request.gpus),
            json.dumps(request.engines),
        )

    logger.info("Node registered: %s (%s)", request.node_id, request.hostname)
    return {
        "status": "registered",
        "node_id": request.node_id,
        "id": str(row["id"]),
    }


@router.post("/heartbeat")
async def receive_heartbeat(request: HeartbeatRequest):
    """
    Receive heartbeat from a GPU Agent.
    Updates GPU status, loaded models, and queue depth.
    """
    pool = await get_db_pool()
    await _ensure_tables(pool)

    import json

    async with pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE compute_nodes SET
                gpu_status = $2::jsonb,
                loaded_models = $3::jsonb,
                queue_depth = $4::jsonb,
                last_heartbeat = NOW(),
                status = COALESCE($5, status),
                updated_at = NOW()
            WHERE node_id = $1
        """,
            request.node_id,
            json.dumps(request.gpus),
            json.dumps(request.loaded_models),
            json.dumps(request.queue_depth),
            request.status,
        )

    if "UPDATE 0" in result:
        raise HTTPException(
            status_code=404,
            detail=f"Node not registered: {request.node_id}. Call /register first.",
        )

    return {"status": "ok", "node_id": request.node_id}


# =============================================================================
# Node Management
# =============================================================================

@router.get("/nodes")
async def list_nodes():
    """List all registered nodes with GPU status."""
    pool = await get_db_pool()
    await _ensure_tables(pool)

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM compute_nodes ORDER BY created_at
        """)

    nodes = [_node_row_to_response(row) for row in rows]
    return {"nodes": [n.model_dump() for n in nodes], "total": len(nodes)}


@router.get("/nodes/{node_id}")
async def get_node(node_id: str):
    """Get details for a single node."""
    pool = await get_db_pool()
    await _ensure_tables(pool)

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT * FROM compute_nodes WHERE node_id = $1
        """, node_id)

    if not row:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")

    return _node_row_to_response(row).model_dump()


@router.post("/nodes/{node_id}/drain")
async def drain_node(node_id: str):
    """Put a node into maintenance mode (stop accepting new work)."""
    pool = await get_db_pool()

    async with pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE compute_nodes SET status = 'draining', updated_at = NOW()
            WHERE node_id = $1
        """, node_id)

    if "UPDATE 0" in result:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")

    # Also tell the agent to drain
    try:
        node_row = None
        async with pool.acquire() as conn:
            node_row = await conn.fetchrow(
                "SELECT ip_address FROM compute_nodes WHERE node_id = $1", node_id
            )
        if node_row and node_row["ip_address"]:
            async with httpx.AsyncClient(timeout=5.0) as client:
                drain_url = "http://unicorn-gpu-agent:8090" if node_row['ip_address'] in ('192.168.10.10', '127.0.0.1') else f"http://{node_row['ip_address']}:8090"
                await client.post(f"{drain_url}/api/v1/node/drain")
    except Exception as e:
        logger.warning("Could not notify agent for drain: %s", e)

    logger.info("Node %s set to draining", node_id)
    return {"status": "draining", "node_id": node_id}


@router.post("/nodes/{node_id}/resume")
async def resume_node(node_id: str):
    """Resume a node (accept new work again)."""
    pool = await get_db_pool()

    async with pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE compute_nodes SET status = 'active', updated_at = NOW()
            WHERE node_id = $1
        """, node_id)

    if "UPDATE 0" in result:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")

    # Also tell the agent to resume
    try:
        node_row = None
        async with pool.acquire() as conn:
            node_row = await conn.fetchrow(
                "SELECT ip_address FROM compute_nodes WHERE node_id = $1", node_id
            )
        if node_row and node_row["ip_address"]:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resume_url = "http://unicorn-gpu-agent:8090" if node_row['ip_address'] in ('192.168.10.10', '127.0.0.1') else f"http://{node_row['ip_address']}:8090"
                await client.post(f"{resume_url}/api/v1/node/resume")
    except Exception as e:
        logger.warning("Could not notify agent for resume: %s", e)

    logger.info("Node %s resumed", node_id)
    return {"status": "active", "node_id": node_id}


# =============================================================================
# Workload Dispatch
# =============================================================================

@router.post("/dispatch", response_model=DispatchResponse)
async def dispatch_workload(request: DispatchRequest):
    """
    Main entry point — dispatch a workload to the best node/GPU.

    Routing priority:
    1. Manual override (routing.target_node / routing.target_gpu)
    2. Pipeline rules (if pipeline name specified)
    3. Auto-routing (capability + availability + latency)
    """
    pool = await get_db_pool()
    await _ensure_tables(pool)

    import json

    job_id = str(uuid4())
    routing_decision = {}
    start_time_ms = time.time() * 1000

    # Step 1: Resolve pipeline config if specified
    pipeline_config = {}
    if request.pipeline:
        async with pool.acquire() as conn:
            pipeline_row = await conn.fetchrow("""
                SELECT config FROM compute_pipelines WHERE name = $1
            """, request.pipeline)
        if pipeline_row:
            config = pipeline_row["config"]
            if isinstance(config, str):
                pipeline_config = json.loads(config)
            else:
                pipeline_config = config
            routing_decision["pipeline"] = request.pipeline
        else:
            routing_decision["pipeline_warning"] = f"Pipeline '{request.pipeline}' not found, using auto-routing"

    # Step 2: Determine target node and GPU
    target_node = None
    target_gpu = None

    # Manual override takes highest priority
    routing = request.routing or {}
    if routing.get("target_node"):
        target_node = routing["target_node"]
        target_gpu = routing.get("target_gpu")
        routing_decision["method"] = "manual_override"
    elif pipeline_config.get("target_node"):
        target_node = pipeline_config["target_node"]
        target_gpu = pipeline_config.get("target_gpu")
        routing_decision["method"] = "pipeline_rule"
    else:
        # Auto-routing: find best available node
        target_node, target_gpu, reason = await _auto_route(
            pool, request.workload_type, pipeline_config
        )
        routing_decision["method"] = "auto_routing"
        routing_decision["reason"] = reason

    if not target_node:
        # Log failed job
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO compute_jobs (
                    id, workload_type, pipeline_name, status,
                    routing_decision, payload, error, created_at
                )
                VALUES ($1::uuid, $2, $3, 'failed', $4::jsonb, $5::jsonb, $6, NOW())
            """,
                job_id,
                request.workload_type,
                request.pipeline,
                json.dumps(routing_decision),
                json.dumps(request.payload),
                "No available node for this workload",
            )

        return DispatchResponse(
            job_id=job_id,
            status="failed",
            routing_decision=routing_decision,
            error="No available node for this workload",
        )

    # Step 3: Dispatch to the target node's agent
    result = None
    error = None
    status = "dispatched"

    try:
        # Get the node's agent URL
        async with pool.acquire() as conn:
            node_row = await conn.fetchrow("""
                SELECT ip_address, status FROM compute_nodes WHERE node_id = $1
            """, target_node)

        if not node_row:
            raise HTTPException(status_code=404, detail=f"Target node not found: {target_node}")

        if node_row["status"] == "draining":
            raise HTTPException(status_code=503, detail=f"Target node is draining: {target_node}")

        # Use Docker container hostname for local nodes, IP for remote
        node_ip = str(node_row['ip_address'])
        if node_ip in ('192.168.10.10', '127.0.0.1', 'localhost', '192.168.10.10/32'):
            agent_url = "http://unicorn-gpu-agent:8090"
        else:
            agent_url = f"http://{node_ip}:8090"

        execute_payload = {
            "job_id": job_id,
            "workload_type": request.workload_type,
            "target_gpu": target_gpu,
            "payload": request.payload,
        }

        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(
                f"{agent_url}/api/v1/node/execute",
                json=execute_payload,
            )
            if resp.status_code == 200:
                resp_data = resp.json()
                status = resp_data.get("status", "completed")
                result = resp_data.get("result")
                error = resp_data.get("error")
                target_gpu = resp_data.get("gpu_id", target_gpu)
            else:
                status = "failed"
                error = f"Agent returned {resp.status_code}: {resp.text}"

    except httpx.ConnectError as e:
        status = "failed"
        error = f"Cannot reach node agent at {target_node}"
        logger.error("ConnectError dispatching to %s (url=%s): %s", target_node, agent_url, e)
    except HTTPException:
        raise
    except Exception as e:
        status = "failed"
        error = str(e)
        logger.error("Dispatch exception for %s: %s", target_node, e)

    # Step 4: Log the job
    duration_ms = int(time.time() * 1000 - start_time_ms)
    completed_at = datetime.now(timezone.utc) if status in ("completed", "failed") else None
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO compute_jobs (
                id, workload_type, pipeline_name, target_node, target_gpu,
                status, routing_decision, payload, result, duration_ms, error,
                created_at, completed_at
            )
            VALUES (
                $1::uuid, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb,
                $9::jsonb, $10, $11, NOW(), $12
            )
        """,
            job_id,
            request.workload_type,
            request.pipeline,
            target_node,
            target_gpu,
            status,
            json.dumps(routing_decision),
            json.dumps(request.payload),
            json.dumps(result) if result else None,
            duration_ms,
            error,
            completed_at,
        )

    return DispatchResponse(
        job_id=job_id,
        status=status,
        target_node=target_node,
        target_gpu=target_gpu,
        routing_decision=routing_decision,
        result=result,
        error=error,
    )


async def _auto_route(
    pool, workload_type: str, pipeline_config: Dict[str, Any]
) -> tuple:
    """
    Auto-route a workload to the best available node.

    Scoring:
    - Must support the workload_type capability
    - Must be active and online (heartbeat within HEARTBEAT_TIMEOUT)
    - Prefer nodes with more free VRAM
    - Prefer nodes listed in pipeline preferred_nodes
    - Prefer local over remote (lower latency)

    Returns:
        (target_node, target_gpu, reason_str) or (None, None, reason_str)
    """
    import json

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM compute_nodes
            WHERE status = 'active'
            AND last_heartbeat > NOW() - INTERVAL '%s seconds'
        """ % HEARTBEAT_TIMEOUT)

    if not rows:
        return None, None, "No active nodes with recent heartbeat"

    preferred_nodes = pipeline_config.get("preferred_nodes", [])
    candidates = []

    for row in rows:
        caps = row.get("capabilities") or []
        if isinstance(caps, str):
            try:
                caps = json.loads(caps)
            except (json.JSONDecodeError, TypeError):
                caps = []

        if workload_type not in caps:
            continue

        # Calculate score
        score = 0
        best_gpu = None

        # Parse GPU status to find free VRAM
        gpu_status = row.get("gpu_status") or []
        if isinstance(gpu_status, str):
            try:
                gpu_status = json.loads(gpu_status)
            except (json.JSONDecodeError, TypeError):
                gpu_status = []

        max_free_vram = 0
        for gpu in gpu_status:
            free = gpu.get("vram_free_mb", 0)
            if free > max_free_vram:
                max_free_vram = free
                best_gpu = gpu.get("id")

        score += max_free_vram  # More free VRAM = higher score

        # ── Cost awareness ──
        # Local nodes are "free", cloud nodes cost money.
        # Strongly prefer local unless pipeline explicitly wants cloud.
        node_ip = str(row.get("ip_address", ""))
        is_local = node_ip.startswith("192.168.") or node_ip.startswith("10.") or node_ip.startswith("100.")
        if is_local:
            score += 50000  # Strong local preference — cloud only as overflow
        # Cloud nodes get no bonus (score stays at VRAM level)

        # ── GPU capability matching ──
        # Check if GPU architecture meets workload requirements
        gpu_info = row.get("gpu_info") or []
        if isinstance(gpu_info, str):
            try:
                gpu_info = json.loads(gpu_info)
            except (json.JSONDecodeError, TypeError):
                gpu_info = []

        requested_model = pipeline_config.get("model", "")
        for gpu in gpu_info:
            gpu_id = gpu.get("id")
            features = gpu.get("features", [])
            arch = gpu.get("architecture", "")
            compute_cap = float(gpu.get("compute_capability", "0") or "0")
            vram_mb = gpu.get("vram_mb", 0)

            # FP8 workloads need Ampere+ (compute 8.0+)
            if pipeline_config.get("quant_method") == "fp8" and compute_cap < 8.0:
                if gpu_id == best_gpu:
                    score -= 20000  # Penalize — wrong architecture for FP8
                continue

            # Flash attention needs compute 7.5+
            if "flash_attention" in features and gpu_id == best_gpu:
                score += 2000  # Bonus for flash attention support

            # Tensor cores bonus for generation workloads
            if "tensor_cores" in features and workload_type in ("image", "music"):
                score += 1000

        # ── Model affinity ──
        # If the requested model is already loaded on a GPU, prefer that GPU
        # to avoid cold start (30-60s model loading)
        loaded_models = row.get("loaded_models") or []
        if isinstance(loaded_models, str):
            try:
                loaded_models = json.loads(loaded_models)
            except (json.JSONDecodeError, TypeError):
                loaded_models = []

        payload_model = pipeline_config.get("model", "")
        if not payload_model and isinstance(pipeline_config.get("payload"), dict):
            payload_model = pipeline_config["payload"].get("model", "")

        for lm in loaded_models:
            lm_model = lm.get("model", "") if isinstance(lm, dict) else str(lm)
            lm_gpu = lm.get("gpu", None) if isinstance(lm, dict) else None
            if payload_model and payload_model in lm_model:
                score += 30000  # Strong bonus — model already warm
                if lm_gpu is not None:
                    best_gpu = lm_gpu  # Use the GPU where it's loaded
                break

        # ── Preferred nodes (pipeline config) ──
        node_id = row["node_id"]
        for pref in preferred_nodes:
            pref_node = pref.split(":")[0] if ":" in pref else pref
            if node_id == pref_node:
                score += 10000  # Pipeline preference bonus
                if ":" in pref:
                    try:
                        best_gpu = int(pref.split(":")[1].replace("gpu", ""))
                    except ValueError:
                        pass
                break

        # ── Queue depth penalty ──
        queue = row.get("queue_depth") or {}
        if isinstance(queue, str):
            try:
                queue = json.loads(queue)
            except (json.JSONDecodeError, TypeError):
                queue = {}
        queue_for_type = queue.get(workload_type, 0)
        score -= queue_for_type * 1000  # Penalize busy queues

        candidates.append((node_id, best_gpu, score))

    if not candidates:
        return None, None, f"No nodes support workload type '{workload_type}'"

    # Sort by score descending
    candidates.sort(key=lambda x: -x[2])
    winner = candidates[0]

    reason = f"Selected {winner[0]} (gpu={winner[1]}, score={winner[2]})"
    if len(candidates) > 1:
        reason += f" from {len(candidates)} candidates"

    return winner[0], winner[1], reason


# =============================================================================
# Pipeline CRUD
# =============================================================================

@router.get("/pipelines")
async def list_pipelines():
    """List all named routing pipelines."""
    pool = await get_db_pool()
    await _ensure_tables(pool)

    import json

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM compute_pipelines ORDER BY name
        """)

    pipelines = []
    for row in rows:
        config = row["config"]
        if isinstance(config, str):
            config = json.loads(config)
        pipelines.append({
            "id": str(row["id"]),
            "name": row["name"],
            "workload_type": row.get("workload_type"),
            "config": config,
            "created_by": row.get("created_by"),
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
            "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
        })

    return {"pipelines": pipelines, "total": len(pipelines)}


@router.post("/pipelines")
async def create_pipeline(request: PipelineCreateRequest):
    """Create a new named routing pipeline."""
    pool = await get_db_pool()
    await _ensure_tables(pool)

    import json

    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow("""
                INSERT INTO compute_pipelines (name, workload_type, config, created_by)
                VALUES ($1, $2, $3::jsonb, $4)
                RETURNING id, name, workload_type, config, created_by, created_at, updated_at
            """,
                request.name,
                request.workload_type,
                json.dumps(request.config),
                "admin",
            )

            logger.info("Pipeline created: %s", request.name)

            config = row["config"]
            if isinstance(config, str):
                config = json.loads(config)

            return {
                "id": str(row["id"]),
                "name": row["name"],
                "workload_type": row["workload_type"],
                "config": config,
                "created_by": row["created_by"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            }

        except Exception as e:
            if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                raise HTTPException(
                    status_code=409,
                    detail=f"Pipeline '{request.name}' already exists"
                )
            logger.error("Error creating pipeline: %s", e)
            raise HTTPException(status_code=500, detail=f"Failed to create pipeline: {str(e)}")


@router.put("/pipelines/{name}")
async def update_pipeline(name: str, request: PipelineUpdateRequest):
    """Update an existing pipeline."""
    pool = await get_db_pool()

    import json

    updates = []
    params = [name]
    param_idx = 2

    if request.workload_type is not None:
        updates.append(f"workload_type = ${param_idx}")
        params.append(request.workload_type)
        param_idx += 1

    if request.config is not None:
        updates.append(f"config = ${param_idx}::jsonb")
        params.append(json.dumps(request.config))
        param_idx += 1

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updates.append("updated_at = NOW()")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(f"""
            UPDATE compute_pipelines
            SET {', '.join(updates)}
            WHERE name = $1
            RETURNING id, name, workload_type, config, created_by, created_at, updated_at
        """, *params)

    if not row:
        raise HTTPException(status_code=404, detail=f"Pipeline not found: {name}")

    config = row["config"]
    if isinstance(config, str):
        config = json.loads(config)

    logger.info("Pipeline updated: %s", name)
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "workload_type": row["workload_type"],
        "config": config,
        "created_by": row["created_by"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


@router.delete("/pipelines/{name}")
async def delete_pipeline(name: str):
    """Delete a named pipeline."""
    pool = await get_db_pool()

    async with pool.acquire() as conn:
        result = await conn.execute("""
            DELETE FROM compute_pipelines WHERE name = $1
        """, name)

    if "DELETE 0" in result:
        raise HTTPException(status_code=404, detail=f"Pipeline not found: {name}")

    logger.info("Pipeline deleted: %s", name)
    return {"status": "deleted", "name": name}


# =============================================================================
# Job History
# =============================================================================

@router.get("/jobs")
async def list_jobs(
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    workload_type: Optional[str] = None,
    node_id: Optional[str] = None,
):
    """List recent dispatch jobs for debugging and analytics."""
    pool = await get_db_pool()
    await _ensure_tables(pool)

    conditions = []
    params = []
    param_idx = 1

    if status:
        conditions.append(f"status = ${param_idx}")
        params.append(status)
        param_idx += 1

    if workload_type:
        conditions.append(f"workload_type = ${param_idx}")
        params.append(workload_type)
        param_idx += 1

    if node_id:
        conditions.append(f"target_node = ${param_idx}")
        params.append(node_id)
        param_idx += 1

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT id, workload_type, pipeline_name, target_node, target_gpu,
                   status, routing_decision, duration_ms, error, created_at, completed_at
            FROM compute_jobs
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """, *params, limit, offset)

        count_row = await conn.fetchval(f"""
            SELECT COUNT(*) FROM compute_jobs {where_clause}
        """, *params)

    import json
    jobs = []
    for row in rows:
        routing = row.get("routing_decision") or {}
        if isinstance(routing, str):
            routing = json.loads(routing)
        jobs.append({
            "id": str(row["id"]),
            "workload_type": row["workload_type"],
            "pipeline_name": row.get("pipeline_name"),
            "target_node": row.get("target_node"),
            "target_gpu": row.get("target_gpu"),
            "status": row["status"],
            "routing_decision": routing,
            "duration_ms": row.get("duration_ms"),
            "error": row.get("error"),
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
            "completed_at": row["completed_at"].isoformat() if row.get("completed_at") else None,
        })

    return {"jobs": jobs, "total": count_row, "limit": limit, "offset": offset}
