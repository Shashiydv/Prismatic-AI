import os
import json
import secrets
from datetime import datetime
from typing import Dict, List, Any, Optional
from abc import ABC, abstractmethod

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from openai import OpenAI

# Base Directory Path (Taaki files hamesha sahi location se load hon)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ============ 1. CONFIGURATION ============
class Config:
    # ⚠️ Apni API key yahan dalein ya .env use karein
    OPENAI_API_KEY = os.getenv(
        "OPENAI_API_KEY",
        "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"
    )
    MEMORY_FILE = os.path.join(BASE_DIR, "memory.json")

# ============ 2. MEMORY SYSTEM ============
class MemorySystem:
    def __init__(self, filepath: str = Config.MEMORY_FILE):
        self.filepath = filepath
        self.data = self._load_memory()
    
    def _load_memory(self) -> Dict[str, Any]:
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r', encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {"users": {}, "conversations": []}
        return {"users": {}, "conversations": []}
    
    def _save_memory(self):
        with open(self.filepath, 'w', encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)
    
    def add_conversation(self, user_id: str, role: str, content: str):
        if "conversations" not in self.data:
            self.data["conversations"] = []
        conversation = {
            "user_id": user_id, 
            "role": role, 
            "content": str(content)[:500], 
            "timestamp": datetime.now().isoformat()
        }
        self.data["conversations"].append(conversation)
        if len(self.data["conversations"]) > 50:
            self.data["conversations"] = self.data["conversations"][-50:]
        self._save_memory()

# ============ 3. AGENT CLASSES ============
class BaseAgent(ABC):
    def __init__(self, name: str):
        self.name = name
        self.client = OpenAI(api_key=Config.OPENAI_API_KEY)
        
    @abstractmethod
    def execute(self, task: str, **kwargs):
        pass

class WritingAgent(BaseAgent):
    def execute(self, task: str, **kwargs):
        response = self.client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a professional writer."},
                {"role": "user", "content": kwargs.get('content', '')}
            ]
        )
        return {"media_type": "text", "content": response.choices[0].message.content}

class CodingAgent(BaseAgent):
    def execute(self, task: str, **kwargs):
        response = self.client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an expert coder."},
                {"role": "user", "content": kwargs.get('requirements', '')}
            ]
        )
        return {"media_type": "text", "content": response.choices[0].message.content}

class ImageAgent(BaseAgent):
    def execute(self, task: str, **kwargs):
        try:
            response = self.client.images.generate(
                model="dall-e-3",
                prompt=kwargs.get('content', ''),
                n=1,
                size="1024x1024"
            )
            return {"media_type": "image", "url": response.data[0].url, "content": "Image is ready!"}
        except Exception as e:
            return {"media_type": "text", "content": f"Image Error: {str(e)}"}

# ============ 4. ORCHESTRATOR ============
class AIOrchestrator:
    def __init__(self):
        self.memory = MemorySystem()
        self.client = OpenAI(api_key=Config.OPENAI_API_KEY)
        self.agents = {
            "writing": WritingAgent("Writer"),
            "coding": CodingAgent("Coder"),
            "image": ImageAgent("Artist")
        }
    
    def process(self, user_id: str, user_input: str):
        self.memory.add_conversation(user_id, "user", user_input)
        ui_low = user_input.lower()
        
        if any(x in ui_low for x in ['image', 'photo', 'logo', 'draw']):
            intent = "image"
        elif any(x in ui_low for x in ['write', 'essay', 'email']):
            intent = "writing"
        elif any(x in ui_low for x in ['code', 'python', 'debug']):
            intent = "coding"
        else:
            intent = "general"

        if intent in self.agents:
            result = self.agents[intent].execute(task=intent, content=user_input, requirements=user_input)
        else:
            resp = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are Prismatic AI."},
                    {"role": "user", "content": user_input}
                ]
            )
            result = {"media_type": "text", "content": resp.choices[0].message.content}

        self.memory.add_conversation(user_id, "assistant", result.get('content', ''))
        return {**result, "agent_used": intent}

# ============ 5. FASTAPI APP & ROUTES ============
app = FastAPI(title="Prismatic AI")
orchestrator = AIOrchestrator()

app.add_middleware(
    CORSMiddleware, 
    allow_origins=["*"], 
    allow_credentials=True, 
    allow_methods=["*"], 
    allow_headers=["*"]
)

# Helper function: HTML file safely find aur serve karne ke liye
def render_html_file(filename: str):
    # 1. Check direct current folder
    direct_path = os.path.join(BASE_DIR, filename)
    if os.path.exists(direct_path):
        with open(direct_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
            
    # 2. Check inside 'templates' folder
    template_path = os.path.join(BASE_DIR, "templates", filename)
    if os.path.exists(template_path):
        with open(template_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
            
    return HTMLResponse(content=f"<h3>Error: {filename} nahi mili! Folder check karein.</h3>", status_code=404)

# Home Routes (Dono support karega: / aur /index.html)
@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
async def home(request: Request):
    return render_html_file("index.html")

# Dashboard Routes (Dono support karega: /dashboard aur /dashboard.html)
@app.get("/dashboard", response_class=HTMLResponse)
@app.get("/dashboard.html", response_class=HTMLResponse)
async def dashboard(request: Request):
    return render_html_file("dashboard.html")

class UserLogin(BaseModel):
    username: str
    password: str
    full_name: Optional[str] = None

fake_users_db = {"admin": {"username": "admin", "password": "123", "full_name": "Shashi Ranjan"}}

@app.post("/signup")
async def signup(user_data: UserLogin):
    if user_data.username in fake_users_db:
        raise HTTPException(status_code=400, detail="User already exists")
    fake_users_db[user_data.username] = user_data.model_dump()
    return {"status": "success"}

@app.post("/login")
async def login(user_data: UserLogin):
    user = fake_users_db.get(user_data.username)
    if not user or user_data.password != user['password']:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"status": "success", "token": secrets.token_hex(16), "username": user['username']}

# Chat Route
@app.post("/chat")
async def chat(data: dict):
    username = data.get("username", "User")
    message = data.get("message", "")
    
    result = orchestrator.process(username, message)
    
    return {
        "reply": result.get('content'),
        "media_type": result.get('media_type'),
        "url": result.get('url'),
        "agent_used": result.get('agent_used')
    }

# ============ 6. RUN SERVER ============
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8001, reload=True)