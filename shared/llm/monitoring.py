"""
Monitoring and cost tracking for LLM providers.
Tracks usage, performance, and costs across different providers.
"""

from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from collections import defaultdict
import json
from pathlib import Path


class MetricsCollector:
    """Collects metrics for LLM provider usage"""
    
    def __init__(self):
        self.requests = defaultdict(int)
        self.successes = defaultdict(int)
        self.failures = defaultdict(lambda: defaultdict(int))
        self.latencies = defaultdict(list)
        self.start_time = datetime.now()
    
    def record_request(self, provider: str):
        """Record a request attempt"""
        self.requests[provider] += 1
    
    def record_success(self, provider: str, duration: float):
        """Record successful request"""
        self.successes[provider] += 1
        self.latencies[provider].append(duration)
    
    def record_failure(self, provider: str, error: str):
        """Record failed request"""
        self.failures[provider][error] += 1
    
    def get_summary(self) -> Dict[str, Any]:
        """Get metrics summary"""
        uptime = (datetime.now() - self.start_time).total_seconds()
        
        summary = {
            "uptime_seconds": uptime,
            "providers": {}
        }
        
        for provider in self.requests.keys():
            total = self.requests[provider]
            success = self.successes[provider]
            
            provider_stats = {
                "total_requests": total,
                "successful_requests": success,
                "failed_requests": total - success,
                "success_rate": (success / total * 100) if total > 0 else 0,
                "failures_by_error": dict(self.failures[provider])
            }
            
            if self.latencies[provider]:
                latencies = self.latencies[provider]
                provider_stats["latency"] = {
                    "mean": sum(latencies) / len(latencies),
                    "min": min(latencies),
                    "max": max(latencies),
                    "p50": sorted(latencies)[len(latencies) // 2],
                    "p95": sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) > 20 else max(latencies)
                }
            
            summary["providers"][provider] = provider_stats
        
        return summary


class CostTracker:
    """Tracks costs for LLM usage"""
    
    def __init__(self, budget_limit: Optional[float] = None):
        self.costs_by_provider = defaultdict(float)
        self.costs_by_hour = defaultdict(lambda: defaultdict(float))
        self.budget_limit = budget_limit
        self.start_time = datetime.now()
    
    def record_cost(self, provider: str, cost: float):
        """Record cost for a request"""
        self.costs_by_provider[provider] += cost
        
        hour_key = datetime.now().strftime("%Y-%m-%d %H:00")
        self.costs_by_hour[hour_key][provider] += cost
        
        # Check budget
        if self.budget_limit:
            total = sum(self.costs_by_provider.values())
            if total > self.budget_limit:
                raise Exception(f"Budget limit exceeded: ${total:.2f} > ${self.budget_limit:.2f}")
    
    def get_summary(self) -> Dict[str, Any]:
        """Get cost summary"""
        total_cost = sum(self.costs_by_provider.values())
        
        return {
            "total_cost": total_cost,
            "cost_by_provider": dict(self.costs_by_provider),
            "cost_by_hour": dict(self.costs_by_hour),
            "budget_limit": self.budget_limit,
            "budget_remaining": self.budget_limit - total_cost if self.budget_limit else None,
            "average_cost_per_hour": total_cost / max(1, (datetime.now() - self.start_time).total_seconds() / 3600)
        }
    
    def export_to_file(self, filepath: str):
        """Export cost data to JSON file"""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w') as f:
            json.dump(self.get_summary(), f, indent=2, default=str)