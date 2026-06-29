import os
import json
import subprocess
import httpx
from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional

app = FastAPI(title="Antigravity Chatbot")

# CORS middleware for testing / local requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory store for chat context (for simplicity in this basic version)
session_context = {
    "text": ""
}

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatPayload(BaseModel):
    model: str
    messages: List[ChatMessage]
    use_context: bool = False

@app.get("/api/models")
async def get_models():
    """
    Scans available local models. Attempts to run the `ollama list` command.
    Falls back to querying the Ollama API (/api/tags) if the command fails
    or if Ollama is running on a different host.
    """
    models = []
    
    # 1. Try running 'ollama list' command as requested
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            if len(lines) > 1:
                # First line is header: NAME | ID | SIZE | MODIFIED
                for line in lines[1:]:
                    parts = line.split()
                    if parts:
                        models.append(parts[0])
    except Exception as e:
        print(f"Subprocess 'ollama list' failed: {e}. Falling back to HTTP API.")

    # 2. If subprocess failed or returned empty list, try Ollama HTTP API
    if not models:
        ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{ollama_host}/api/tags")
                if response.status_code == 200:
                    data = response.json()
                    for model_info in data.get("models", []):
                        models.append(model_info.get("name"))
        except Exception as e:
            print(f"Ollama API tags query failed: {e}")

    # Deduplicate while preserving order
    unique_models = []
    for m in models:
        if m not in unique_models:
            unique_models.append(m)

    # If still empty, return a default model
    if not unique_models:
        # We don't want an empty menu, so return a placeholder
        unique_models = ["llama3:latest", "mistral:latest", "gemma:latest"]

    return {"models": unique_models}

@app.post("/api/chat")
async def chat(payload: ChatPayload):
    """
    Handles streaming chat using SSE. Integrates session context if requested.
    """
    ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    
    # Formulate messages list
    messages = [msg.dict() for msg in payload.messages]
    
    # Inject context if active and requested
    if payload.use_context and session_context["text"]:
        # Find the system prompt if it exists, or insert one
        system_msg_idx = -1
        for i, msg in enumerate(messages):
            if msg["role"] == "system":
                system_msg_idx = i
                break
        
        context_instruction = (
            f"Use the following context to help answer the user's questions:\n"
            f"--- START CONTEXT ---\n{session_context['text']}\n--- END CONTEXT ---\n"
        )
        
        if system_msg_idx != -1:
            messages[system_msg_idx]["content"] = (
                context_instruction + "\n" + messages[system_msg_idx]["content"]
            )
        else:
            messages.insert(0, {
                "role": "system",
                "content": context_instruction + "You are a helpful assistant."
            })

    async def stream_ollama():
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                async with client.stream(
                    "POST",
                    f"{ollama_host}/api/chat",
                    json={
                        "model": payload.model,
                        "messages": messages,
                        "stream": True
                    }
                ) as response:
                    if response.status_code != 200:
                        yield f"data: {json.dumps({'error': f'Ollama returned status {response.status_code}'})}\n\n"
                        return
                    
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            content = data.get("message", {}).get("content", "")
                            done = data.get("done", False)
                            yield f"data: {json.dumps({'content': content, 'done': done})}\n\n"
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                yield f"data: {json.dumps({'error': f'Connection to Ollama failed: {str(e)}'})}\n\n"

    return StreamingResponse(stream_ollama(), media_type="text/event-stream")

@app.post("/api/context")
async def add_context(
    text: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None)
):
    """
    Endpoints to upload or set text/file context.
    """
    if file:
        try:
            contents = await file.read()
            # Decode content as text
            session_context["text"] = contents.decode("utf-8", errors="ignore")
            filename = file.filename
            return {"status": "success", "message": f"File '{filename}' loaded as context.", "length": len(session_context["text"])}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to read file: {str(e)}")
    elif text is not None:
        session_context["text"] = text
        return {"status": "success", "message": "Text context loaded.", "length": len(session_context["text"])}
    
    raise HTTPException(status_code=400, detail="No text or file provided.")

@app.delete("/api/context")
async def clear_context():
    """
    Clears the active session context.
    """
    session_context["text"] = ""
    return {"status": "success", "message": "Context cleared."}

@app.get("/api/context")
async def get_context():
    """
    Retrieves information about current context status.
    """
    length = len(session_context["text"])
    preview = session_context["text"][:200] + "..." if length > 200 else session_context["text"]
    return {
        "active": length > 0,
        "length": length,
        "preview": preview
    }

# Mount the static files directory at root
# Note: Ensure static folder exists
os.makedirs("static", exist_ok=True)
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    # Start the server
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
