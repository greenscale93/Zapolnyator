from fastapi import FastAPI\napp=FastAPI()\n@app.get('/health')\nasync def health():\n    return {'status':'ok'}
