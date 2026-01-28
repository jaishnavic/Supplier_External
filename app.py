from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
import uuid
import os

from fastapi.security import HTTPBasic, HTTPBasicCredentials

from gemini_agent import extract_supplier_payload
from utils.session_manager import init_session, merge_session, get_missing_fields
from fusion_validator import validate_against_fusion
from fusion_client import create_supplier
from config.fusion_settings import FIELD_QUESTIONS, REQUIRED_FIELDS

app = FastAPI()

# ---------------- AUTH ----------------
security = HTTPBasic()

def authenticate_user(credentials: HTTPBasicCredentials = Depends(security)):
    if (
        credentials.username == os.getenv("BOT_USERNAME")
        and credentials.password == os.getenv("BOT_PASSWORD")
    ):
        return credentials.username
    raise HTTPException(status_code=401, detail="Unauthorized")

# -------------------------------
# Request schema
# -------------------------------
class SupplierAgentRequest(BaseModel):
    message: str

# -------------------------------
# Single active session (Agent Studio)
# -------------------------------
active_session = None


@app.post("/supplier-agent")
def supplier_agent(
    payload: SupplierAgentRequest,
    username: str = Depends(authenticate_user)
):
    global active_session
    user_input = payload.message.strip().lower()

    # -------------------------------
    # INIT SESSION
    # -------------------------------
    if not active_session:
        session = init_session()

        extracted = extract_supplier_payload(payload.message)
        session = merge_session(session, extracted)

        missing = get_missing_fields(session)
        current_field = missing[0] if missing else None

        active_session = {
            "session": session,
            "current_field": current_field,
            "state": "COLLECTING"
        }

        if current_field:
            return {"reply": FIELD_QUESTIONS[current_field]}

    state = active_session
    session = state["session"]
    current_field = state["current_field"]
    mode = state["state"]

    # -------------------------------
    # CONFIRM MODE
    # -------------------------------
    if mode == "CONFIRM":
        if user_input == "yes":
            status, response = create_supplier(session)
            active_session = None

            if status == 201:
                return {
                    "reply": "Supplier created successfully",
                    "data": {
                        "SupplierId": response.get("SupplierId"),
                        "SupplierNumber": response.get("SupplierNumber")
                    }
                }

            return {"status": "ERROR","reply": "Supplier creation failed","details": response}

        if user_input == "edit":
            state["state"] = "EDIT"
            return {
                "reply": (
                    "Which field do you want to edit?\n"
                    + "\n".join(
                        f"{i+1}. {f}" for i, f in enumerate(REQUIRED_FIELDS)
                    )
                )
            }

        if user_input == "cancel":
            active_session = None
            return {"reply": "Supplier creation cancelled."}

        return {
            "reply": "Please type Yes, Edit, or Cancel."
        }

    # -------------------------------
    # EDIT MODE
    # -------------------------------
    if mode == "EDIT":
        field_map = {str(i + 1): f for i, f in enumerate(REQUIRED_FIELDS)}

        if user_input in field_map:
            field = field_map[user_input]
            state["current_field"] = field
            state["state"] = "COLLECTING"
            return {"reply": FIELD_QUESTIONS[field]}

        return {"reply": "Invalid choice. Please enter a valid number."}

    # -------------------------------
    # COLLECTING MODE
    # -------------------------------
    if current_field:
        if len(payload.message.split()) > 3:
            extracted = extract_supplier_payload(payload.message)
            session = merge_session(session, extracted)

            if not session.get(current_field):
                session[current_field] = payload.message
        else:
            session[current_field] = payload.message

    state["session"] = session
    state["current_field"] = None

    # -------------------------------
    # NEXT FIELD
    # -------------------------------
    missing = get_missing_fields(session)
    if missing:
        next_field = missing[0]
        state["current_field"] = next_field
        return {"reply": FIELD_QUESTIONS[next_field]}

    # -------------------------------
    # VALIDATION
    # -------------------------------
    errors = validate_against_fusion(session)
    if errors:
        field = REQUIRED_FIELDS[0]
        state["current_field"] = field
        return {
            "reply": (
                "There are validation issues:\n"
                + "\n".join(errors)
                + f"\n\n{FIELD_QUESTIONS[field]}"
            )
        }

    # -------------------------------
    # CONFIRM SUMMARY
    # -------------------------------
    summary = "\n".join(
        f"{f}: {session.get(f)}" for f in REQUIRED_FIELDS
    )

    state["state"] = "CONFIRM"
    return {
        "reply": (
            "Please review the supplier details:\n\n"
            + summary
            + "\n\nType Yes to submit, Edit to change, or Cancel."
        )
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8009)
