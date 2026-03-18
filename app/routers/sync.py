import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException

from ..services.vnstock_service import (
    get_stock_price_history,
    get_stock_fundamentals,
    get_all_symbols,
    DEFAULT_SYMBOLS,
)
from ..services.firestore_service import upsert_stock, upsert_price_history
from ..core.firebase import verify_token, get_db

router = APIRouter()
logger = logging.getLogger(__name__)


def _sync_one_symbol(symbol: str, start_date: str, end_date: str) -> int:
    """Sync price history + full fundamental data for one symbol."""
    fundamentals = get_stock_fundamentals(symbol)
    fundamentals["updatedAt"] = datetime.now(timezone.utc)
    upsert_stock(symbol, fundamentals)

    records = get_stock_price_history(symbol, start_date, end_date)
    for record in records:
        upsert_price_history(symbol, record["date"], record)
    return len(records)

def _utc_now():
    return datetime.now(timezone.utc)


def _job_ref(job_id: str):
    return get_db().collection("sync_jobs").document(job_id)


def _lock_ref():
    return get_db().collection("sync_locks").document("global")


def _acquire_global_lock(job_id: str, uid: str, full_market: bool) -> None:
    """
    Tránh nhiều người bấm Sync toàn thị trường cùng lúc gây rate limit.
    Cho phép 1 job chạy tại 1 thời điểm (đặc biệt full_market=true).
    """
    db = get_db()
    ref = _lock_ref()
    snap = ref.get()
    now = _utc_now()
    ttl = timedelta(minutes=30)

    if snap.exists:
        d = snap.to_dict() or {}
        if d.get("status") == "running":
            updated_at = d.get("updatedAt")
            if updated_at and now - updated_at <= ttl:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Đang có một sync job chạy. Vui lòng chờ hoàn tất.",
                        "job_id": d.get("job_id"),
                    },
                )

    ref.set(
        {
            "status": "running",
            "job_id": job_id,
            "uid": uid,
            "full_market": full_market,
            "updatedAt": now,
        },
        merge=True,
    )


def _release_global_lock(job_id: str) -> None:
    try:
        ref = _lock_ref()
        snap = ref.get()
        if snap.exists and (snap.to_dict() or {}).get("job_id") == job_id:
            ref.set({"status": "idle", "updatedAt": _utc_now()}, merge=True)
    except Exception:
        # Không làm fail job chỉ vì unlock
        pass


def _touch_lock(job_id: str) -> None:
    try:
        ref = _lock_ref()
        snap = ref.get()
        if snap.exists and (snap.to_dict() or {}).get("job_id") == job_id:
            ref.set({"updatedAt": _utc_now()}, merge=True)
    except Exception:
        pass


def _run_sync_job(job_id: str, uid: str, full_market: bool) -> None:
    """
    Chạy sync và cập nhật progress vào Firestore.
    Lỗi 1 mã sẽ ghi vào job.errors và tiếp tục mã tiếp theo.
    """
    ref = _job_ref(job_id)
    now = _utc_now()
    end_date = now.strftime("%Y-%m-%d")
    start_date = (now - timedelta(days=200)).strftime("%Y-%m-%d")

    symbols = get_all_symbols() if full_market else list(DEFAULT_SYMBOLS)
    total = len(symbols)

    ref.set(
        {
            "job_id": job_id,
            "uid": uid,
            "full_market": full_market,
            "status": "running",
            "createdAt": now,
            "startedAt": now,
            "updatedAt": now,
            "total_symbols": total,
            "processed": 0,
            "success": 0,
            "errors": 0,
            "current_symbol": None,
            "recent_errors": [],
        },
        merge=True,
    )

    processed = 0
    success = 0
    errors = 0
    recent_errors: list[dict] = []

    try:
        for sym in symbols:
            processed += 1
            try:
                ref.set({"current_symbol": sym, "updatedAt": _utc_now()}, merge=True)
                _touch_lock(job_id)

                # Catch cả SystemExit do vnstock rate limit in ra rồi exit()
                fundamentals = get_stock_fundamentals(sym)
                fundamentals["updatedAt"] = _utc_now()
                upsert_stock(sym, fundamentals)

                records = get_stock_price_history(sym, start_date, end_date)
                for record in records:
                    upsert_price_history(sym, record["date"], record)

                success += 1
            except BaseException as e:  # noqa: BLE001 - cần bắt cả SystemExit
                errors += 1
                msg = str(e)
                recent_errors.append(
                    {
                        "symbol": sym,
                        "error": msg[:500],
                        "at": _utc_now(),
                    }
                )
                # Giữ tối đa 15 lỗi gần nhất
                recent_errors = recent_errors[-15:]
                logger.error("Sync job %s failed %s: %s", job_id, sym, e)

            # Giảm số lần write progress (mỗi 10 mã hoặc khi kết thúc)
            if processed % 10 == 0 or processed == total:
                ref.set(
                    {
                        "processed": processed,
                        "success": success,
                        "errors": errors,
                        "recent_errors": recent_errors,
                        "updatedAt": _utc_now(),
                    },
                    merge=True,
                )

        ref.set(
            {
                "status": "done",
                "finishedAt": _utc_now(),
                "current_symbol": None,
                "processed": processed,
                "success": success,
                "errors": errors,
                "recent_errors": recent_errors,
                "updatedAt": _utc_now(),
            },
            merge=True,
        )
    except Exception as e:
        ref.set(
            {
                "status": "failed",
                "finishedAt": _utc_now(),
                "last_error": str(e)[:500],
                "updatedAt": _utc_now(),
            },
            merge=True,
        )
        raise
    finally:
        _release_global_lock(job_id)


