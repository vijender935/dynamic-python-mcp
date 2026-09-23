import modal
from typing import Optional, List

APP_VERSION = "2026-09-23-mcp-fix-1"

app = modal.App("dynamic-python-mcp")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install(
        "fastapi==0.115.14",
        "fastmcp==2.12.0",
        "pydantic>=2.0",
    )
)

GOOGLE_DRIVE_SECRET = modal.Secret.from_name("google-drive")


def make_mcp_server():
    from fastmcp import FastMCP

    mcp = FastMCP("Dynamic Python MCP (with pip install + H100 + Google Drive)")

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
        Run arbitrary Python code in a Modal Sandbox.

        Args:
            code: Python code to execute
            packages: pip packages to install
            timeout_seconds: max sandbox lifetime (default 300)
            python_version: e.g. "3.12"
            gpu: "T4" | "L4" | "A10G" | "A100" | "H100" | None
            wait: if True, wait for result; if False, fire-and-forget

        Returns:
            stdout/stderr when wait=True, or sandbox id when wait=False
        """
        import modal

        packages = packages or []

        sandbox_image = modal.Image.debian_slim(python_version=python_version)
        if packages:
            sandbox_image = sandbox_image.pip_install(*packages)

        gpu_config = None
        if gpu:
            g = gpu.upper().strip()
            mapping = {
                "H100": "H100", "H100!": "H100",
                "A100": "A100", "A100-80GB": "A100",
                "A10G": "A10G", "A10": "A10G",
                "L4": "L4", "T4": "T4",
            }
            if g not in mapping:
                return f"Unsupported GPU: {gpu}. Use T4, L4, A10G, A100, H100"
            gpu_config = mapping[g]

        sandbox_kwargs = {
            "image": sandbox_image,
            "timeout": timeout_seconds,
            "app": app,
            "secrets": [GOOGLE_DRIVE_SECRET],
        }
        if gpu_config:
            sandbox_kwargs["gpu"] = gpu_config

        sb = modal.Sandbox.create(**sandbox_kwargs)
        process = sb.exec("python", "-c", code)

        if not wait:
            sb.detach()
            return (
                f"Started (fire-and-forget)\n"
                f"sandbox_id={sb.object_id}\n"
                f"timeout_seconds={timeout_seconds}\n"
                f"gpu={gpu_config or 'cpu'}\n"
                f"Job is running in backend. Check Modal dashboard for logs."
            )

        try:
            process.wait()
            stdout = process.stdout.read()
            stderr = process.stderr.read()
            output = ""
            if stdout:
                output += f"=== STDOUT ===\n{stdout}\n"
            if stderr:
                output += f"=== STDERR ===\n{stderr}\n"
            if process.returncode != 0:
                output += f"\n[Exit code: {process.returncode}]"
            return output.strip() or "(no output)"
        finally:
            sb.terminate()

    # Keep this return at the factory level, outside run_python().
    # The deployed Modal service must receive the FastMCP instance.
    return mcp


@app.function(image=image, timeout=600, secrets=[GOOGLE_DRIVE_SECRET])
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

    mcp_app = mcp.http_app(
        transport="streamable-http",
        stateless_http=True,
    )

    fastapi_app = FastAPI(
        lifespan=mcp_app.router.lifespan_context
    )
    fastapi_app.mount("/", mcp_app)

    return fastapi_app
