import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Dict
from src.mxl_parser import parse_mxl
from src.business_logic import process_data
from src.excel_processor import update_excel
from src.metrics import calculate_metrics
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

class ToolRequest(BaseModel):
    tool: str
    arguments: Dict[str, Any]

class ToolResponse(BaseModel):
    status: str  # "success" | "needs_clarification" | "error"
    result: Dict[str, Any] | None = None
    clarification: Dict[str, Any] | None = None
    error_message: str | None = None

@app.post("/api/v1/tool")
async def call_tool(request: ToolRequest):
    logger.info(f"Calling tool: {request.tool} with args: {request.arguments}")
    try:
        if request.tool == "parse_mxl":
            result = await parse_mxl(request.arguments["file_path"])
        elif request.tool == "process_data":
            result = await process_data(
                mxl_data=request.arguments["mxl_data"],
                month=request.arguments["month"],
                year=request.arguments["year"],
                rules=request.arguments.get("rules", {}),
                user_mapping=request.arguments.get("user_mapping")
            )
        elif request.tool == "update_excel":
            result = await update_excel(
                template_path=request.arguments["template_path"],
                data=request.arguments["data"],
                month=request.arguments["month"],
                year=request.arguments["year"],
                password=request.arguments.get("password", "987456")
            )
        elif request.tool == "calculate_metrics":
            result = await calculate_metrics(
                output_path=request.arguments["output_path"],
                month=request.arguments["month"],
                year=request.arguments["year"],
                payroll_data=request.arguments.get("payroll_data")
            )
        else:
            return ToolResponse(status="error", error_message=f"Unknown tool: {request.tool}")
        
        if result.get("status") == "needs_clarification":
            return ToolResponse(status="needs_clarification", clarification=result.get("clarification"))
        elif result.get("status") == "error":
            return ToolResponse(status="error", error_message=result.get("error_message"))
        else:
            return ToolResponse(status="success", result=result.get("result"))
    except Exception as e:
        logger.exception("Tool execution error")
        return ToolResponse(status="error", error_message=str(e))

@app.get("/health")
async def health():
    return {"status": "ok"}