# Dynamic Python MCP

Modal-based MCP server jo Claude ko **kahin bhi Python code chalane** deta hai, dynamic `pip install` aur GPU ke saath.

## Features

- Single tool: `run_python`
- Dynamic `pip install` (har call pe fresh sandbox)
- GPU: `T4`, `L4`, `A10G`, `A100` (40GB), `A100-40GB`, `A100-80GB`, `L40S`, `H100`, `H100!`, `H200`, `B200`
- Do modes: `wait=True` (result turant) aur `wait=False` (fire-and-forget)
- Code khatam hote hi sandbox **apne aap band** hota hai (idle GPU ka bill nahi)
- Secret URL (token) + `max_containers` limit

## One-time setup

1. Modal secret **`google-drive`**: Drive credentials (sirf sandbox ko milta hai).
2. Modal secret **`mcp-auth`** with key `MCP_PATH_TOKEN` (16+ random chars):
   ```bash
   python -c "import secrets;print(secrets.token_urlsafe(24))"
   modal secret create mcp-auth MCP_PATH_TOKEN=<string>
   ```
   (Ya Modal dashboard > Secrets > Create new secret > Custom.)
3. GitHub repo secrets: `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`.

## Deploy

```bash
modal deploy modal_dynamic_mcp.py
```

`main` pe push karne par GitHub Actions bhi deploy karta hai (`.github/workflows/deploy.yml`).

## Connect

Claude mein **Streamable HTTP** MCP server ke roop mein ye URL add karo:

```
https://<workspace>--dynamic-python-mcp-web.modal.run/<MCP_PATH_TOKEN>/mcp
```

URL ko password ki tarah private rakho. Bina token ke `/mcp` 404 deta hai.

## Tool: `run_python`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `code` | string | required | Python code to run |
| `packages` | list[str] | none | Packages to `pip install` |
| `timeout_seconds` | int | 300 | Sandbox max life (min 10, max 86400). `wait=True` mein max 540 |
| `python_version` | str | "3.12" | Python version |
| `gpu` | str | CPU | See GPU list above |
| `wait` | bool | true | `false` = fire-and-forget |

### Modes

- **`wait=True`**: result wapas aata hai (STDOUT / STDERR / exit code). Chhote kaam ke liye.
- **`wait=False`**: turant `sandbox_id` milta hai, job background mein chalti hai, logs Modal dashboard pe. Lambe kaam ke liye.

### Limits

| Limit | Value |
|-------|-------|
| `wait=True` max time | 540s |
| Output | last 20,000 characters |
| Parallel containers | 5 |

Pehli baar bade packages (jaise `torch`) ka image build hota hai. Aisa kaam `wait=False` se chalao.

### Example

```python
run_python(
    code="import torch; print(torch.cuda.get_device_name(0))",
    packages=["torch"],
    gpu="H100",
    wait=False,
)
```
