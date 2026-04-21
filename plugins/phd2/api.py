"""FastAPI router for PHD2 guiding control."""
import structlog
from fastapi import APIRouter, HTTPException, Request

from plugins.phd2.client import Phd2Client
from plugins.phd2.models import DebugRequest, DitherRequest, GuideRequest, Phd2Status
from plugins.phd2.settings import Phd2Settings

logger = structlog.get_logger()
router = APIRouter(prefix="/plugins/phd2", tags=["phd2"])


def _client(request: Request) -> Phd2Client:
    return request.app.state.phd2_client


@router.post("/connect", status_code=204)
async def connect(request: Request) -> None:
    """Start (or restart) the PHD2 connection loop using the current saved settings."""
    try:
        raw: dict = {}
        store = getattr(request.app.state, "profile_store", None)
        if store is not None:
            raw = store.get_user_settings().plugin_settings.get("phd2", {})
        cfg = Phd2Settings(**raw)
        await _client(request).reconnect(host=cfg.host, port=cfg.port)
    except Exception as exc:
        logger.warning("phd2.connect_failed", reason=str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/disconnect", status_code=204)
async def disconnect(request: Request) -> None:
    """Stop the PHD2 connection loop and close the socket."""
    try:
        await _client(request).stop()
    except Exception as exc:
        logger.warning("phd2.disconnect_failed", reason=str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/status", response_model=Phd2Status)
async def get_status(request: Request) -> Phd2Status:
    """Return current PHD2 connection state and guiding metrics."""
    return _client(request).get_status()


@router.post("/guide", status_code=204)
async def guide(body: GuideRequest, request: Request) -> None:
    """Start PHD2 guiding (calibrate if needed, then guide)."""
    try:
        await _client(request).guide(
            settle_pixels=body.settle.pixels,
            settle_time=body.settle.time,
            settle_timeout=body.settle.timeout,
            recalibrate=body.recalibrate,
        )
    except ConnectionError as exc:
        logger.warning("phd2.guide_failed", reason=str(exc))
        raise HTTPException(status_code=503, detail=str(exc))
    except TimeoutError:
        msg = "PHD2 did not respond to guide command (RPC timeout)"
        logger.warning("phd2.guide_failed", reason=msg)
        raise HTTPException(status_code=504, detail=msg)
    except Exception as exc:
        logger.warning("phd2.guide_failed", reason=str(exc))
        raise HTTPException(status_code=502, detail=f"PHD2: {exc}") from exc


@router.post("/stop", status_code=204)
async def stop(request: Request) -> None:
    """Stop PHD2 capture / guiding."""
    try:
        await _client(request).stop_capture()
    except ConnectionError as exc:
        logger.warning("phd2.stop_failed", reason=str(exc))
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.warning("phd2.stop_failed", reason=str(exc))
        raise HTTPException(status_code=502, detail=f"PHD2: {exc}") from exc


@router.post("/dither", status_code=204)
async def dither(body: DitherRequest, request: Request) -> None:
    """Dither the guide star and wait for settle."""
    try:
        await _client(request).dither(
            pixels=body.pixels,
            ra_only=body.ra_only,
            settle_pixels=body.settle.pixels,
            settle_time=body.settle.time,
            settle_timeout=body.settle.timeout,
        )
    except ConnectionError as exc:
        logger.warning("phd2.dither_failed", reason=str(exc))
        raise HTTPException(status_code=503, detail=str(exc))
    except TimeoutError as exc:
        logger.warning("phd2.dither_failed", reason=str(exc))
        raise HTTPException(status_code=504, detail=str(exc))
    except Exception as exc:
        logger.warning("phd2.dither_failed", reason=str(exc))
        raise HTTPException(status_code=502, detail=f"PHD2: {exc}") from exc


@router.post("/pause", status_code=204)
async def pause(request: Request) -> None:
    """Pause PHD2 guiding output (keeps looping, no corrections sent)."""
    try:
        await _client(request).pause()
    except ConnectionError as exc:
        logger.warning("phd2.pause_failed", reason=str(exc))
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.warning("phd2.pause_failed", reason=str(exc))
        raise HTTPException(status_code=502, detail=f"PHD2: {exc}") from exc


@router.post("/resume", status_code=204)
async def resume(request: Request) -> None:
    """Resume PHD2 guiding output after a pause."""
    try:
        await _client(request).resume()
    except ConnectionError as exc:
        logger.warning("phd2.resume_failed", reason=str(exc))
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.warning("phd2.resume_failed", reason=str(exc))
        raise HTTPException(status_code=502, detail=f"PHD2: {exc}") from exc


@router.post("/debug", status_code=204)
async def set_debug(req: DebugRequest, request: Request) -> None:
    """Enable or disable raw JSON-RPC traffic logging to the server console."""
    _client(request).set_debug(req.enabled)
