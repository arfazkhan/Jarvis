import json
import csv
import logging
import io
from datetime import datetime
from typing import Dict, Any, List, Optional
from agent_commercial.gsas_reporter import GSASReporter, GSASCategory, CriterionStatus

logger = logging.getLogger("arvis.bms.gsas.exporter")

class GSASgateExporter:
    """
    Exporter for GSASgate (GORD Portal) compatibility.
    
    Transforms GSASReporter data into structured formats (JSON/CSV)
    required for official certification submission.
    """
    
    def __init__(self, reporter: GSASReporter):
        self.reporter = reporter
        self.building_id = reporter.building_id
        self.building_name = reporter.building_name
        
    def export_json(self) -> str:
        """
        Export assessment data as a GSASgate-compliant JSON string.
        """
        status = self.reporter.get_status()
        
        # GSASgate Schema v1.2 (Simulated)
        export_data = {
            "metadata": {
                "portal": "GSASgate-OPS",
                "version": "1.2",
                "export_timestamp": datetime.now().isoformat(),
                "building": {
                    "id": self.building_id,
                    "name": self.building_name,
                    "location": "Qatar",
                    "type": "Commercial"
                }
            },
            "assessment": {
                "overall_score": status["overall_score"],
                "star_rating": status["star_rating"],
                "total_criteria_measured": len(self.reporter.criteria),
                "last_assessment_date": datetime.now().strftime("%Y-%m-%d")
            },
            "categories": [],
            "criteria_details": []
        }
        
        # Add Categories
        for cat_id, cat_data in status["categories"].items():
            export_data["categories"].append({
                "category_id": cat_id,
                "score_percent": cat_data["percentage"],
                "points_achieved": cat_data["achieved_points"],
                "weight": self.reporter.CATEGORY_WEIGHTS.get(GSASCategory(cat_id), 0.0)
            })
            
        # Add Detailed Criteria
        for crit_id, crit in self.reporter.criteria.items():
            export_data["criteria_details"].append({
                "id": crit_id,
                "name": crit.name,
                "category": crit.category.value,
                "points": crit.current_points,
                "max_points": crit.max_points,
                "status": crit.status.value,
                "is_bms_verified": crit.is_bms_measurable,
                "evidence_count": len(crit.evidence)
            })
            
        return json.dumps(export_data, indent=2)

    def export_csv(self) -> str:
        """
        Export criteria-level scoring as a CSV string.
        """
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow([
            "Criterion ID", "Name", "Category", "Points Achieved", 
            "Max Points", "Status", "BMS Verified", "Last Updated"
        ])
        
        # Rows
        for crit_id, crit in self.reporter.criteria.items():
            writer.writerow([
                crit_id,
                crit.name,
                crit.category.value,
                crit.current_points,
                crit.max_points,
                crit.status.value,
                "Yes" if crit.is_bms_measurable else "No",
                crit.last_updated.isoformat()
            ])
            
        return output.getvalue()

    def save_to_file(self, filename: str, format: str = "json") -> str:
        """
        Save the export to a local file.
        """
        import os
        
        # Ensure exports directory exists
        os.makedirs("exports/gsasgate", exist_ok=True)
        
        filepath = os.path.join("exports/gsasgate", filename)
        
        content = ""
        if format.lower() == "json":
            content = self.export_json()
        elif format.lower() == "csv":
            content = self.export_csv()
        else:
            raise ValueError(f"Unsupported export format: {format}")
            
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
            
        logger.info(f"GSAS assessment exported to {filepath}")
        return filepath
