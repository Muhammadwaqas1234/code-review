from agno.agent import Agent
from agno.models.openai import OpenAIChat


class AgentService:

    LLM_FAST = OpenAIChat(id="gpt-4o-mini", temperature=0.0)
    LLM_SMART = OpenAIChat(id="gpt-4o", temperature=0.0)

    @staticmethod
    def planner():
        return Agent(
            name="PlannerAgent",
            model=AgentService.LLM_SMART,
            instructions="""
            Analyze repository and decide required review agents.
            Output JSON: { "agents": ["style","security"] }
            """
        )

    @staticmethod
    def reviewer(name, instruction):
        return Agent(
            name=name,
            model=AgentService.LLM_SMART,
            instructions=instruction
        )

    @staticmethod
    def scoring():
        return Agent(
            name="ScoringAgent",
            model=AgentService.LLM_SMART,
            instructions="""
            Combine reviews and output strict JSON:
            {
                "final_score": number,
                "category_scores": {},
                "risk_level": "",
                "reasoning": ""
            }
            """
        )

    @staticmethod
    def reporter():
        return Agent(
            name="EnterpriseReportAgent",
            model=AgentService.LLM_SMART,
            instructions="""
            Generate enterprise report:
            Executive Summary,
            Risk Assessment,
            Production Readiness,
            Recommendations.
            """
        )
