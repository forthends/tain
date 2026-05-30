"""Smoke tests for Web UI routes."""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from webui.app import create_app
    app = create_app()
    return TestClient(app)


class TestDashboardRoutes:
    def test_dashboard_returns_200(self, client):
        with patch('webui.routes.pages.list_agents', return_value=[]), \
             patch('webui.routes.pages.get_config', return_value={'framework': {'version': '0.5.0'}}):
            response = client.get("/")
            assert response.status_code == 200

    def test_dashboard_includes_framework_name(self, client):
        with patch('webui.routes.pages.list_agents', return_value=[]), \
             patch('webui.routes.pages.get_config', return_value={'framework': {'version': '0.5.0'}}):
            response = client.get("/")
            assert "Tain" in response.text or "tain" in response.text.lower()


class TestCreateAgentRoute:
    def test_create_page_returns_200(self, client):
        with patch('webui.routes.pages.list_agents', return_value=[]), \
             patch('webui.routes.pages.get_config', return_value={}):
            response = client.get("/create")
            assert response.status_code == 200


class TestAgentDetailRoute:
    def test_agent_detail_handles_missing_agent(self, client):
        with patch('webui.routes.pages.get_agent', return_value=None), \
             patch('webui.routes.pages.list_agents', return_value=[]), \
             patch('webui.routes.pages.get_config', return_value={}):
            response = client.get("/agent/nonexistent_agent_12345")
            assert response.status_code in (200, 404)


class TestKnowledgeRoute:
    def test_knowledge_rejects_path_traversal(self, client):
        """Verify C3 fix: path traversal is blocked."""
        response = client.get(
            "/api/agent/default/knowledge/content",
            params={"path": "../../../etc/passwd"}
        )
        assert response.status_code in (200, 403, 404)
        if response.status_code == 200:
            data = response.json()
            content = data.get("content", "")
            assert "root:" not in content


class TestSettingsRoute:
    def test_settings_page_returns_200(self, client):
        with patch('webui.routes.pages.list_agents', return_value=[]), \
             patch('webui.routes.pages.get_config', return_value={}):
            response = client.get("/settings")
            assert response.status_code == 200
