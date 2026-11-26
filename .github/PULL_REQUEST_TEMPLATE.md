## Summary
Briefly describe the changes and why they are needed.

## Checklist
- [ ] `uv run ruff check .` passes without errors
- [ ] `QT_QPA_PLATFORM=offscreen uv run pytest -v` passes
- [ ] Changes keep existing `~/.ssh/sshcnfgr.toml` / `hosts.toml` files backward-compatible
- [ ] No private SSH key contents are read or stored
- [ ] Documentation (`README.md` / `CHANGELOG.md`) updated if user-facing behavior changed
