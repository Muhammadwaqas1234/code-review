import json
import concurrent.futures
from backend.services.vector_service import VectorService
from backend.services.chunk_service import SmartChunker
from backend.services.agent_service import AgentService
from backend.config import logger


class OrchestratorService:

    def __init__(self):
        self.vector = VectorService()
        self.chunker = SmartChunker()

        self.review_agents = {
            "style": AgentService.reviewer("StyleAgent", "Review style. Output JSON."),
            "bugs": AgentService.reviewer("BugAgent", "Detect bugs. Output JSON."),
            "security": AgentService.reviewer("SecurityAgent", "Detect vulnerabilities. Output JSON."),
            "architecture": AgentService.reviewer("ArchitectureAgent", "Evaluate architecture. Output JSON."),
            "performance": AgentService.reviewer("PerformanceAgent", "Detect performance issues. Output JSON.")
        }

    def run_parallel(self, agents, context):
        results = {}

        def run(name):
            result = self.review_agents[name].run(context).content
            return name, result

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(run, name) for name in agents]

            for future in concurrent.futures.as_completed(futures):
                name, result = future.result()
                results[name] = result

        return results

    def execute(self, repo_text: str):

        chunks = self.chunker.chunk_text(repo_text)
        self.vector.build_index(chunks)

        planner = AgentService.planner()
        plan_raw = planner.run(repo_text[:4000]).content

        try:
            plan = json.loads(plan_raw)
            agents = plan.get("agents", list(self.review_agents.keys()))
        except:
            agents = list(self.review_agents.keys())

        reviews = self.run_parallel(agents, repo_text[:8000])

        scoring = AgentService.scoring()
        score = scoring.run(json.dumps(reviews)).content

        reporter = AgentService.reporter()
        report = reporter.run(str(reviews) + str(score)).content

        return {
            "reviews": reviews,
            "score": score,
            "report": report
        }
