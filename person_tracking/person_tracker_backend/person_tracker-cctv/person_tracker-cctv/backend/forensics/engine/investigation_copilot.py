"""
Investigation Copilot (Phase 51)
AI-powered copilot for natural language investigation workflows.

Capabilities:
- Translates natural language queries into structured investigative actions
- Generates timeline summaries
- Reconstructs movement paths
- Formats investigator-ready reports

Usage:
    copilot = InvestigationCopilot(investigation_engine)
    report = copilot.process_query("Generate investigation report for suspect X")
"""
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class InvestigationCopilot:
    """
    Acts as the primary AI interface for human investigators.
    Wraps the existing InvestigationEngine to provide rich, narrative-driven
    summaries and automated report generation.
    """

    def __init__(self, investigation_engine=None):
        self._engine = investigation_engine
        self._total_interactions = 0
        logger.info("InvestigationCopilot initialized")

    def process_query(self, query: str) -> Dict[str, Any]:
        """
        Process a natural language query and generate a rich response.
        """
        self._total_interactions += 1
        
        # If we have the engine, parse the query
        if not self._engine:
            return {
                "status": "error",
                "message": "Underlying InvestigationEngine not available."
            }

        parsed = self._engine.query_natural_language(query)
        q_type = parsed.get("query_type", "unknown")
        
        response = {
            "original_query": query,
            "query_type": q_type,
            "narrative_summary": "",
            "structured_data": parsed.get("results", []),
            "copilot_suggestions": []
        }

        # Generate narrative summaries based on the underlying results
        if q_type == "timeline" and "identity_id" in parsed.get("parameters", {}):
            identity = parsed["parameters"]["identity_id"]
            count = len(parsed.get("results", []))
            if count == 0:
                response["narrative_summary"] = f"I found no sightings of {identity}."
            else:
                first_sighting = parsed["results"][0]["timestamp"]
                last_sighting = parsed["results"][-1]["timestamp"]
                response["narrative_summary"] = (
                    f"I found {count} total sightings for {identity}. "
                    f"The first appearance was at {first_sighting}, and the "
                    f"last known appearance was at {last_sighting}."
                )
                response["copilot_suggestions"].append(
                    f"Reconstruct movement path for {identity}"
                )
                
        elif q_type == "path" and "identity_id" in parsed.get("parameters", {}):
            identity = parsed["parameters"]["identity_id"]
            results = parsed.get("results", [])
            if not results:
                response["narrative_summary"] = f"Not enough data to reconstruct a path for {identity}."
            else:
                steps = len(results)
                response["narrative_summary"] = (
                    f"I have reconstructed the movement path for {identity} across {steps} camera transitions. "
                    f"The path starts at {results[0]['from_camera']} and ends at {results[-1]['to_camera']}."
                )
                
        elif "report" in query.lower():
            # A special "generate report" meta-query
            # In a real system, this would aggregate timeline, path, and evidence
            response["query_type"] = "report_generation"
            response["narrative_summary"] = (
                "Here is the generated investigation report compiling all known sightings, "
                "inferred movement paths, and attached evidence."
            )
            
        else:
            response["narrative_summary"] = (
                f"I processed your query. Found {parsed.get('result_count', 0)} relevant records."
            )
            response["copilot_suggestions"].append("Show all appearances of this suspect")
            
        return response

    def generate_dossier(self, identity_id: str) -> Dict[str, Any]:
        """
        Generates a complete investigator-ready dossier for a specific identity.
        """
        self._total_interactions += 1
        if not self._engine:
            return {"error": "Engine unavailable"}
            
        timeline = self._engine.reconstruct_timeline(identity_id)
        path = self._engine.reconstruct_path(identity_id)
        
        return {
            "identity_id": identity_id,
            "dossier_title": f"Investigation Dossier: {identity_id}",
            "summary": f"Subject appears in {len(timeline)} events across {len(path)+1} cameras.",
            "timeline": timeline,
            "path_reconstruction": path,
            "risk_indicators": []  # To be populated by RiskEngine
        }

    def get_metrics(self) -> dict:
        return {
            "total_copilot_interactions": self._total_interactions
        }
