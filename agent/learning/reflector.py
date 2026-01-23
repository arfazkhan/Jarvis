
import json
import time

REFLECTION_SYSTEM_PROMPT = """
You are the "Reflector" — an advanced component of the Home Agent's memory.

Your Goal:
Analyze the provided interaction history between the User and the Agent.
Identify if the agent made a mistake, was corrected, or if the user expressed a specific preference/constraint.

Output:
If you find a teachable lesson, extract it as a "Lesson".
A Lesson is a general rule that should be followed in the future.

Examples:
- Interaction: User said "Turn on lights", Agent turned them on 100%, User said "No, too bright, set to 50%".
- Lesson: "When turning on lights in the evening, default to 50% brightness unless specified."

- Interaction: User said "Play music", Agent played Rock, User said "I hate Rock, play Jazz".
- Lesson: "User dislikes Rock music and prefers Jazz."

Tool Usage:
Use the `log_lesson` tool to save these insights.
If no clear lesson is found, do nothing.
"""

class Reflector:
    def __init__(self, llm_client):
        self.llm_client = llm_client

    def reflect(self, interaction_history: list) -> list:
        """
        Analyze a list of interaction events (User/Agent messages) 
        and return a list of tool (log_lesson) calls.
        """
        if not self.llm_client or not interaction_history:
            return []

        # Format history for the LLM
        context_str = json.dumps(interaction_history, indent=2)

        # Define the specific tool for this task
        tools = [{
            "type": "function",
            "function": {
                "name": "log_lesson",
                "description": "Log a learned lesson or strategy from a past interaction",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "lesson": {
                            "type": "string", 
                            "description": "The generalizable rule or fact learned"
                        },
                        "context": {
                            "type": "string",
                            "description": "Brief context on why this was learned (e.g. 'User correction')"
                        }
                    },
                    "required": ["lesson", "context"]
                }
            }
        }]

        try:
            # reuse LLMAgent's generate logic but with custom tools/prompt
            # We assume LLMAgent.generate_tool_calls supports passing custom tools
            # If not, we might need to modify LLMAgent or use the client directly.
            # Looking at LLMAgent code, generate_tool_calls accepts `tools` argument.
            
            tool_calls = self.llm_client.generate_tool_calls(
                system_prompt=REFLECTION_SYSTEM_PROMPT,
                user_content=f"Analyze this history:\n{context_str}",
                tools=tools
            )
            return tool_calls

        except Exception as e:
            print(f"[Reflector] Error during reflection: {e}")
            return []
