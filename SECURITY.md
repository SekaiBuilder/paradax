# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use
[GitHub's private vulnerability reporting](https://github.com/SekaiBuilder/paradax/security/advisories/new)
with a description, steps to reproduce and the version (commit) you used.

## Security model

Paradax runs agents that can use real tools on your machine, so the boundaries matter:

- **Local only.** The API listens on `127.0.0.1` and rejects requests whose `Host` or `Origin` is not local (protects against CSRF and DNS rebinding from pages open in your browser).
- **Tools by contract.** An agent can only call the tools its contract declares and that the tool broker allows for the task type. Code-editing tools are confined to the Paradax folder.
- **Undo.** Before each project run, Paradax takes a git snapshot of its folder; the last run can be undone from the interface.
- **Human approval.** Skills and tools proposed by the ghost agent are staged and only applied after you approve them.
- **Quarantine.** Trained students with unexpected behavior are vetoed from production. Lab interviews are text only through local Ollama, with no tools, network or files, and their answers never enter a dataset.
- **Research is data, not instructions.** Web research has a fixed budget, uses a local SearXNG by default, and pages that try to inject instructions are discarded and flagged.

## Out of scope

Paradax is a single-user tool for your own machine. It is not designed to be exposed to a network or shared between users.
Models can still produce wrong or unsafe text; the checks reduce that risk, they do not remove it.
