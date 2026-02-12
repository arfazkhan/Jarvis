"""
Interactive Feedback Loop
=========================

Facilitates active learning by soliciting operator feedback.
Identifies high-uncertainty scenarios and asks targeted questions.

Capabilities:
1. Identify when to ask for feedback (Active Learning).
2. Generate specific questions (e.g., "Why did you choose X over Y?").
3. Process and store feedback for model retraining.
"""

import logging
import uuid
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime

from agent_advisory.recommendation_tracker import RecommendationTracker
from agent_advisory.schemas import Recommendation, RecommendationStatus

logger = logging.getLogger("arvis.advisory.feedback")

@dataclass
class FeedbackRequest:
    """A request for operator feedback"""
    request_id: str
    recommendation_id: str
    question_type: str  # "choice_rationale", "outcome_verification", "general_feedback"
    question_text: str
    options: Optional[List[str]] = None
    created_at: datetime = field(default_factory=datetime.now)
    answered: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "recommendation_id": self.recommendation_id,
            "question_type": self.question_type,
            "question_text": self.question_text,
            "options": self.options,
            "created_at": self.created_at.isoformat(),
            "answered": self.answered
        }

@dataclass
class FeedbackResponse:
    """Operator's response to a feedback request"""
    request_id: str
    operator_id: str
    response_text: str
    selected_option: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "operator_id": self.operator_id,
            "response_text": self.response_text,
            "selected_option": self.selected_option,
            "timestamp": self.timestamp.isoformat()
        }

class ActiveLearner:
    """
    Manages active learning strategies.
    Decides when and what to ask.
    """
    
    def __init__(self, tracker: RecommendationTracker):
        self.tracker = tracker
        self.pending_requests: Dict[str, FeedbackRequest] = {}
        self.llm_provider = None
        
    async def check_for_feedback_opportunities(self, window_hours: int = 24) -> List[FeedbackRequest]:
        """
        Scan recent recommendations for learning opportunities.
        
        Strategies:
        1. Disagreement: Operator rejected recommendation (High Priority).
        2. Uncertainty: Model was unsure (<60% confidence).
        3. Novelty: New scenario encountered.
        """
        requests = []
        
        # Get recent recommendations
        # (Assuming tracker has filtering by time, using raw method for now)
        recs = self.tracker.get_recent_recommendations(window_days=1)
        
        for rec in recs:
            # Avoid duplicate requests
            if self._feedback_requested(rec.id):
                continue
                
            # STRATEGY 1: Disagreement (Rejection/Modification)
            if rec.status in [RecommendationStatus.REJECTED, RecommendationStatus.MODIFIED]:
                req = await self._create_disagreement_request(rec)
                requests.append(req)
                self.pending_requests[req.request_id] = req
                
            # STRATEGY 2: Low Confidence Acceptance (Verification)
            elif rec.status == RecommendationStatus.ACCEPTED and rec.confidence < 0.6:
                req = self._create_verification_request(rec)
                requests.append(req)
                self.pending_requests[req.request_id] = req
                
        return requests

    def set_llm_provider(self, provider: Any) -> None:
        """Set LLM provider for curiosity generation."""
        self.llm_provider = provider

    async def _generate_curiosity_question(self, context: Dict[str, Any], decision: str) -> str:
        """Generate a curious question about the operator's decision using LLM."""
        if not hasattr(self, 'llm_provider') or not self.llm_provider:
            return "Could you explain your decision?"
            
        prompt = f"""
        The operator made a decision that surprised the system.
        Context: {str(context)[:200]}...
        Decision: {decision}
        
        Generate a polite, 1-sentence question to understand their reasoning.
        Example: "I noticed you chose X instead of Y; was specific factor Z involved?"
        """
        try:
            response = await self.llm_provider.chat([{"role": "user", "content": prompt}])
            return response.content.strip().replace('"', '')
        except Exception:
            return "Could you explain the reasoning behind this choice?"

    async def _create_disagreement_request(self, rec: Recommendation) -> FeedbackRequest:
        """Create request for when operator disagrees."""
        question = "We noticed you adjusted our recommendation. What was the key factor?"
        
        # Smart upgrade
        if hasattr(self, 'llm_provider') and self.llm_provider:
            question = await self._generate_curiosity_question(
                rec.context, 
                f"Rejected {rec.recommended_action} (Status: {rec.status})"
            )
            
        return FeedbackRequest(
            request_id=str(uuid.uuid4()),
            recommendation_id=rec.id,
            question_type="choice_rationale",
            question_text=question,
            options=["Simpler", "Safety Concern", "Cost", "Comfort Complaint", "Other"]
        )

    def _create_verification_request(self, rec: Recommendation) -> FeedbackRequest:
        """Create verification request for low confidence acceptance."""
        return FeedbackRequest(
            request_id=str(uuid.uuid4()),
            recommendation_id=rec.id,
            question_type="outcome_verification",
            question_text=f"We were unsure about '{rec.recommended_action}'. Did it work as expected?",
            options=["Yes, worked well", "Worked but needs tuning", "No, caused issues"]
        )
                
        return requests
        
    def process_feedback(self, response: FeedbackResponse):
        """Process received feedback"""
        req = self.pending_requests.get(response.request_id)
        if not req:
            logger.warning(f"Received feedback for unknown request {response.request_id}")
            return
            
        logger.info(f"Processing feedback from {response.operator_id}: {response.response_text}")
        
        # In a real system:
        # 1. Update Recommendation/Outcome in DB
        # 2. Store specific feedback for "Preference Learning" dataset
        # 3. Trigger retrain if enough feedback collected
        
        # Mark as answered
        req.answered = True
        # (Could move to 'archived_requests' or simpler cleanup)
        


        
    def _feedback_requested(self, rec_id: str) -> bool:
        """Check if we already asked about this recommendation"""
        # Linear scan for demo; optimizing would use a set or DB index
        for req in self.pending_requests.values():
            if req.recommendation_id == rec_id:
                return True
        return False
