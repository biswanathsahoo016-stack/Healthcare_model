function el(id) {
  return document.getElementById(id);
}

function fmtTime(isoStr) {
  try {
    const d = new Date(isoStr);
    return d.toLocaleString();
  } catch (e) {
    return isoStr;
  }
}

function renderMessage(role, text) {
  const chat = el("chat");
  const node = document.createElement("div");
  node.className = `msg ${role}`;
  node.textContent = text;
  chat.appendChild(node);
  chat.scrollTop = chat.scrollHeight;
}

async function typeMessage(role, text, speed = 30) {
  const chat = el("chat");
  const node = document.createElement("div");
  node.className = `msg ${role}`;
  node.textContent = "";
  chat.appendChild(node);

  for (let i = 0; i < text.length; i++) {
    node.textContent += text[i];
    chat.scrollTop = chat.scrollHeight;
    await new Promise(resolve => setTimeout(resolve, speed));
  }
}

function renderBotResponse(response) {
  if (response.error) {
    renderMessage("bot", `Error: ${response.error}`);
    return;
  }
  
  const text = response.response || "No response generated.";
  typeMessage("bot", text, 20);
}

async function fetchJSON(url, opts) {
  const res = await fetch(url, {
    ...opts,
    headers: {
      ...opts?.headers,
      "Cache-Control": "no-cache, no-store, must-revalidate"
    }
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || `Request failed: ${res.status}`);
  }
  return data;
}

async function loadHistory() {
  const list = el("historyList");
  list.innerHTML = "";
  try {
    const data = await fetchJSON("/api/history");
    const history = data.history || [];
    if (history.length === 0) {
      list.innerHTML = "<div class='muted'>No history yet.</div>";
      return;
    }

    history
      .slice()
      .reverse()
      .forEach((h) => {
        const item = document.createElement("div");
        item.className = "history-item";

        const topResult =
          h.response && h.response.response
            ? h.response.response.substring(0, 50) + "..."
            : "AI Response";

        item.textContent = `${fmtTime(h.ts)} - Input: ${h.input} -> ${topResult}`;
        list.appendChild(item);
      });
  } catch (e) {
    list.innerHTML = "<div class='muted'>Could not load history.</div>";
  }
}

async function clearHistory() {
  await fetchJSON("/api/history", { method: "DELETE" });
  await loadHistory();
}

async function handleSubmit(e) {
  e.preventDefault();
  const input = el("inputText").value.trim();
  if (!input) return;

  renderMessage("user", input);
  el("inputText").value = "";

  try {
    const response = await fetchJSON("/api/predict", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ input })
    });
    console.log("API Response:", response);
    
    // Check if response has error
    if (response.error) {
      renderMessage("bot", `Error: ${response.error}`);
    } else {
      const text = response.response || "No response generated.";
      await typeMessage("bot", text, 20);
    }
    
    await loadHistory();
  } catch (err) {
    renderMessage("bot", `Error: ${err.message || "Something went wrong. Try again."}`);
    // eslint-disable-next-line no-console
    console.error("Full error:", err);
  }
}

function setupVoiceInput() {
  const voiceBtn = el("voiceBtn");
  const voiceStatus = el("voiceStatus");

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    voiceBtn.disabled = true;
    voiceBtn.title = "Voice input not supported in this browser.";
    voiceStatus.textContent = "Voice not supported.";
    return;
  }

  const recog = new SpeechRecognition();
  recog.lang = "en-US";
  recog.interimResults = false;
  recog.maxAlternatives = 1;

  recog.onstart = () => {
    voiceStatus.textContent = "Listening...";
  };
  recog.onerror = (event) => {
    voiceStatus.textContent = `Voice error: ${event.error || "unknown"}`;
  };
  recog.onend = () => {
    voiceStatus.textContent = "";
  };
  recog.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    el("inputText").value = transcript;
  };

  voiceBtn.addEventListener("click", () => recog.start());
}

async function init() {
  el("symptomForm").addEventListener("submit", handleSubmit);
  el("clearHistoryBtn").addEventListener("click", clearHistory);
  setupVoiceInput();
  await loadHistory();
}

init();

