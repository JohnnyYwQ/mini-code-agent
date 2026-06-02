import json

from django.http import JsonResponse
from django.shortcuts import render


from core.agent import agent_loop

AGENT_HISTORY = []

def index(request):
    return render(request, "chat/index.html")

def brief_error(exc):
    """
    catch error in agentloop
    No full traceback, return clean error
    """
    message = str(exc).splitlines()[0].strip()
    return message[:300] or exc.__class__.__name__

def extract_assistant_text(message):
    """
    catch last message(which should be assistant response)
    catch 4 cases:
        last message is not a dict
        role of last message is not assistant
        content of last message is not a list
        collect all texts, include:
            block.text: block is a dict
            block.get("text"): block is a object
    """
    if not isinstance(message, dict):
        return None
    if message.get("role") != "assistant":
        return None

    content = message.get("content")
    if not isinstance(content, list):
        return None

    parts = []
    for block in content:
        text = getattr(block, "text", None)
        if text is None and isinstance(block, dict):
            text = block.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())

    return "\n".join(parts) or None

def chat_api(request):
    """
    during post request, we catch:
        method error(not post)
        json error
        message error:
            data is not a dict
            real message is not str
            msg only is space
        agentloop error:
            brief_error catch in progress agentloop
            extract_assistant_text catch result of message
    """
    if request.method != "POST":
        response = JsonResponse({"ok": False, "error": "Method not allowed"}, status=405)
        response["Allow"] = "POST"
        return response
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    if not isinstance(data, dict):
        return JsonResponse({"ok": False, "error": "Message is required"}, status=400)

    raw_message = data.get("message")
    if not isinstance(raw_message, str):
        return JsonResponse({"ok": False, "error": "Message is required"}, status=400)

    query = raw_message.strip()

    if not query:
        return JsonResponse({"ok": False, "error": "Message is required"}, status=400)
    
    AGENT_HISTORY.append({
        "role": "user",
        "content": query,
    })

    try:
        agent_loop(AGENT_HISTORY)
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"Agent failed: {brief_error(e)}"}, status=500)

    assistant_text = extract_assistant_text(AGENT_HISTORY[-1] if AGENT_HISTORY else None)
    if not assistant_text:
        return JsonResponse({"ok": False, "error": "Agent returned no assistant text"}, status=502)

    return JsonResponse({
        "ok": True,
        "user": raw_message,
        "assistant": assistant_text,
        "tool_trace": [],
    })
