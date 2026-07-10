FROM python:3.11-slim\nWORKDIR /app\nCOPY requirements.txt .\nRUN pip install -r requirements.txt\nCMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
