import json

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST


from core.prac_tool import agent_loop

AGENT_HISTORY = []

def index(request):
    return render(request, "chat/index.html")

@require_POST
def chat_api(request):
    data = json.loads(request.body)
    query = data.get("message", "").strip()

    if not query:
        return JsonResponse({"error": "message is required"}, status=400)
    
    AGENT_HISTORY.append({
        "role": "user",
        "content": query,
    })

    agent_loop(AGENT_HISTORY)

    response_content = AGENT_HISTORY[-1]["content"]

    if isinstance(response_content, list):
        for block in response_content:
            if hasattr(block, "text"):
                return JsonResponse({
                    "user": query,
                    "assistant": block.text
                })