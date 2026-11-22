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

    Modes:
      - static/dynamic: {"mode":"static","hands":[...]}
      - lsch_v3: {"mode":"lsch_v3","frames":[[1629 floats], ...], "top_k":3}
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
            frames = data.get("frames")
            top_k = data.get("top_k", 3)

            if mode not in ("static", "dynamic", "lsch_v3"):
                await websocket.send_json({"error": "mode debe ser 'static', 'dynamic' o 'lsch_v3'"})
                continue

            if mode == "lsch_v3":
                if not isinstance(frames, list) or len(frames) == 0:
                    await websocket.send_json({"error": "Se requieren frames para mode='lsch_v3'"})
                    continue
            elif not hands:
                await websocket.send_json({"error": "Se requiere al menos una mano"})
                continue

            try:
                result = predict(mode, hands, face, frames=frames, top_k=top_k)
                await websocket.send_json(result)
            except Exception as e:
                logger.exception("Inference error: %s", e)
                await websocket.send_json({"error": "Error en inferencia"})

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
