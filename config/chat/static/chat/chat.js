/*
listen form post event:
    prevent browser refresh
    use fetch send post request to backend
    get json response from backend
    display response on the screen

js just care 3 variable
    form: which user can post msg
    input: user inut
    message: all conversation
             including user's query
             and llm's response

  用户在 textarea 输入
          ↓
  用户点击 Send / 触发表单 submit
          ↓
  浏览器准备执行表单默认提交
          ↓
  JS 捕获 submit 事件
          ↓
  event.preventDefault()
  阻止浏览器默认提交和页面刷新
          ↓
  JS 读取 input.value
          ↓
  JS appendMessage("user", text) 先显示用户消息
          ↓
  JS fetch POST /api/chat/
          ↓
  HTTP JSON: {"message": "..."}
          ↓
  Django chat_api(request)
          ↓
  json.loads(request.body)
          ↓
  Python dict: {"message": "..."}
          ↓
  agent_loop(AGENT_HISTORY)
          ↓
  Django JsonResponse({"assistant": "..."})
          ↓
  HTTP JSON 返回前端
          ↓
  response.json()
          ↓
  JS object: { assistant: "..." }
          ↓
  appendMessage("assistant", data.assistant)
*/

document.addEventListener("DOMContentLoaded", () => {
    const form = document.querySelector('#chat-form');
    const input = document.querySelector('#message');
    const messages = document.querySelector('#messages');

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const text = input.value.trim();
        if (!text) return;
        appendMessage("user", text)
        input.value = ""

        const thinkingMessage = appendMessage("assistant", "Thinking");
        thinkingMessage.classList.add("thinking");

        try {
            const response = await fetch("/api/chat/", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCsrfToken(),
                },
                body: JSON.stringify({ message: text }) 
            });

            const data = await response.json();
            const contentEl = thinkingMessage.querySelector(".content");

            if (data.error){
                contentEl.textContent = `Error: ${data.error}`;
            } else {
                contentEl.textContent = data.assistant || "(no response)";
            }
        } catch (error) {
            thinkingMessage.querySelector(".content").textContent = `Error: ${error}`;
        } finally {
            thinkingMessage.classList.remove("thinking");
        }     
    });

    function appendMessage(role, content){
        /*
        append JS object called article into messages(JS object)

        article has two attributes:
            className
            innerHTML

        deal innerHTML out of article
        */
        const article = document.createElement("article")
        article.className = `message ${role}`
        article.innerHTML = `
            <div class="role">${role}</div>
            <div class="content"></div>
        `
        article.querySelector(".content").textContent = content;
        messages.appendChild(article);
        return article
    };

    function getCsrfToken(){
        return document.querySelector("[name=csrfmiddlewaretoken]").value;
    }
})