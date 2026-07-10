import logging
logger = logging.getLogger(__name__)

class OrchestratorClient:
    async def create_task(self, user_id: int, excel_path: str, mxl_path: str) -> str:
        logger.info(f"Mock: task created for {user_id}")
        return "mock-task-id"