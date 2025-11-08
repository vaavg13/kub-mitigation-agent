#!/usr/bin/env python3
"""
Unified cleanup operations for all anomaly types.

This module provides a single entry point for cleaning up all anomalies
across the system, regardless of type (node, pod, service, etc.).
"""

from typing import Dict, Any, List, Optional
from .node_anomaly_handler import NodeAnomalyHandler
from .pod_anomaly_handler import PodAnomalyHandler


def cleanup_all_anomalies(
    namespaces: Optional[List[str]] = None,
    nodes: Optional[Dict[str, str]] = None,
    chaosd_port: int = 31767
) -> Dict[str, Any]:
    """
    Stop ALL anomalies across the entire system in one call.
    
    This is the unified entry point for comprehensive anomaly cleanup.
    It delegates to each anomaly type's cleanup_all() method and aggregates results.
    
    Args:
        namespaces: List of namespaces to clean pod/service anomalies from
        nodes: Dict mapping node names to IP addresses for chaosd cleanup
        chaosd_port: Port for chaosd API (default: 31767)
        
    Returns:
        Dict with cleanup results:
        {
            "node_anomalies": {...},      # Results from NodeAnomalyHandler
            "pod_anomalies": {...},       # Results from PodAnomalyHandler
            "summary": {
                "total_cleaned": int,     # Total anomalies stopped
                "all_successful": bool    # True if no errors
            }
        }
        
    Example:
        >>> from kub_mitigation_agent.anomalies import cleanup_all_anomalies
        >>> results = cleanup_all_anomalies(
        ...     namespaces=["app-iot-gateway"],
        ...     nodes={"worker1": "192.168.1.10"},
        ...     chaosd_port=31767
        ... )
        >>> print(results["summary"]["total_cleaned"])
        5
    """
    results = {
        "node_anomalies": {},
        "pod_anomalies": {},
        "summary": {
            "total_cleaned": 0,
            "all_successful": True
        }
    }
    
    # 1. Clean node anomalies (chaosd)
    if nodes:
        try:
            node_result = NodeAnomalyHandler.cleanup_all(
                nodes=nodes,
                chaosd_port=chaosd_port
            )
            results["node_anomalies"] = node_result
            
            # Aggregate statistics
            total_deleted = sum(r.get("deleted", 0) for r in node_result.values())
            total_errors = sum(r.get("errors", 0) for r in node_result.values())
            
            results["summary"]["total_cleaned"] += total_deleted
            
            if total_errors > 0:
                results["summary"]["all_successful"] = False
                
        except Exception as e:
            results["node_anomalies"] = {"error": str(e)}
            results["summary"]["all_successful"] = False
    else:
        results["node_anomalies"] = {"skipped": True, "reason": "No nodes provided"}
    
    # 2. Clean pod/service anomalies (ChaosMesh CRDs)
    if namespaces:
        try:
            pod_result = PodAnomalyHandler.cleanup_all(namespaces=namespaces)
            results["pod_anomalies"] = pod_result
            
            # Check for failures (only count actual False values, not empty results)
            failed_namespaces = [ns for ns, success in pod_result.items() if success is False]
            if failed_namespaces:
                results["summary"]["all_successful"] = False
                results["summary"]["failed_namespaces"] = failed_namespaces
                
        except Exception as e:
            results["pod_anomalies"] = {"error": str(e)}
            results["summary"]["all_successful"] = False
    else:
        results["pod_anomalies"] = {"skipped": True, "reason": "No namespaces provided"}
    
    return results

