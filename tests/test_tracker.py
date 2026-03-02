"""Tests for usage tracker."""


from claw_forge.pool.tracker import UsageTracker


class TestUsageTracker:
    def test_empty_stats(self):
        t = UsageTracker()
        assert t.get_all_stats() == {}

    def test_record_request(self):
        t = UsageTracker()
        t.record_request("p1", 100, 50, 3.0, 15.0, 200.0)
        stats = t.get_stats("p1")
        assert stats.total_requests == 1
        assert stats.total_input_tokens == 100
        assert stats.total_output_tokens == 50
        assert stats.avg_latency_ms == 200.0

    def test_cost_calculation(self):
        t = UsageTracker()
        # 1M input tokens at $3/Mtok = $3, 1M output at $15/Mtok = $15
        t.record_request("p1", 1_000_000, 1_000_000, 3.0, 15.0, 100.0)
        stats = t.get_stats("p1")
        assert abs(stats.total_cost_usd - 18.0) < 0.01

    def test_rate_limiting(self):
        t = UsageTracker()
        assert not t.is_rate_limited("p1", 60)
        for _ in range(60):
            t.record_request("p1", 10, 10, 1.0, 1.0, 10.0)
        assert t.is_rate_limited("p1", 60)

    def test_record_error(self):
        t = UsageTracker()
        t.record_error("p1")
        assert t.get_stats("p1").total_errors == 1

    def test_get_avg_latency_unknown(self):
        t = UsageTracker()
        assert t.get_avg_latency("unknown") == float("inf")

    def test_reset(self):
        t = UsageTracker()
        t.record_request("p1", 100, 50, 3.0, 15.0, 200.0)
        t.reset()
        assert t.get_all_stats() == {}

    def test_get_all_stats_format(self):
        t = UsageTracker()
        t.record_request("p1", 100, 50, 3.0, 15.0, 200.0)
        all_stats = t.get_all_stats()
        assert "p1" in all_stats
        assert "total_requests" in all_stats["p1"]
        assert "avg_latency_ms" in all_stats["p1"]
