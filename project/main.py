
import os
import json
import secrets
from datetime import datetime
from typing import Dict, Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from openai import OpenAI, OpenAIError

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))


# CONFIGURATION
class Config:
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    MEMORY_FILE = os.path.join(BASE_DIR, "memory.json")

    FRONTEND_ORIGINS = [
        x.strip()
        for x in os.getenv(
            "FRONTEND_ORIGINS",
            "http://localhost:5500,http://127.0.0.1:5500"
        ).split(",") if x.strip()
    ]


if not Config.OPENAI_API_KEY:
    raise RuntimeError(
        "OPENAI_API_KEY missing. Add it to your .env file."
    )

client = OpenAI(api_key=Config.OPENAI_API_KEY)


# MEMORY SYSTEM
class MemorySystem:
    def __init__(self, filepath=Config.MEMORY_FILE):
        self.filepath = filepath
        self.data = self._load_memory()

    def _load_memory(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError("Invalid memory format")
                data.setdefault("users", {})
                data.setdefault("conversations", [])
                return data
            except (OSError, ValueError, json.JSONDecodeError):
                return {"users": {}, "conversations": []}

        return {"users": {}, "conversations": []}

    def _save_memory(self):
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def add_conversation(self, user_id, role, content):
        self.data.setdefault("conversations", [])

        self.data["conversations"].append({
            "user_id": user_id,
            "role": role,
            "content": str(content)[:500],
            "timestamp": datetime.now().isoformat()
        })

        self.data["conversations"] = self.data["conversations"][-50:]
        self._save_memory()


# AGENTS
class BaseAgent:
    def __init__(self, name):
        self.name = name
        self.client = client


class WritingAgent(BaseAgent):
    def execute(self, task, **kwargs):
        response = self.client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a professional writer."},
                {"role": "user", "content": kwargs.get("content", "")}
            ]
        )

        return {
            "media_type": "text",
            "content": response.choices[0].message.content
        }


class CodingAgent(BaseAgent):
    def execute(self, task, **kwargs):
        response = self.client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an expert coder."},
                {"role": "user", "content": kwargs.get("requirements", "")}
            ]
        )

        return {
            "media_type": "text",
            "content": response.choices[0].message.content
        }


class ImageAgent(BaseAgent):
    def execute(self, task, **kwargs):
        try:
            response = self.client.images.generate(
                model="dall-e-3",
                prompt=kwargs.get("content", ""),
                n=1,
                size="1024x1024"
            )

            return {
                "media_type": "image",
                "url": response.data[0].url,
                "content": "Image is ready!"
            }

        except OpenAIError:
            return {
                "media_type": "text",
                "content": "Image generation failed. Please try again."
            }


# ORCHESTRATOR
class AIOrchestrator:
    def __init__(self):
        self.memory = MemorySystem()
        self.client = client

        self.agents = {
            "writing": WritingAgent("Writer"),
            "coding": CodingAgent("Coder"),
            "image": ImageAgent("Artist")
        }

    def process(self, user_id, user_input):
        self.memory.add_conversation(user_id, "user", user_input)

        ui_low = user_input.lower()

        if any(x in ui_low for x in ["image", "photo", "logo", "draw"]):
            intent = "image"
        elif any(x in ui_low for x in ["write", "essay", "email"]):
            intent = "writing"
        elif any(x in ui_low for x in ["code", "python", "debug"]):
            intent = "coding"
        else:
            intent = "general"

        if intent in self.agents:
            result = self.agents[intent].execute(
                task=intent,
                content=user_input,
                requirements=user_input
            )
        else:
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are Prismatic AI."},
                    {"role": "user", "content": user_input}
                ]
            )

            result = {
                "media_type": "text",
                "content": response.choices[0].message.content
            }

        self.memory.add_conversation(
            user_id, "assistant", result.get("content", "")
        )

        return {**result, "agent_used": intent}


# FASTAPI
app = FastAPI(title="Prismatic AI")
orchestrator = AIOrchestrator()

app.add_middleware(
    CORSMiddleware,
    allow_origins=Config.FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"]
)


def render_html_file(filename):
    paths = [
        os.path.join(BASE_DIR, filename),
        os.path.join(BASE_DIR, "templates", filename)
    ]

    for path in paths:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())

    return HTMLResponse(
        content=f"<h3>Error: {filename} nahi mili!</h3>",
        status_code=404
    )


@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
async def home(request: Request):
    return render_html_file("index.html")


@app.get("/dashboard", response_class=HTMLResponse)
@app.get("/dashboard.html", response_class=HTMLResponse)
async def dashboard(request: Request):
    return render_html_file("dashboard.html")


# DEMO LOGIN SYSTEM
class UserLogin(BaseModel):
    username: str
    password: str
    full_name: Optional[str] = None


fake_users_db = {
    "admin": {
        "username": "admin",
        "password": "123",
        "full_name": "Shashi Ranjan"
    }
}


@app.post("/signup")
async def signup(user_data: UserLogin):
    if user_data.username in fake_users_db:
        raise HTTPException(status_code=400, detail="User already exists")

    fake_users_db[user_data.username] = user_data.model_dump()
    return {"status": "success"}


@app.post("/login")
async def login(user_data: UserLogin):
    user = fake_users_db.get(user_data.username)

    if not user or user_data.password != user["password"]:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return {
        "status": "success",
        "token": secrets.token_hex(16),
        "username": user["username"]
    }


# CHAT
class ChatRequest(BaseModel):
    username: str = "User"
    message: str


@app.post("/chat")
async def chat(data: ChatRequest):
    message = data.message.strip()

    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    try:
        result = orchestrator.process(data.username, message)

    except OpenAIError:
        raise HTTPException(
            status_code=502,
            detail="AI service is temporarily unavailable."
        )

    return {
        "reply": result.get("content"),
        "media_type": result.get("media_type"),
        "url": result.get("url"),
        "agent_used": result.get("agent_used")
    }


# RUN SERVER
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8001,
        reload=True
    )
