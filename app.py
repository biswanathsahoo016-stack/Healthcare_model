import json
from pathlib import Path
from typing import Any, Dict, List

from flask import Flask, jsonify, render_template, request
from groq import Groq
from dotenv import load_dotenv
import os

from chatbot import build_matcher, now_iso


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

DATASET_PATH = DATA_DIR / "disease_data.json"
HISTORY_PATH = DATA_DIR / "chat_history.json"


def _load_history() -> List[Dict[str, Any]]:
    if not HISTORY_PATH.exists():
        return []
    try:
        with HISTORY_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except json.JSONDecodeError:
        return []


def _append_history(entry: Dict[str, Any]) -> None:
    history = _load_history()
    history.append(entry)
    # Keep the file small.
    history = history[-200:]
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_PATH.open("w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def create_app() -> Flask:
    load_dotenv()
    groq_api_key = os.getenv("GROQ_API_KEY")
    if not groq_api_key:
        raise ValueError("GROQ_API_KEY not found in environment variables")

    app = Flask(
        __name__,
        template_folder=str(TEMPLATE_DIR),
        static_folder=str(STATIC_DIR),
    )

    matcher = build_matcher(DATASET_PATH)
    
    # Load dataset for AI context
    with DATASET_PATH.open("r", encoding="utf-8") as f:
        dataset = json.load(f)
    diseases = dataset.get("diseases", [])

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.post("/api/predict")
    def predict():
        try:
            payload = request.get_json(silent=True) or {}
            user_input = (payload.get("input") or "").strip()

            if not user_input:
                return jsonify({"error": "Input is required"}), 400

            # Create context from diseases
            context = "\n".join([
                f"Disease: {d['name']}\nSymptoms: {', '.join(d.get('symptoms', []))}\nDescription: {d.get('description', '')}\nPrecautions: {', '.join(d.get('precautions', []))}\nOTC Medicines: {', '.join([m['name'] for m in d.get('otc_medicines', [])])}\nWhen to consult doctor: {', '.join(d.get('when_to_consult_doctor', []))}"
                for d in diseases
            ])

            prompt = f"""You are a healthcare chatbot. Use the following disease information as context to provide helpful suggestions. Remember: This is not medical advice, and users should consult professionals.

Context:
{context}

User input: {user_input}

Provide a response with possible matches, precautions, and when to see a doctor. Include the disclaimer: "This is not a medical diagnosis tool." """

            client = Groq(api_key=groq_api_key)
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500
            )
            ai_response = response.choices[0].message.content.strip()

            response_data = {
                "query": user_input,
                "response": ai_response,
                "disclaimer": "This is not a medical diagnosis tool."
            }

            include_history = bool(payload.get("include_history", True))
            if include_history:
                _append_history(
                    {
                        "ts": now_iso(),
                        "input": user_input,
                        "response": response_data,
                    }
                )

            return jsonify(response_data)
        except Exception as e:
            print(f"Error in predict: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({"error": f"Failed to get response from Groq: {str(e)}"}), 500

    @app.get("/api/history")
    def history_get():
        history = _load_history()
        return jsonify({"history": history[-50:]})

    @app.delete("/api/history")
    def history_clear():
        if HISTORY_PATH.exists():
            HISTORY_PATH.write_text("[]", encoding="utf-8")
        return jsonify({"ok": True})

    @app.get("/health")
    def health_check():
        return jsonify({"ok": True})

    return app


app = create_app()

if __name__ == "__main__":
    # Debug is fine for local testing; disable for production.
    app.run(host="127.0.0.1", port=5000, debug=True)

