function toggleChat() {
    const widget = document.getElementById("chat-widget");
    widget.classList.toggle("hidden");
  }
  
  function sendMessage() {
    const input = document.getElementById("chat-input");
    const box = document.getElementById("chat-box");
  
    if (!input || !box) return;
  
    const text = input.value.trim();
    if (!text) return;
  
    addMessage(text, "user");
  
    input.value = "";
    showTyping();
  
    fetch("/chat-symptoms", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text })
    })
    .then(r => r.json())
    .then(data => {
        hideTyping();
        addMessage(data.reply || "Error", "bot");
        handleBotResponse(data);
      })
    .catch(() => {
      hideTyping();
      addMessage("Server error", "bot");
    });
  }
  
  function resetChat() {
    fetch("/reset-chat").then(() => {
      const box = document.getElementById("chat-box");
      if (!box) return;
  
      localStorage.removeItem("bookwell_chat");
  
      box.innerHTML = `
        <div class="text-sm text-gray-500">
          🤖 Hi! What symptoms are you experiencing?
        </div>
      `;
    });
  }
  function handleBotResponse(data) {
    const btn = document.getElementById("book-btn-container");
  
    if (data.show_booking) {
      selectedCategory = data.category;
      btn.classList.remove("hidden");
    } else {
      btn.classList.add("hidden");
    }
  }