.PHONY: test run webui clean help

help:
	@echo "Tain Agent Framework"
	@echo ""
	@echo "  make test      Run all tests"
	@echo "  make run       Start an agent (NAME=agent_name)"
	@echo "  make webui     Start the Web UI (PORT=8000)"
	@echo "  make clean     Remove __pycache__ and .pytest_cache"

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
