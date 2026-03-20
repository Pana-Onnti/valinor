"""
Memory tools — Persistent swarm memory for cross-run learning.

Handles reading/writing swarm memory and output artifacts.
"""

import json
from datetime import datetime
from pathlib import Path

from claude_agent_sdk import tool

from valinor.config import MEMORY_DIR, OUTPUT_DIR


@tool(
    "read_memory",
    "Read previous swarm memory for a client. Returns findings from past runs.",
    {
        "client_name": str,
        "period": str,
    },
)
async def read_memory(args):
    """Read swarm memory for a specific client and period."""
    client = args["client_name"]
    period = args.get("period")

    memory_dir = MEMORY_DIR / client

    if not memory_dir.exists():
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"status": "no_memory", "client": client, "message": "First run — no previous memory."}
                    ),
                }
            ]
        }

    if period:
        # Look for specific period
        memory_file = memory_dir / f"swarm_memory_{period}.json"
        if memory_file.exists():
            with open(memory_file, "r", encoding="utf-8") as f:
                memory = json.load(f)
            return {
                "content": [
                    {"type": "text", "text": json.dumps({"status": "found", "period": period, "memory": memory}, indent=2)}
                ]
            }

    # Find latest memory
    memory_files = sorted(memory_dir.glob("swarm_memory_*.json"), reverse=True)
    if not memory_files:
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"status": "no_memory", "client": client}),
                }
            ]
        }

    with open(memory_files[0], "r", encoding="utf-8") as f:
        memory = json.load(f)

    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "status": "found",
                        "period": memory_files[0].stem.replace("swarm_memory_", ""),
                        "memory": memory,
                    },
                    indent=2,
                ),
            }
        ]
    }


@tool(
    "write_memory",
    "Write/update swarm memory for a client. Persists findings for future runs.",
    {
        "client_name": str,
        "period": str,
        "memory_data": str,
    },
)
async def write_memory(args):
    """Write swarm memory to disk."""
    client = args["client_name"]
    period = args["period"]
    memory_data = args["memory_data"]

    if isinstance(memory_data, str):
        memory_data = json.loads(memory_data)

    memory_dir = MEMORY_DIR / client
    memory_dir.mkdir(parents=True, exist_ok=True)

    memory_file = memory_dir / f"swarm_memory_{period}.json"

    # Add metadata
    memory_data["_metadata"] = {
        "written_at": datetime.now().isoformat(),
        "period": period,
        "client": client,
    }

    with open(memory_file, "w", encoding="utf-8") as f:
        json.dump(memory_data, f, indent=2, ensure_ascii=False)

    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "status": "written",
                        "path": str(memory_file),
                        "size_bytes": memory_file.stat().st_size,
                    }
                ),
            }
        ]
    }


@tool(
    "write_artifact",
    "Write an output artifact (entity_map, findings, report) to the output directory.",
    {
        "client_name": str,
        "period": str,
        "filename": str,
        "content": str,
    },
)
async def write_artifact(args):
    """Write an artifact file to the output directory."""
    client = args["client_name"]
    period = args["period"]
    filename = args["filename"]
    content = args["content"]

    output_dir = OUTPUT_DIR / client / period
    output_dir.mkdir(parents=True, exist_ok=True)

    artifact_path = output_dir / filename

    with open(artifact_path, "w", encoding="utf-8") as f:
        f.write(content)

    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "status": "written",
                        "path": str(artifact_path),
                        "size_bytes": artifact_path.stat().st_size,
                    }
                ),
            }
        ]
    }
