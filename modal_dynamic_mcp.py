import os
import time
import asyncio
import modal
from typing import Optional, List

APP_VERSION = "2026-09-24-no-auth"

# ---------- Limits ----------
MAX_WAIT_SECONDS = 540       # wait=True cap (web function ke 600s timeout se pehle)
MIN_TIMEOUT_SECONDS = 10     # Modal sandbox ka minimum timeout
MAX_TIMEOUT_SECONDS = 86400  # sandbox ki max life: 24 ghante
MAX_OUTPUT_CHARS = 20000     # isse bada output truncate hota hai
MAX_CONTAINERS = 5           # ek saath max containers (bill / abuse control)

# User ka GPU naam -> Modal GPU string
GPU_MAP = {
    "T4": "T4",
    "L4": "L4",
    "A10": "A10G",
    "A10G": "A10G",
    "A100": "A100",
    "A100-40GB": "A100-40GB",
    "A100-80GB": "A100-80GB",
    "L40S": "L40S",
    "H100": "H100",
    "H100!": "H100!",
    "H200": "H200",
    "B200": "B200",
}

app = modal.App("dynamic-python-mcp")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install(
        "fastapi==0.115.14",
        "fastmcp==2.12.0",
        "pydantic>=2.0",
    )
)

# Drive credentials sirf sandbox ko milte hain (web function ko nahi)
GOOGLE_DRIVE_SECRET = modal.Secret.from_name("google-drive")


def _clip(text, limit=None):
    limit = limit or MAX_OUTPUT_CHARS
    if len(text) > limit:
        return "...[truncated]...\n" + text[-limit:]
    return text


def make_mcp_server():
    from fastmcp import FastMCP

    mcp = FastMCP("Dynamic Python MCP (pip install + GPU + Google Drive)")

    @mcp.tool()
    async def run_python(
        code: str,
        packages: Optional[List[str]] = None,
        timeout_seconds: int = 300,
        python_version: str = "3.12",
        gpu: Optional[str] = None,
        wait: bool = True,
    ) -> str:
        """
        Run arbitrary Python code in a Modal Sandbox (dynamic pip install + optional GPU).

        Args:
            code: Python code to execute
            packages: pip packages to install (e.g. ["torch", "numpy"])
            timeout_seconds: sandbox max life in seconds (default 300, min 10, max 86400).
                With wait=True it is capped at 540s.
            python_version: e.g. "3.12"
            gpu: "T4" | "L4" | "A10G" | "A100" | "A100-40GB" | "A100-80GB" |
                 "L40S" | "H100" | "H100!" | "H200" | "B200" | None (CPU)
            wait: True = wait for the result (short jobs, up to ~9 min).
                  False = fire-and-forget for long jobs; the sandbox stops by
                  itself as soon as the code finishes.

        Returns:
            stdout/stderr when wait=True (very long output is truncated to the
            last 20000 chars), or the sandbox id when wait=False
        """
        started = time.monotonic()
        notes = []
        packages = packages or []

        # ---- timeout limits ----
        try:
            timeout_seconds = int(timeout_seconds)
        except (TypeError, ValueError):
            timeout_seconds = 300
        if timeout_seconds > MAX_TIMEOUT_SECONDS:
            timeout_seconds = MAX_TIMEOUT_SECONDS
            notes.append(f"⚠️ timeout_seconds max {MAX_TIMEOUT_SECONDS}s pe limit hua.")
        timeout_seconds = max(MIN_TIMEOUT_SECONDS, timeout_seconds)
        if wait and timeout_seconds > MAX_WAIT_SECONDS:
            timeout_seconds = MAX_WAIT_SECONDS
            notes.append(
                f"⚠️ wait=True mein timeout {MAX_WAIT_SECONDS}s pe limit hua. "
                "Lamba kaam ho to wait=False use karo."
            )

        # ---- GPU ----
        gpu_config = None
        if gpu:
            gpu_config = GPU_MAP.get(gpu.upper().strip())
            if gpu_config is None:
                return f"Unsupported GPU: {gpu}. Use: {', '.join(GPU_MAP)}"

        # ---- sandbox: code hi entrypoint hai, khatam hote hi sandbox band ----
        try:
            sandbox_image = modal.Image.debian_slim(python_version=python_version)
            if packages:
                sandbox_image = sandbox_image.pip_install(*packages)

            kwargs = {
                "image": sandbox_image,
                "timeout": timeout_seconds,
                "app": app,
                "secrets": [GOOGLE_DRIVE_SECRET],
            }
            if gpu_config:
                kwargs["gpu"] = gpu_config

            sb = await modal.Sandbox.create.aio("python", "-c", code, **kwargs)
        except Exception as e:
            return (
                "❌ Sandbox start nahi hua (packages / python_version / gpu check karo):\n"
                + _clip(str(e), 3000)
            )

        # ---- fire-and-forget ----
        if not wait:
            sandbox_id = sb.object_id
            try:
                await sb.detach.aio()
            except Exception:
                pass
            return "\n".join(
                notes
                + [
                    "Started (fire-and-forget)",
                    f"sandbox_id={sandbox_id}",
                    f"timeout_seconds={timeout_seconds}",
                    f"gpu={gpu_config or 'cpu'}",
                    "Code khatam hote hi sandbox apne aap band ho jayega.",
                    "Logs: Modal dashboard.",
                ]
            )

        # ---- wait for result ----
        try:
            remaining = max(5.0, MAX_WAIT_SECONDS - (time.monotonic() - started))
            await asyncio.wait_for(sb.wait.aio(), timeout=remaining)
            stdout = await sb.stdout.read.aio()
            stderr = await sb.stderr.read.aio()
            output = ""
            if stdout:
                output += f"=== STDOUT ===\n{stdout}\n"
            if stderr:
                output += f"=== STDERR ===\n{stderr}\n"
            if sb.returncode not in (0, None):
                output += f"\n[Exit code: {sb.returncode}]"
            result = _clip(output.strip() or "(no output)")
        except asyncio.TimeoutError:
            result = (
                f"⏱️ {MAX_WAIT_SECONDS}s ki limit pe band kiya. "
                "Lamba kaam ho to wait=False use karo."
            )
        except Exception as e:
            result = "❌ Run fail ya timeout ho gaya:\n" + _clip(str(e), 3000)
        finally:
            try:
                await sb.terminate.aio()
            except Exception:
                pass

        return "\n".join(notes + [result])

    return mcp


@app.function(
    image=image,
    timeout=600,
    max_containers=MAX_CONTAINERS,
)
@modal.asgi_app()
def web():
    from fastapi import FastAPI

    mcp = make_mcp_server()

    if mcp is None:
        raise RuntimeError(
            f"make_mcp_server() returned None. "
            f"Deployment version: {APP_VERSION}"
        )

    print(f"Starting Dynamic Python MCP {APP_VERSION}")

    # Endpoint: /mcp (no token required)
    mcp_app = mcp.http_app(
        path="/mcp",
        transport="streamable-http",
        stateless_http=True,
    )

    fastapi_app = FastAPI(
        lifespan=mcp_app.router.lifespan_context
    )
    fastapi_app.mount("/", mcp_app)

    return fastapi_app
