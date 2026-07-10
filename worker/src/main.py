import logging
import os
import json
import re
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict, Optional
from src.mxl_parser import parse_mxl, convert_mxl_to_csv
from src.excel_processor import write_excel_data, read_excel_structure

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

class ToolRequest(BaseModel):
    tool: str
    arguments: Dict[str, Any]

class ToolResponse(BaseModel):
    status: str
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None

def sanitize_data(data):
    """Рекурсивно удаляет управляющие символы из строк."""
    if isinstance(data, str):
        return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', data)
    elif isinstance(data, dict):
        return {sanitize_data(k): sanitize_data(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_data(item) for item in data]
    else:
        return data

@app.post("/api/v1/tool")
async def call_tool(request: ToolRequest):
    logger.info(f"Calling tool: {request.tool} with args: {request.arguments}")
    try:
        if request.tool == "parse_mxl":
            result = await parse_mxl(request.arguments["file_path"])
            if result.get("status") == "error":
                return ToolResponse(status="error", error_message=result.get("error_message"))
            return ToolResponse(status="success", result=result.get("result"))
        
        elif request.tool == "convert_mxl_to_csv":
            result = await convert_mxl_to_csv(request.arguments["file_path"])
            if result.get("status") == "error":
                return ToolResponse(status="error", error_message=result.get("error_message"))
            return ToolResponse(status="success", result=result.get("result"))
        
        elif request.tool == "filter_mxl_data":
            file_path = request.arguments["file_path"]
            filters = request.arguments.get("filters", {})
            # Если файл CSV, читаем его
            if file_path.endswith('.csv'):
                import csv
                data = []
                with open(file_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    data = list(reader)
            else:
                parsed = await parse_mxl(file_path)
                if parsed.get("status") == "error":
                    return ToolResponse(status="error", error_message=parsed.get("error_message"))
                data = parsed["result"]["data"]
            
            # Применяем фильтры
            filtered = data
            for col, value in filters.items():
                if value is None:
                    continue
                if isinstance(value, list):
                    # Если список — проверяем вхождение
                    filtered = [row for row in filtered if row.get(col) in value]
                else:
                    # Строковое сравнение
                    filtered = [row for row in filtered if row.get(col) == value]
            
            # Очищаем данные
            filtered = sanitize_data(filtered)
            return ToolResponse(status="success", result={
                "filtered_data": filtered,
                "count": len(filtered)
            })
        
        elif request.tool == "write_excel":
            template_path = request.arguments["template_path"]
            sheets_data = request.arguments["sheets_data"]
            password = request.arguments.get("password", "987456")
            output_path = request.arguments.get("output_path")
            result = await write_excel_data(template_path, sheets_data, password, output_path)
            if result.get("status") == "error":
                return ToolResponse(status="error", error_message=result.get("error_message"))
            return ToolResponse(status="success", result={"output_path": result["output_path"]})
        
        elif request.tool == "read_excel_structure":
            file_path = request.arguments["file_path"]
            result = await read_excel_structure(file_path)
            if result.get("status") == "error":
                return ToolResponse(status="error", error_message=result.get("error_message"))
            return ToolResponse(status="success", result=result.get("result"))
        
        else:
            return ToolResponse(status="error", error_message=f"Unknown tool: {request.tool}")
    
    except Exception as e:
        logger.exception("Tool execution error")
        return ToolResponse(status="error", error_message=str(e))

@app.get("/health")
async def health():
    return {"status": "ok"}