from tain_agent.mcp.middleware import ProductionGateMiddleware, RateLimiter

class TestProductionGateMiddleware:
    def test_allows_production_ready(self):
        assert ProductionGateMiddleware().check({"status":"production_ready","stable_streak":3}) is True
    def test_rejects_non_ready(self):
        assert ProductionGateMiddleware().check({"status":"not_ready"}) is False
    def test_rejects_stabilizing(self):
        assert ProductionGateMiddleware().check({"status":"stabilizing"}) is False

class TestRateLimiter:
    def test_allows_under_limit(self):
        assert RateLimiter(max_per_minute=60).allow("tools/call") is True
    def test_blocks_over_limit(self):
        rl = RateLimiter(max_per_minute=2)
        for _ in range(2): rl.allow("tools/call")
        assert rl.allow("tools/call") is False
    def test_independent_endpoints(self):
        rl = RateLimiter(max_per_minute=2)
        for _ in range(2): rl.allow("tools/call")
        assert rl.allow("resources/read") is True
