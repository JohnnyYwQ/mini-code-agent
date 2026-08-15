document.addEventListener("DOMContentLoaded", () => {
    const form = document.querySelector("#chat-form");
    const input = document.querySelector("#message");
    const messages = document.querySelector("#messages");
    if (!form || !input || !messages) return;

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const text = input.value.trim();
        const conversationId = form.dataset.conversationId;
        if (!text || !conversationId) return;

        removeEmptyState();
        appendMessage("user", text);
        input.value = "";
        const thinkingMessage = appendMessage("assistant", "Thinking");
        thinkingMessage.classList.add("thinking");

        try {
            const response = await fetch("/api/chat/", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCsrfToken(),
                },
                body: JSON.stringify({
                    conversation_id: conversationId,
                    message: text,
                }),
            });
            const data = await response.json();
            const content = thinkingMessage.querySelector(".content");
            if (!response.ok || data.error) {
                content.textContent = `Error: ${data.error || response.statusText}`;
            } else {
                content.textContent = data.assistant || "(no response)";
                updateConversationTitle(conversationId, data.title);
            }
        } catch (error) {
            thinkingMessage.querySelector(".content").textContent = `Error: ${error}`;
        } finally {
            thinkingMessage.classList.remove("thinking");
        }
    });

    function appendMessage(role, content) {
        const article = document.createElement("article");
        article.className = `message ${role}`;
        article.innerHTML = `
            <div class="role">${role}</div>
            <div class="content"></div>
        `;
        article.querySelector(".content").textContent = content;
        messages.appendChild(article);
        messages.scrollTop = messages.scrollHeight;
        return article;
    }

    function removeEmptyState() {
        messages.querySelector(".empty")?.remove();
    }

    function getCsrfToken() {
        return form.querySelector("[name=csrfmiddlewaretoken]").value;
    }

    function updateConversationTitle(conversationId, title) {
        if (!title) return;
        const headerTitle = document.querySelector("#conversation-title");
        if (headerTitle) headerTitle.textContent = title;
        const link = document.querySelector(
            `[data-conversation-id="${CSS.escape(conversationId)}"]`,
        );
        const label = link?.querySelector("span");
        if (label) label.textContent = title;
    }
});
