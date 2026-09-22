import modal
from typing import Optional, List

app = modal.App("dynamic-python-mcp")

# Base image for the MCP server itself
image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install(
        "fastapi==0.115.14",
        "fastmcp==2.12.0",
        "pydantic>=2.0",
    )
)


def make_mcp_server():
    from fastmcp import FastMCP

    mcp = FastMCP("Dynamic Python MCP (with pip install + H100)")

    @mcp.tool()
    async def run_python(
        code: str,
        packages: Optional[List[str]] = None,
        timeout_seconds: int = 300,
        python_version: str = "3.12",
        gpu: Optional[str] = None,
    ) -> str:
        """
        Run arbitrary Python code in a secure Modal Sandbox.
        Supports dynamic package installation and optional GPU (including H100).

        Args:
            code: The Python code to execute
            packages: List of packages to install (e.g. ["torch", "transformers", "boto3"])
            timeout_seconds: Max runtime in seconds (default 300)
            python_version: Python version to use (default "3.12")
            gpu: GPU type. Options: "T4", "L4", "A10G", "A100", "H100" (or None for CPU)

        Returns:
            stdout + stderr from the execution
        """
        import modal

        packages = packages or []

        # Create image with requested packages
        sandbox_image = modal.Image.debian_slim(python_version=python_version)
        if packages:
            sandbox_image = sandbox_image.pip_install(*packages)

        # GPU mapping
        gpu_config = None
        if gpu:
            gpu = gpu.upper().strip()
            if gpu in ["H100", "H100!"]:
                gpu_config = "H100"
            elif gpu in ["A100", "A100-80GB"]:
                gpu_config = "A100"
            elif gpu in ["A10G", "A10"]:
                gpu_config = "A10G"
            elif gpu in ["L4"]:
                gpu_config = "L4"
            elif gpu in ["T4"]:
                gpu_config = "T4"
            else:
                return f"Unsupported GPU: {gpu}. Supported: T4, L4, A10G, A100, H100"

        # Create Sandbox (no context manager - not supported)
        sandbox_kwargs = {
            "image": sandbox_image,
            "timeout": timeout_seconds,
            "app": app,
        }
        if gpu_config:
            sandbox_kwargs["gpu"] = gpu_config

        sb = modal.Sandbox.create(**sandbox_kwargs)
        try:
            process = sb.exec("python", "-c", code)
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

    return mcp


@app.function(image=image, timeout=600)
@modal.asgi_app()
def web():
    """MCP Server endpoint (Streamable HTTP)"""
    from fastapi import FastAPI

    mcp = make_mcp_server()
    mcp_app = mcp.http_app(transport="streamable-http", stateless_http=True)

    fastapi_app = FastAPI(lifespan=mcp_app.router.lifespan_context)
    fastapi_app.mount("/", mcp_app)

    return fastapi_app
