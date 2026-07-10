import logging
import os
import json
import csv
from io import StringIO
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict, Optional, List
from src.mxl_parser import parse_mxl
from src.excel_processor import write_excel_data, read_excel_structure

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

class ToolRequest(BaseModel):
    tool: str
    arguments: Dict[str, Any]

class ToolResponse(BaseModel):
    status: str  # "success" | "error"
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None

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
            file_path = request.arguments["file_path"]
            parsed = await parse_mxl(file_path)
            if parsed.get("status") == "error":
                return ToolResponse(status="error", error_message=parsed.get("error_message"))
            data = parsed["result"]["data"]
            columns = parsed["result"]["columns"]
            if not data:
                return ToolResponse(status="error", error_message="No data in MXL")
            # Генерируем CSV
            output = StringIO()
            writer = csv.DictWriter(output, fieldnames=columns, delimiter=';', quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()
            writer.writerows(data)
            csv_data = output.getvalue()
            # Сохраняем CSV рядом с исходным файлом
            csv_path = file_path + ".csv"
            with open(csv_path, 'w', encoding='utf-8-sig') as f:
                f.write(csv_data)
            logger.info(f"Converted MXL to CSV: {csv_path}, rows={len(data)}, size={len(csv_data)}")
            return ToolResponse(status="success", result={
                "csv_path": csv_path,
                "csv_data": csv_data,  # можно передать, но если большой, лучше не передавать
                "rows": len(data),
                "columns": columns,
                "size": len(csv_data)
            })
        
        elif request.tool == "get_mxl_structure":
            file_path = request.arguments["file_path"]
            parsed = await parse_mxl(file_path)
            if parsed.get("status") == "error":
                return ToolResponse(status="error", error_message=parsed.get("error_message"))
            data = parsed["result"]["data"]
            columns = parsed["result"]["columns"]
            samples = data[:10] if data else []
            return ToolResponse(status="success", result={
                "columns": columns,
                "samples": samples,
                "total_rows": len(data)
            })
        
        elif request.tool == "filter_mxl_data":
            file_path = request.arguments["file_path"]
            filters = request.arguments.get("filters", {})
            parsed = await parse_mxl(file_path)
            if parsed.get("status") == "error":
                return ToolResponse(status="error", error_message=parsed.get("error_message"))
            data = parsed["result"]["data"]
            filtered = data
            for col, value in filters.items():
                if value is None:
                    continue
                if isinstance(value, list):
                    filtered = [row for row in filtered if row.get(col) in value]
                else:
                    filtered = [row for row in filtered if row.get(col) == value]
            # Проверяем сериализуемость
            try:
                json.dumps(filtered, ensure_ascii=False, default=str)
            except Exception as e:
                return ToolResponse(status="error", error_message=f"Data serialization error: {e}")
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