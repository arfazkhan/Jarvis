"""
GSAS Approval Workflow
======================

Manages the lifecycle of GSAS certification packages:
Draft -> Pending Review -> Approved/Rejected.

Ensures human-in-the-loop (HITL) accountability for GORD submissions.
"""

import logging
import uuid
import json
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
from enum import Enum

logger = logging.getLogger("arvis.gsas.approval")

class PackageStatus(str, Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    SUBMITTED = "submitted"
    REJECTED = "rejected"

@dataclass
class Anomaly:
    """A flagged issue in the GSAS data requiring CSP attention."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    criterion_id: str = ""
    description: str = ""
    severity: str = "medium"  # low, medium, high, critical
    detected_at: datetime = field(default_factory=datetime.now)
    resolution: Optional[str] = None
    resolved_at: Optional[datetime] = None

@dataclass
class GSASSubmissionPackage:
    """A frozen snapshot of GSAS data awaiting CSP review."""
    package_id: str = field(default_factory=lambda: f"PKG-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:4].upper()}")
    building_id: str = ""
    status: PackageStatus = PackageStatus.DRAFT
    created_at: datetime = field(default_factory=datetime.now)
    created_by: str = "ARVIS_AI"
    reviewed_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    
    # Frozen data snapshot
    gsas_status: Dict[str, Any] = field(default_factory=dict)
    export_json: str = ""  # The serialized GSASgate JSON
    export_filepath: Optional[str] = None
    
    # HITL Tracking
    anomalies: List[Anomaly] = field(default_factory=list)
    rejection_reason: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["created_at"] = self.created_at.isoformat()
        if self.approved_at:
            data["approved_at"] = self.approved_at.isoformat()
        if self.export_filepath:
            data["export_filepath"] = self.export_filepath
        for i, anomaly in enumerate(data["anomalies"]):
            data["anomalies"][i]["detected_at"] = self.anomalies[i].detected_at.isoformat()
            if self.anomalies[i].resolved_at:
                data["anomalies"][i]["resolved_at"] = self.anomalies[i].resolved_at.isoformat()
        return data

class GSASApprovalWorkflow:
    """Orchestrates the CSP review and approval process."""
    
    def __init__(self):
        self.packages: Dict[str, GSASSubmissionPackage] = {}

    def create_package(self, reporter, exporter) -> GSASSubmissionPackage:
        """Create a new frozen snapshot for review."""
        status = reporter.get_status()
        export_data = exporter.export_json()
        
        package = GSASSubmissionPackage(
            building_id=reporter.building_id,
            gsas_status=status,
            export_json=export_data
        )
        
        # Auto-detect anomalies
        self._detect_anomalies(package, reporter)
        
        if package.anomalies:
            package.status = PackageStatus.PENDING_REVIEW
        
        self.packages[package.package_id] = package
        logger.info(f"Created GSAS submission package {package.package_id} with {len(package.anomalies)} anomalies")
        return package

    def _detect_anomalies(self, package: GSASSubmissionPackage, reporter) -> None:
        """Internal logic to flag data issues."""
        anomalies = []
        
        for cat_id in ["E", "W"]:
            cat_score = package.gsas_status["categories"].get(cat_id, {})
            score = cat_score.get("achieved_points", 3.0) # Using achieved points for logic
            if score <= 0.3:
                anomalies.append(Anomaly(
                    criterion_id=cat_id,
                    description=f"{cat_id} score is {score:.2f}, dangerously close to disqualification floor (0.0).",
                    severity="high"
                ))
        
        # 2. Data Gaps (BMS-measurable but NOT_STARTED)
        for crit_id, crit in reporter.criteria.items():
            if crit.is_bms_measurable and crit.status.value == "not_started":
                anomalies.append(Anomaly(
                    criterion_id=crit_id,
                    description=f"Criterion {crit_id} is BMS-measurable but has no data ingested.",
                    severity="medium"
                ))
                
        # 3. Overall Performance
        if package.gsas_status["overall_score"] < 1.0:
            anomalies.append(Anomaly(
                criterion_id="OVERALL",
                description="Overall building score is below 1.0. High risk of 1-Star or below.",
                severity="medium"
            ))

        package.anomalies = anomalies

    def resolve_anomaly(self, package_id: str, anomaly_id: str, resolution: str) -> bool:
        """Mark an anomaly as resolved by the CSP."""
        package = self.packages.get(package_id)
        if not package:
            return False
            
        for anomaly in package.anomalies:
            if anomaly.id == anomaly_id:
                anomaly.resolution = resolution
                anomaly.resolved_at = datetime.now()
                logger.info(f"Anomaly {anomaly_id} resolved in package {package_id}")
                return True
        return False

    def approve_package(self, package_id: str, operator_id: str) -> Dict[str, Any]:
        """Final approval gate."""
        package = self.packages.get(package_id)
        if not package:
            return {"status": "error", "message": "Package not found"}
            
        # Check if all anomalies are resolved
        unresolved = [a for a in package.anomalies if not a.resolution]
        if unresolved:
            return {
                "status": "error", 
                "message": f"Cannot approve: {len(unresolved)} unresolved anomalies remain",
                "unresolved_ids": [a.id for a in unresolved]
            }
            
        package.status = PackageStatus.APPROVED
        package.reviewed_by = operator_id
        package.approved_at = datetime.now()
        
        # Auto-export on approval
        import os
        os.makedirs("exports/gsasgate", exist_ok=True)
        filename = f"exports/gsasgate/{package_id}.json"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(package.export_json)
        package.export_filepath = filename
        
        logger.info(f"Package {package_id} APPROVED by {operator_id}. Exported to {filename}")
        return {"status": "success", "package_id": package_id, "export_filepath": filename}

    def reject_package(self, package_id: str, operator_id: str, reason: str) -> bool:
        """Reject and request corrections."""
        package = self.packages.get(package_id)
        if not package:
            return False
            
        package.status = PackageStatus.REJECTED
        package.reviewed_by = operator_id
        package.rejection_reason = reason
        
        logger.info(f"Package {package_id} REJECTED by {operator_id}: {reason}")
        return True

    def get_package(self, package_id: str) -> Optional[GSASSubmissionPackage]:
        return self.packages.get(package_id)

    def list_packages(self) -> List[GSASSubmissionPackage]:
        return list(self.packages.values())