async def _sync_stocks(full_market: bool = True) -> None:
    """Sync price history + fundamentals into Firestore.

    full_market=True: lấy toàn bộ mã từ VCI (get_all_symbols).
    full_market=False: chỉ sync DEFAULT_SYMBOLS (nhanh hơn).
    """
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=200)).strftime("%Y-%m-%d")

    symbols = get_all_symbols() if full_market else list(DEFAULT_SYMBOLS)
    logger.info("Sync starting: %d symbols (full_market=%s)", len(symbols), full_market)
    success_count = 0

    for symbol in symbols:
        try:
            count = await asyncio.to_thread(_sync_one_symbol, symbol, start_date, end_date)
            success_count += 1
            logger.info("Synced %s: %d records", symbol, count)
        except Exception as e:
            logger.error("Failed to sync %s: %s", symbol, e)

    logger.info("Sync complete: %d/%d stocks", success_count, len(symbols))


@router.post("")
async def trigger_sync(
    background_tasks: BackgroundTasks,
    full_market: bool = True,
):
    """
    Trigger data sync from vnstock into Firestore.
    full_market=True (default): sync toàn bộ mã từ VCI.
    full_market=False: chỉ sync danh sách mặc định (nhanh hơn).
    """
    background_tasks.add_task(_sync_stocks, full_market)
    return {
        "message": "Sync started",
        "full_market": full_market,
        "timestamp": datetime.now().isoformat(),
    }


@router.post("/jobs")
async def create_sync_job(
    background_tasks: BackgroundTasks,
    full_market: bool = True,
    authorization: str | None = Header(default=None),
):
    """
    Tạo một sync job có progress để FE theo dõi.
    Yêu cầu đăng nhập (Firebase token).
    """
    uid = verify_token(authorization)
    job_id = str(uuid.uuid4())

    # Global lock để tránh spam (đặc biệt full_market)
    _acquire_global_lock(job_id, uid, full_market)

    # Tạo job doc ngay để FE có thể poll lập tức
    _job_ref(job_id).set(
        {
            "job_id": job_id,
            "uid": uid,
            "full_market": full_market,
            "status": "queued",
            "createdAt": _utc_now(),
            "updatedAt": _utc_now(),
        },
        merge=True,
    )

    background_tasks.add_task(_run_sync_job, job_id, uid, full_market)
    return {"job_id": job_id, "status": "queued", "full_market": full_market}


@router.get("/jobs/{job_id}")
async def get_sync_job(job_id: str, authorization: str | None = Header(default=None)):
    """Lấy trạng thái job để hiển thị progress trên web."""
    verify_token(authorization)
    doc = _job_ref(job_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Job not found")
    d = doc.to_dict() or {}
    # Convert datetime to iso (frontend-friendly)
    for k in ("createdAt", "startedAt", "finishedAt", "updatedAt"):
        if isinstance(d.get(k), datetime):
            d[k] = d[k].isoformat()
    # recent_errors[].at
    if isinstance(d.get("recent_errors"), list):
        for item in d["recent_errors"]:
            if isinstance(item.get("at"), datetime):
                item["at"] = item["at"].isoformat()
    return d
