import logging
import os
import json
import re
import pandas as pd
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict, Optional
from src.mxl_parser import parse_mxl, convert_mxl_to_csv
from src.excel_processor import read_excel_structure, apply_sheet_mapping
from src.vz_utils import get_empty_vz_contractors
from src.template_reader import get_template_offices
from src.ffot_writer import process_write_values, process_read_values

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
        
        elif request.tool == "read_excel_data":
            file_path = request.arguments["file_path"]
            sheet_name = request.arguments.get("sheet_name")
            try:
                df = pd.read_excel(file_path, sheet_name=sheet_name, header=0)
                df = df.where(pd.notnull(df), None)
                data = df.to_dict(orient='records')
                columns = df.columns.tolist()
                data = sanitize_data(data)
                return ToolResponse(status="success", result={
                    "data": data,
                    "columns": columns,
                    "rows": len(data)
                })
            except Exception as e:
                logger.exception("read_excel_data error")
                return ToolResponse(status="error", error_message=str(e))
        
        elif request.tool == "apply_sheet_mapping":
            source_path = request.arguments["source_path"]
            template_path = request.arguments["template_path"]
            sheet_name = request.arguments["sheet_name"]
            mapping = request.arguments["mapping"]
            month = request.arguments["month"]
            year = request.arguments["year"]
            password = request.arguments.get("password", "987456")
            output_path = request.arguments.get("output_path")
            result = await apply_sheet_mapping(source_path, template_path, sheet_name, mapping, month, year, password, output_path)
            if result.get("status") == "error":
                return ToolResponse(status="error", error_message=result.get("error_message"))
            return ToolResponse(status="success", result={"output_path": result["output_path"], "rows_added": result.get("rows_added")})
        
        elif request.tool == "read_excel_structure":
            file_path = request.arguments["file_path"]
            result = await read_excel_structure(file_path)
            if result.get("status") == "error":
                return ToolResponse(status="error", error_message=result.get("error_message"))
            return ToolResponse(status="success", result=result.get("result"))

        elif request.tool == "read_vz_empty_contractors":
            source_path = request.arguments["source_path"]
            if not os.path.exists(source_path):
                return ToolResponse(status="error", error_message=f"Source file not found: {source_path}")
            try:
                contractors = get_empty_vz_contractors(source_path)
                return ToolResponse(status="success", result={"contractors": contractors})
            except Exception as e:
                logger.exception("read_vz_empty_contractors error")
                return ToolResponse(status="error", error_message=str(e))
        
        elif request.tool == "read_template_offices":
            template_path = request.arguments["template_path"]
            if not os.path.exists(template_path):
                return ToolResponse(status="error", error_message=f"Template file not found: {template_path}")
            try:
                offices = get_template_offices(template_path)
                return ToolResponse(status="success", result={"offices": offices})
            except Exception as e:
                logger.exception("read_template_offices error")
                return ToolResponse(status="error", error_message=str(e))

        elif request.tool == "write_ffot_value":
            source_path = request.arguments["source_path"]
            template_path = request.arguments["template_path"]
            month = request.arguments["month"]
            year = request.arguments["year"]
            config = request.arguments.get("config", {})
            if not os.path.exists(source_path):
                return ToolResponse(status="error", error_message=f"Source file not found: {source_path}")
            if not os.path.exists(template_path):
                return ToolResponse(status="error", error_message=f"Template file not found: {template_path}")
            try:
                # Если передан config из rules.json — используем config-driven подход
                if config:
                    results = await process_write_values(
                        source_path, template_path, [config], month, year
                    )
                    return ToolResponse(status="success", result={"results": results})
                else:
                    # Старый формат для обратной совместимости
                    from src.ffot_writer import _write_ffot
                    default_config = {
                        "key": "ffot",
                        "row_name": "ФОТ фактический, руб.",
                        "row_column": 3,
                        "month_row": 2,
                        "month_offset": -1,
                        "label": "ФОТ фактический, руб."
                    }
                    result = await _write_ffot(
                        source_path, template_path, default_config, month, year
                    )
                    return ToolResponse(status="success", result=result)
            except Exception as e:
                logger.exception("write_ffot_value error")
                return ToolResponse(status="error", error_message=str(e))

        elif request.tool == "process_write_values":
            source_path = request.arguments["source_path"]
            template_path = request.arguments["template_path"]
            month = request.arguments["month"]
            year = request.arguments["year"]
            values = request.arguments.get("values", [])
            if not os.path.exists(source_path):
                return ToolResponse(status="error", error_message=f"Source file not found: {source_path}")
            if not os.path.exists(template_path):
                return ToolResponse(status="error", error_message=f"Template file not found: {template_path}")
            try:
                results = await process_write_values(
                    source_path, template_path, values, month, year
                )
                return ToolResponse(status="success", result={"results": results})
            except Exception as e:
                logger.exception("process_write_values error")
                return ToolResponse(status="error", error_message=str(e))

        elif request.tool == "read_template_values":
            template_path = request.arguments["template_path"]
            month = request.arguments["month"]
            year = request.arguments["year"]
            values = request.arguments.get("values", [])
            if not os.path.exists(template_path):
                return ToolResponse(status="error", error_message=f"Template file not found: {template_path}")
            try:
                results = process_read_values(
                    template_path, values, month, year
                )
                return ToolResponse(status="success", result={"results": results})
            except Exception as e:
                logger.exception("read_template_values error")
                return ToolResponse(status="error", error_message=str(e))
                    
        else:
            return ToolResponse(status="error", error_message=f"Unknown tool: {request.tool}")
    
    except Exception as e:
        logger.exception("Tool execution error")
        return ToolResponse(status="error", error_message=str(e))

@app.get("/health")
async def health():
    return {"status": "ok"}