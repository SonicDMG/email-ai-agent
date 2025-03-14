from fastapi import FastAPI, Request
import uvicorn
import json
import requests
import logging
import sys
from json_repair import repair_json
import unicodedata

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("webhook.log"),  # Log to a file
        logging.StreamHandler(sys.stdout)    # Also log to console
    ]
)
logger = logging.getLogger("webhook_handler")

app = FastAPI(title="Email AI Agent Webhook Handler")

# Langflow API details
LANGFLOW_API_URL = "http://localhost:7860"  # Change to your Langflow URL

# Create a translation table that maps control characters to None
CONTROL_CHAR_TABLE = str.maketrans("", "", "".join(chr(i) for i in range(32)) + chr(127))

def clean_json_data(data):
    """Clean JSON data to ensure it can be properly serialized"""
    if isinstance(data, dict):
        return {k: clean_json_data(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [clean_json_data(item) for item in data]
    elif isinstance(data, str):
        # Remove control characters
        cleaned = data.translate(CONTROL_CHAR_TABLE)
        # Normalize Unicode
        cleaned = unicodedata.normalize("NFC", cleaned)
        return cleaned
    else:
        return data

@app.post("/webhook")
async def webhook(request: Request):
    """Handle incoming webhook from Gmail"""
    try:
        # Get raw request body and try to repair if needed
        raw_body = await request.body()
        raw_text = raw_body.decode('utf-8')

        # Find the JSON object boundaries
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start != -1 and end != -1 and end > start:
            raw_text = raw_text[start:end+1]

        try:
            # First try standard parsing
            payload = json.loads(raw_text)
        except json.JSONDecodeError:
            # If that fails, try to repair the JSON
            logger.info("Attempting to repair malformed JSON")
            repaired_text = repair_json(raw_text)
            payload = json.loads(repaired_text)
            logger.info("JSON successfully repaired")
        
        # Log the full payload for testing
        logger.info("Received webhook: %s", json.dumps(payload, indent=2))

        # Extract the data from the payload
        data = payload.get("data", payload)

        # Create a filtered payload without the large 'payload' object
        filtered_data = {
            "to": data.get("to"),
            "sender": data.get("sender"),
            "subject": data.get("subject"),
            "messageText": data.get("messageText", ""),
            "messageTimestamp": data.get("messageTimestamp"),
            "threadId": data.get("threadId"),
            "messageId": data.get("messageId")
        }

        # Clean the filtered data to ensure it can be properly serialized
        filtered_data = clean_json_data(filtered_data)
        
        # Truncate very long messages if needed
        if len(filtered_data.get("messageText", "")) > 10000:
            filtered_data["messageText"] = filtered_data["messageText"][:10000] + "... (truncated)"

        # Log the full filtered data for testing
        logger.info("Sending to Langflow: %s", json.dumps(filtered_data, indent=2))

        response = requests.post(
            f"{LANGFLOW_API_URL}/api/v1/webhook/email_ai_agent_ingest",
            json=filtered_data,
            timeout=10
        )

        logger.info("Forwarded to Langflow, status: %d, response: %s", response.status_code, response.text)
        return {"status": "success", "message": "Webhook received and processed"}

    except Exception as e:
        logger.error("Error processing webhook: %s", str(e), exc_info=True)
        return {"status": "error", "message": str(e)}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    logger.info("Health check called")
    return {"status": "healthy"}

# Main entry point
if __name__ == "__main__":
    logger.info("Starting webhook server on port 8000...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
