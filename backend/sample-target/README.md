# sample-target — intentionally vulnerable corpus

A small, **deliberately insecure** code corpus bundled into the AgentCore container as the
default scan target (`/app/sample-target`). It exists solely to exercise the FSI-Mythos
pipeline end-to-end and to demo findings. **Never deploy or import this code.**

| File | Language | CWE | Issue |
|------|----------|-----|-------|
| `transfer.c` | C | CWE-120 / CWE-787 / CWE-78 | strcpy overflow, sprintf OOB write, `system` command injection |
| `auth.py` | Python | CWE-347 | JWT signature verification disabled |
| `queries.py` | Python | CWE-89 | SQL injection via string formatting |
| `files.py` | Python | CWE-22 | path traversal on statement filename |
| `crypto.py` | Python | CWE-327 | weak hash (MD5) for PIN |
| `serial.py` | Python | CWE-502 | `pickle.loads` of untrusted data |
| `render.js` | JavaScript | CWE-79 | DOM XSS via `innerHTML` |

Phase 1 (sink-guided slicing) flags the command/buffer/deserialization/DOM sinks directly;
the remaining CWEs (SQLi, path traversal, weak crypto, JWT bypass) are caught by the Hunter
agent's semantic reasoning.
