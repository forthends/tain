# Contributing to Tain Agent Framework

## Getting Started

1. Fork the repository and clone it locally.
2. Create a virtual environment:
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -e ".[dev]"
   ```
3. Run the test suite to confirm everything works:
   ```bash
   pytest tests/ -q
   ```

## Development Workflow

1. Create a branch from `dev` for your changes.
2. Make your changes, following existing code patterns.
3. Add tests for new functionality.
4. Run the full test suite: `pytest tests/ -q`
5. Submit a pull request to the `dev` branch.

## Code Style

- Follow PEP 8 conventions.
- Use `logging` module for all log output — no `print()` statements.
- Keep methods focused and files reasonably sized.
- Prefer composition over deep inheritance.
- Write docstrings for public APIs.

## Testing

- Unit tests go in `tests/` with the pattern `test_<module>.py`.
- Run before submitting: `pytest tests/ -q --tb=short`

## Commit Messages

Use conventional commit prefixes:

- `feat:` — new feature
- `fix:` — bug fix
- `refactor:` — code change that neither fixes a bug nor adds a feature
- `test:` — adding or updating tests
- `docs:` — documentation changes
- `chore:` — maintenance tasks (dependency updates, cleanup)

## Architecture

See [docs/architecture.md](docs/architecture.md) for the full system design.

## Questions?

Open an issue with a clear description of your question.
