import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services.inference import predict

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/recognize")
async def ws_recognize(websocket: WebSocket):
    """
    WebSocket endpoint for real-time sign recognition.

    Client sends JSON:
      {"mode": "static"|"dynamic", "hands": [...], "face": {...}?

    Server responds with JSON:
      {"predicted_label": "...", "spanish_text": "...", "confidence": 0.94, "mode": "..."}
    """
    await websocket.accept()
    logger.info("WebSocket connected")

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"error": "JSON inválido"})
                continue

            mode = data.get("mode", "static")
            hands = data.get("hands", [])
            face = data.get("face")

            if mode not in ("static", "dynamic"):
                await websocket.send_json({"error": "mode debe ser 'static' o 'dynamic'"})
                continue

            if not hands:
                await websocket.send_json({"error": "Se requiere al menos una mano"})
                continue

            try:
                result = predict(mode, hands, face)
                await websocket.send_json(result)
            except Exception as e:
                logger.error(f"Inference error: {e}")
                await websocket.send_json({"error": "Error en inferencia"})

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
