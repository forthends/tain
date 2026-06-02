.PHONY: test run webui clean tain

# When `tain` (or `tain-*`) is the goal, suppress the normal `help` target so
# `make tain help` only invokes ./tain (not also the Makefile's own help).
ifeq ($(filter tain tain-%,$(MAKECMDGOALS)),)
.PHONY: help
help:
	@echo "Tain Agent Framework"
	@echo ""
	@echo "  make test         Run all tests"
	@echo "  make run          Start an agent (NAME=agent_name)"
	@echo "  make webui        Start the Web UI (PORT=8000)"
	@echo "  make clean        Remove __pycache__ and .pytest_cache"
	@echo "  make tain <cmd>   Forward to ./tain (e.g. make tain help, make tain list)"
endif

test:
	python -m pytest tests/ -v

run:
	@if [ -z "$(NAME)" ]; then \
		echo "Usage: make run NAME=<agent_name>"; \
		exit 1; \
	fi
	python main.py --agent $(NAME)

webui:
	python main.py --webui --port $(or $(PORT),8000)

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true

# ─── Tain launcher forwarding ─────────────────────────────────────────────
# Allows `make tain help`, `make tain run poet`, `make tain-run NAME=poet`, etc.
# Extra positional goals (e.g. `help`, `list`, `poet`) get turned into no-ops
# below so Make doesn't try to build them as targets.

tain:
	@./tain $(filter-out $@,$(MAKECMDGOALS))

tain-%:
	@./tain $(subst tain-,,$@) $(filter-out $@,$(MAKECMDGOALS))

ifneq ($(filter tain tain-%,$(MAKECMDGOALS)),)
EXTRA_TAIN_ARGS := $(filter-out tain tain-%,$(MAKECMDGOALS))
ifneq ($(EXTRA_TAIN_ARGS),)
$(EXTRA_TAIN_ARGS):
	@:
endif
endif
