import os
import json
import secrets
from datetime import datetime
from typing import Dict, List, Any
from abc import ABC, abstractmethod

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI

# ============ CONFIGURATION ============
class Config:
    # ⚠️ Apni API Key ko safe rakhein
    OPENAI_API_KEY = "sk-proj-w_07..." 
    MEMORY_FILE = "memory.json"

# ============ AI AGENTS & MEMORY ============

class MemorySystem:
    def __init__(self, filepath: str = Config.MEMORY_FILE):
        self.filepath = filepath
        self.data = self._load_memory()
    
    def _load_memory(self) -> Dict[str, Any]:
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r') as f: return json.load(f)
            except: return {"users": {}, "conversations": []}
        return {"users": {}, "conversations": []}
    
    def _save_memory(self):
        with open(self.filepath, 'w') as f: json.dump(self.data, f, indent=2)
    
    def add_conversation(self, user_id: str, role: str, content: str):
        conversation = {
            "user_id": user_id, 
            "role": role, 
            "content": str(content)[:500], 
            "timestamp": datetime.now().isoformat()
        }
        self.data["conversations"].append(conversation)
        # Last 50 messages tak limit
        if len(self.data["conversations"]) > 50: self.data["conversations"] = self.data["conversations"][-50:]
        self._save_memory()

class BaseAgent(ABC):
    def __init__(self, name: str):
        self.name = name
        self.client = OpenAI(api_key=Config.OPENAI_API_KEY)
    @abstractmethod
    def execute(self, task: str, **kwargs): pass

class WritingAgent(BaseAgent):
    def execute(self, task: str, **kwargs):
        response = self.client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "system", "content": "You are a professional content writer."},
                      {"role": "user", "content": kwargs.get('content', '')}]
        )
        return {"media_type": "text", "content": response.choices[0].message.content}

class CodingAgent(BaseAgent):
    def execute(self, task: str, **kwargs):
        response = self.client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "system", "content": "You are a senior software engineer. Provide clean code with comments."},
                      {"role": "user", "content": kwargs.get('requirements', '')}]
        )
        return {"media_type": "text", "content": response.choices[0].message.content}

class ImageAgent(BaseAgent):
    def execute(self, task: str, **kwargs):
        try:
            response = self.client.images.generate(
                model="dall-e-3",
                prompt=kwargs.get('content', ''),
                n=1, size="1024x1024"
            )
            return {"media_type": "image", "url": response.data[0].url, "content": "Maine aapke liye art generate kar di hai!"}
        except Exception as e:
            return {"media_type": "text", "content": f"Image Generation failed: {str(e)}"}

class AIOrchestrator:
    def __init__(self):
        self.memory = MemorySystem()
        self.agents = {
            "writing": WritingAgent("Writer"),
            "coding": CodingAgent("Coder"),
            "image": ImageAgent("Artist")
        }
        self.client = OpenAI(api_key=Config.OPENAI_API_KEY)
    
    def process(self, user_id: str, user_input: str):
        # 1. User ki baat memory mein daalein
        self.memory.add_conversation(user_id, "user", user_input)
        
        # 2. Intent Classification (Kaunsa agent kaam karega?)
        ui_low = user_input.lower()
        if any(x in ui_low for x in ['image', 'photo', 'banao', 'logo', 'draw', 'picture']):
            intent = "image"
        elif any(x in ui_low for x in ['write', 'essay', 'email', 'story', 'letter']):
            intent = "writing"
        elif any(x in ui_low for x in ['code', 'python', 'cpp', 'debug', 'html', 'function']):
            intent = "coding"
        else:
            intent = "general"

        # 3. Agent Execution
        if intent in self.agents:
            result = self.agents[intent].execute(task=intent, content=user_input, requirements=user_input)
        else:
            # General Chat Logic
            resp = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "system", "content": f"You are Prismatic AI, Shashi's personal assistant. User is {user_id}."},
                          {"role": "user", "content": user_input}]
            )
            result = {"media_type": "text", "content": resp.choices[0].message.content}

        # 4. Assistant ka reply memory mein daalein
        self.memory.add_conversation(user_id, "assistant", result.get('content', ''))
        return {**result, "agent_used": intent}

# ============ FASTAPI ROUTES ============
app = FastAPI()
orchestrator = AIOrchestrator()

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class UserLogin(BaseModel):
    username: str
    password: str

class ChatRequest(BaseModel):
    message: str
    username: str

fake_users_db = {"admin": {"username": "admin", "password": "123"}}

@app.post("/signup")
async def signup(user_data: UserLogin):
    fake_users_db[user_data.username] = user_data.model_dump()
    return {"status": "success", "message": "Account created!"}

@app.post("/login")
async def login(user_data: UserLogin):
    user = fake_users_db.get(user_data.username)
    if not user or user_data.password != user['password']:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"status": "success", "token": secrets.token_hex(16), "username": user['username']}

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    # AI process karega aur result nikalega
    result = orchestrator.process(request.username, request.message)
    
    # Dashboard ko data bhej rahe hain
    return {
        "reply": result.get('content'),
        "media_type": result.get('media_type'),
        "url": result.get('url', None),
        "agent_used": result.get('agent_used')
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)