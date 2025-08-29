# Steps to run the server

# 1. Activate the virtual environment
```
.venv\Scripts\activate
```

# 2. Run the dev server
```
cd server
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```