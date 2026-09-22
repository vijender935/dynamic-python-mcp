# Dynamic Python MCP

Modal-based MCP server with:

- **Dynamic `pip install`** support
- **H100 / A100 / A10G / L4 / T4** GPU support
- Single tool: `run_python`

## Deploy

```bash
modal deploy modal_dynamic_mcp.py
```

After deploy, connect the URL (with `/mcp/`) as a **Streamable HTTP** MCP server.

## Tool: `run_python`

| Parameter | Type | Description |
|-----------|------|-------------|
| `code` | string | Python code to run |
| `packages` | list[str] | Packages to install dynamically |
| `timeout_seconds` | int | Timeout (default 300) |
| `python_version` | str | Python version (default "3.12") |
| `gpu` | str | `"H100"`, `"A100"`, `"A10G"`, `"L4"`, `"T4"` or omit for CPU |

### Example

```python
run_python(
    code="import torch; print(torch.cuda.get_device_name(0))",
    packages=["torch"],
    gpu="H100"
)
```
