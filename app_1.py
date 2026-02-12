from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
import os
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from utils.session_manager import init_session
from config.fusion_settings import DEFAULT_VALUES
from fusion_validator import validate_against_fusion
from fusion_client import create_supplier
from config.fusion_settings import REQUIRED_FIELDS

from gemini_agent import extract_supplier_payload

app = FastAPI()
security = HTTPBasic()


# ---------------- AUTH ----------------
def authenticate_user(credentials: HTTPBasicCredentials = Depends(security)):
    if (
        credentials.username == os.getenv("AGENT_USERNAME")
        and credentials.password == os.getenv("AGENT_PASSWORD")
    ):
        return credentials.username
    raise HTTPException(status_code=401, detail="Unauthorized")


# ---------------- REQUEST ----------------
class SupplierAgentRequest(BaseModel):
    message: str


# ---------------- SESSION ----------------
active_session = {
    "state": "INIT",
    "session": {}
}


@app.get("/")
def root():
    return {"status": "Supplier Agent Running"}


# =========================================================
# MAIN ENDPOINT
# =========================================================
@app.post("/supplier-agent")
def supplier_agent(payload: SupplierAgentRequest,
                   username: str = Depends(authenticate_user)):

    global active_session

    raw_input = payload.message.strip().strip("{}")
    intent_input = raw_input.lower()

    # -------------------------------------------------
    # GLOBAL RESTART
    # -------------------------------------------------
    if "create supplier" in intent_input:
        active_session = {
            "state": "COLLECTING",
            "session": init_session()
        }
        return {
            "reply": (
                "Sure — let’s create a supplier.\n"
                "Provide details in any order."
            )
        }

    # -------------------------------------------------
    # INIT
    # -------------------------------------------------
    if active_session["state"] == "INIT":
        return {"reply": 'Say "create supplier" to begin.'}

    # -------------------------------------------------
    # COLLECTING
    # -------------------------------------------------
    if active_session["state"] == "COLLECTING":

        session = active_session["session"]

        extracted = extract_supplier_payload(raw_input)

        for k, v in extracted.items():
            session[k] = v.strip() if isinstance(v, str) else v

        missing = [f for f in REQUIRED_FIELDS if not session.get(f)]

        if missing:

            collected_list = "\n".join(
                f"- {k}: {v}" for k, v in session.items() if v
            )

            missing_lines = []
            for field in missing:
                if field in DEFAULT_VALUES:
                    missing_lines.append(
                        f"- {field} (default: {DEFAULT_VALUES[field]})"
                    )
                else:
                    missing_lines.append(f"- {field}")

            missing_text = "\n".join(missing_lines)

            return {
                "reply": (
                    "Here’s what I have so far:\n\n"
                    + (collected_list if collected_list else "No details captured yet.")
                    + "\n\nI still need the following details:\n"
                    + missing_text
                )
            }

        # Validate
        errors = validate_against_fusion(session)
        if errors:
            return {"reply": f"Issue with {errors[0]}. Please correct."}

        active_session["state"] = "CONFIRM"

        summary = "\n".join(
            f"{f}: {session.get(f)}"
            for f in REQUIRED_FIELDS
        )

        return {
            "reply": f"Confirm supplier creation:\n{summary}\n\nYes / Edit / Cancel"
        }

    # -------------------------------------------------
    # CONFIRM
    # -------------------------------------------------
    if active_session["state"] == "CONFIRM":

        session = active_session["session"]

        if intent_input == "yes":

            status, response = create_supplier(session)

            active_session = {"state": "INIT", "session": {}}

            if status == 201:
                return {
                    "reply": "Supplier created successfully",
                    "SupplierId": response.get("SupplierId"),
                    "SupplierNumber": response.get("SupplierNumber")
                }

            return {"reply": "Fusion creation failed"}

        if intent_input == "edit":
            active_session["state"] = "COLLECTING"
            return {"reply": "Tell me updated values."}

        if intent_input == "cancel":
            active_session = {"state": "INIT", "session": {}}
            return {"reply": "Cancelled."}

        return {"reply": "Reply Yes / Edit / Cancel"}


# ---------------- RUN ----------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app_1:app", host="0.0.0.0", port=8007, reload=True)
