---
name: Bug Report
about: Something isn't working — please include the debug bundle below
title: "[BUG] "
labels: bug
assignees: ''

---

## What happened?
<!-- A clear description of the bug. What did you do, what did you expect, what actually happened? -->

## Steps to reproduce
1. 
2. 
3. 

## Debug bundle

**Run this and paste the output** — it answers most questions before we have to ask:

```bash
curl -s http://localhost:8000/api/support-info | python3 -m json.tool
```

<details>
<summary>Support info output (paste here)</summary>

```json

```

</details>

**Backend logs (last 50 lines):**

```bash
# Docker Compose
docker compose logs backend --tail 50

# systemd
journalctl -u memar.service -n 50 --no-pager
```

<details>
<summary>Log output (paste here)</summary>

```

```

</details>

## Environment

| Field | Value |
|---|---|
| **Deployment method** | Docker Compose / systemd / Kubernetes |
| **OS / distro** | e.g. Ubuntu 24.04, NixOS 25.11 |
| **MEMAR version** | shown in healthz `version` field |
| **Browser** (UI bugs only) | e.g. Chrome 125 |
| **Machine type triggering issue** | e.g. Klipper, OPC-UA, GRBL |

## Checklist
- [ ] Searched existing issues for duplicates
- [ ] Reproduced consistently (not a one-off)
- [ ] Included healthz output above
- [ ] Included log tail above
