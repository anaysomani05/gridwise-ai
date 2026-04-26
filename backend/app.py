"""
Run the API locally: `cd backend && python app.py`

This starts Uvicorn with the FastAPI app defined in `main.py` (reload on for dev).
"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )
