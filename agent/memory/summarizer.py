"""
Memory Summarizer Utility
==========================
Converts raw observation records into structured "Trend Facts".
Helps the agent see long-horizon patterns (e.g., % increases) as explicit evidence.
"""

import re
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger("arvis.memory.summarizer")

class MemorySummarizer:
    @staticmethod
    def extract_numerical_trends(observations: List[Dict[str, Any]], field_patterns: Dict[str, str]) -> str:
        r"""
        Parses observations to find numerical trends based on regex patterns.
        
        Args:
            observations: List of observation records (dict with 'content' and 'timestamp')
            field_patterns: Map of field names to regex patterns (e.g., {"vibration": r"Vibration: ([\d.]+)"})
            
        Returns:
            A string summary of trends.
        """
        if not observations:
            return "No historical data available for trend analysis."
            
        # Sort by created_at (asc)
        sorted_obs = sorted(observations, key=lambda x: x.get('created_at', ''))
        
        trends = []
        for field, pattern in field_patterns.items():
            values = []
            for obs in sorted_obs:
                match = re.search(pattern, obs['content'])
                if match:
                    try:
                        values.append({
                            "val": float(match.group(1)),
                            "time": obs['created_at']
                        })
                    except (ValueError, IndexError):
                        continue
            
            if len(values) >= 2:
                first = values[0]
                last = values[-1]
                delta = last['val'] - first['val']
                percent = (delta / first['val'] * 100) if first['val'] != 0 else 0
                
                # Calculate duration
                try:
                    t1 = datetime.fromisoformat(first['time'].replace('Z', '+00:00'))
                    t2 = datetime.fromisoformat(last['time'].replace('Z', '+00:00'))
                    days = (t2 - t1).days
                    duration_str = f"{days} days" if days > 0 else "less than a day"
                except:
                    duration_str = "observed period"

                direction = "increased" if delta > 0 else "decreased"
                trend_str = f"- {field.capitalize()} {direction} from {first['val']:.2f} to {last['val']:.2f} ({percent:+.1f}%) over {duration_str}."
                trends.append(trend_str)
        
        if not trends:
            return "No significant numerical patterns detected in recent history."
            
        return "Historical Trend Summary:\n" + "\n".join(trends)

    @staticmethod
    def summarize_conflicts(observations: List[Dict[str, Any]]) -> str:
        """Looks for expert disagreements or ground-truth overrides."""
        summary_points = []
        
        # 1. Look for Expert Conflicts
        experts = ["OEM", "Consultant", "Operator", "Management"]
        expert_views = {e: [] for e in experts}
        for obs in observations:
            content = obs['content'].upper()
            for e in experts:
                if e in content:
                    expert_views[e].append(obs['content'])
        
        conflicting_experts = [e for e, views in expert_views.items() if views]
        if len(conflicting_experts) > 1:
            summary_points.append(f"- Expert Conflict: Recent history contains conflicting views from {', '.join(conflicting_experts)}.")
            
        # 2. Look for Ground Truth / Revelations
        ground_truths = [obs for obs in observations if "GROUND TRUTH" in obs['content'].upper() or "INSPECTION REVEALS" in obs['content'].upper()]
        if ground_truths:
            summary_points.append("\n" + "="*40)
            summary_points.append("!!! IMMUTABLE VERIFIED REALITY !!!")
            summary_points.append(f"Recent physical inspection confirms: '{ground_truths[-1]['content']}'")
            summary_points.append("="*40)
            
        # 3. Keyword-based anomalies
        anomalies = [obs for obs in observations if "conflict" in obs['content'].lower() or "ignored" in obs['content'].lower()]
        if anomalies:
            summary_points.append(f"- Noted {len(anomalies)} instances of ignored warnings or operational conflicts.")
            
        # 4. Agent's Own Past Actions (Executive Continuity)
        past_actions = [obs for obs in observations if "AGENT ACTION TAKEN" in obs['content'].upper()]
        if past_actions:
            # Sort by time to ensure sequence matters
            past_actions.sort(key=lambda x: x.get('created_at', ''), reverse=True)
            actions_str = "\n".join([f"  - {a['content']}" for a in past_actions[:5]])
            summary_points.append(f"### YOUR RECENT DECISION HISTORY (Descending):\n{actions_str}")
            
        # 5. Semantic Ground Truth Check
        if ground_truths:
            summary_points.append("\n!!! CRITICAL EPISTEMIC UPDATE !!!")
            summary_points.append("- Physical reality has been verified. Sensors are CONFIRMED accurate.")
            summary_points.append("- Disregard previous human-suggested 'normal' labels if they conflict with Ground Truth.")
        
        # 6. Inaction Tracking (Stale Recommendations)
        inaction_report = MemorySummarizer.detect_inaction_streak(observations)
        if inaction_report:
            summary_points.append("\n" + "!" * 20)
            summary_points.append(f"### RISK OF INACTION: {inaction_report['count']} cycles")
            summary_points.append(f"The recommendation '{inaction_report['action']}' has been ignored for multiple days.")
            summary_points.append("Internal authority weight is now escalated due to persistent non-action.")
            summary_points.append("!" * 20)
            
        return "\n".join(summary_points)

    @staticmethod
    def detect_inaction_streak(observations: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Identifies if the same high-importance action has been repeatedly suggested."""
        past_actions = [obs for obs in observations if "AGENT ACTION TAKEN" in obs['content'].upper()]
        if len(past_actions) < 2:
            return None
            
        # Sort by time (descending)
        past_actions.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        # Look for the last recommendation
        last_action = past_actions[0]['content'].split("Agent Action Taken: ")[-1].strip()
        
        # Count backwards how many times a similar action appeared without a resolution
        count = 1
        for a in past_actions[1:]:
            content = a['content'].split("Agent Action Taken: ")[-1].strip()
            # Fuzzy match (e.g. "Schedule inspection" vs "Schedule a detailed inspection")
            if last_action[:20].lower() in content.lower() or content[:20].lower() in last_action.lower():
                count += 1
            else:
                break
                
        if count >= 3: # Escalate after 3 identical recommendations
            return {"action": last_action, "count": count}
            
        return None
