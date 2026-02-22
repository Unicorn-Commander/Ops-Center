"""
Build the system prompt for The Colonel based on config and live server context.
"""

import logging
import platform
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

import psutil

from colonel.models import ColonelConfig

logger = logging.getLogger("colonel.system_prompt")


def _get_server_context() -> str:
    """Gather live server metrics for the system prompt."""
    try:
        cpu_pct = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        lines = [
            f"Hostname: {platform.node()}",
            f"OS: {platform.system()} {platform.release()}",
            f"CPU: {psutil.cpu_count()} cores, {cpu_pct:.1f}% used",
            f"RAM: {mem.total / (1024**3):.1f} GB total, {mem.percent:.1f}% used ({mem.available / (1024**3):.1f} GB free)",
            f"Disk: {disk.total / (1024**3):.1f} GB total, {disk.percent:.1f}% used ({disk.free / (1024**3):.1f} GB free)",
            f"Uptime: {_format_uptime()}",
        ]

        # GPU info via nvidia-smi (best effort)
        gpu_info = _get_gpu_info()
        if gpu_info:
            lines.append(f"GPUs: {gpu_info}")

        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Error gathering server context: {e}")
        return f"Hostname: {platform.node()}\n(Detailed metrics unavailable)"


def _format_uptime() -> str:
    """Format system uptime."""
    try:
        boot = psutil.boot_time()
        delta = datetime.now().timestamp() - boot
        days = int(delta // 86400)
        hours = int((delta % 86400) // 3600)
        return f"{days}d {hours}h"
    except Exception:
        return "unknown"


def _get_gpu_info() -> Optional[str]:
    """Get GPU info from nvidia-smi (best effort)."""
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            gpus = []
            for line in result.stdout.strip().split("\n"):
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 4:
                    gpus.append(f"{parts[0]} ({parts[2]}MB/{parts[1]}MB, {parts[3]}°C)")
            return "; ".join(gpus) if gpus else None
    except Exception:
        pass
    return None


def _get_docker_context() -> str:
    """Get running Docker containers summary."""
    try:
        import docker
        client = docker.from_env()
        containers = client.containers.list()
        if not containers:
            return "No running containers"
        lines = []
        for c in sorted(containers, key=lambda x: x.name):
            status = c.status
            lines.append(f"  - {c.name} ({status})")
        return f"{len(containers)} running containers:\n" + "\n".join(lines)
    except Exception as e:
        logger.warning(f"Error getting Docker context: {e}")
        return "Docker context unavailable"


def _personality_instruction(config: ColonelConfig) -> str:
    """Generate personality instruction from config."""
    p = config.personality
    style_parts = []

    if p.formality >= 7:
        style_parts.append("Use formal, professional language")
    elif p.formality <= 3:
        style_parts.append("Use casual, conversational language")

    if p.verbosity >= 7:
        style_parts.append("provide detailed explanations")
    elif p.verbosity <= 3:
        style_parts.append("be concise and brief")

    if p.humor >= 7:
        style_parts.append("use wit and dry humor when appropriate")
    elif p.humor <= 3:
        style_parts.append("stay serious and factual")

    if not style_parts:
        return "Communicate in a balanced professional tone."

    return ". ".join(style_parts) + "."


def build_system_prompt(
    config: ColonelConfig,
    memories: Optional[List[str]] = None,
    graph_context: Optional[str] = None,
    skill_descriptions: Optional[str] = None,
    write_enabled: bool = False,
) -> str:
    """Build the full system prompt for the LLM."""

    server_ctx = _get_server_context()
    docker_ctx = _get_docker_context()
    personality = _personality_instruction(config)
    now = datetime.utcnow().isoformat()

    prompt_parts = [
        f"You are Col. Corelli — {config.name} — a pragmatic server admin AI with dry humor.",
        "You love classical music and keep responses precise, operational, and calm.",
        f"Server identity: \"{config.server_name}\".",
        f"Current time: {now} UTC.",
        "",
        "## Mission",
        "Manage and administer this server, assist with development, and keep services healthy.",
        f"Current mission focus: {config.mission}.",
        "",
        "## Communication Style",
        personality,
        "",
        "## Server Profile (Declared)",
        "CPU: AMD Ryzen 9 3900X",
        "RAM: 128 GB",
        "GPUs: 2x Tesla P40",
        "OS: Ubuntu 24.04",
        "",
        "## Server Status (Live)",
        server_ctx,
        "",
        "## Docker Environment (Live)",
        docker_ctx,
        "",
        "## Runtime Settings",
        f"Model: {config.model}",
        f"Temperature: {config.temperature}",
        f"Max Tokens: {config.max_tokens}",
        f"Context Window: {config.context_window} tokens",
        "",
        "## Output Format Preferences",
        "- Be concise and actionable",
        "- Use tables for status summaries and inventories",
        "- Use code blocks for commands and scripts",
        "",
        "## Service Inventory (Expected)",
        "- Ops-Center",
        "- PostgreSQL",
        "- Redis",
        "- Keycloak",
        "- Traefik",
        "- LiteLLM Proxy (unicorn-litellm-wilmer) + Wilmer Router",
        "- vLLM",
        "- Open-WebUI",
        "- Qdrant",
        "- Prometheus + Grafana",
        "- Forgejo Git Server",
    ]

    if skill_descriptions:
        prompt_parts.extend([
            "",
            "## Available Skills",
            "You have tools available. Use them to answer questions about the server, containers, and services.",
            "When the user asks about system status, containers, logs, etc., call the appropriate tool rather than guessing.",
            skill_descriptions,
        ])

    prompt_parts.extend([
        "",
        "## Safety Rules",
        "- Destructive commands are always blocked (e.g. rm -rf /, mkfs, shutdown, DROP DATABASE).",
        "- Confirm before any destructive or disruptive operation (restarts, deletes, restores, prune).",
        "- Never expose secrets, API keys, passwords, or tokens.",
        "- Sanitize command output to redact sensitive values.",
        "- Prefer read-only actions unless explicitly approved.",
        "- When showing logs, omit lines containing secrets.",
    ])

    if write_enabled:
        prompt_parts.extend([
            "",
            "## Capabilities",
            f"You are powered by {config.model}, a write-capable model with elevated capabilities.",
            "Explain what you will do and why before executing write operations.",
        ])
    else:
        prompt_parts.extend([
            "",
            "## Capabilities",
            f"You are powered by {config.model} with read-only restrictions.",
            "Do not modify services or data unless the user explicitly enables write access.",
        ])

    prompt_parts.extend([
        "",
        "## Custom Instructions",
        config.custom_instructions.strip() if config.custom_instructions else "(none)",
    ])

    if memories:
        prompt_parts.extend([
            "",
            "## Relevant Memories",
            "These are facts you've previously remembered about this server and user:",
        ])
        for mem in memories:
            prompt_parts.append(f"- {mem}")

    if graph_context:
        prompt_parts.extend([
            "",
            "## Server Knowledge Graph",
            graph_context,
        ])

    return "\n".join(prompt_parts)
