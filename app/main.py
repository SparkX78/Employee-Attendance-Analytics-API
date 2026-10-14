"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from contextlib import asynccontextmanager
from dotenv import load_dotenv
from decimal import Decimal, ROUND_HALF_UP                          #----------- FIX 17--------#
from fastapi import FastAPI, HTTPException, Query                   #---------- FIX 15---------#
from pydantic import BaseModel, StrictInt, field_validator, Field                         #------------FIX 11--------#
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError                        #------------FIX 9-------#
from zoneinfo import ZoneInfo
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

load_dotenv()                                                     #-----FIX 1--------#

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "attendance_db")

client = MongoClient(MONGO_URI)
db = client[MONGO_DB]

IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Unique employee code
    db.employees.create_index(
        [("emp_code", 1)],
        unique=True 
    )

    # One attendance record per employee per day
    db.attendance_logs.create_index(
        [("emp_code", 1), ("date", 1)],
        unique=True,
        
    )

    # Attendance listing and date-based analytics
    db.attendance_logs.create_index(
        [("date", -1), ("emp_code", 1)],
        name="idx_attendance_date_emp"
    )

    # Employee history and monthly analytics
    db.attendance_logs.create_index(
        [("emp_code", 1), ("date", -1)],
        name="idx_attendance_emp_date"
    )

    # Status and date filtering
    db.attendance_logs.create_index(
        [("status", 1), ("date", -1)],
        name="idx_attendance_status_date"
    )

    yield


app = FastAPI(
    title="Employee Attendance & Analytics API",
    version="2.0.0",
    lifespan=lifespan
)


def explain_mongo_command(command: dict) -> dict:
    """Return MongoDB executionStats for a find or aggregation command."""
    try:
        result = db.command(
            "explain",
            command,
            verbosity="executionStats"
        )
        return result
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"MongoDB explain failed: {str(exc)}"
        )




# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def to_ist(value: datetime) -> datetime:
    if value.tzinfo is None:                                                            #------------FIX 24------#
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(IST)

def to_epoch_ms(value: Optional[datetime]) -> Optional[int]:                              #---------FIX 29--------#
    if value is None:
        return None

    value = to_ist(value)

    return int(value.timestamp() * 1000)


def compute_late_minutes(
    punch_in: datetime,
    shift_start: str,
    shift_end: str
) -> int:
    start_hour, start_minute = map(int, shift_start.split(":"))
    end_hour, end_minute = map(int, shift_end.split(":"))

    start = punch_in.replace(
        hour=start_hour,
        minute=start_minute,                                                             #------------FIX 16--------#
        second=0,
        microsecond=0
    )

    # If this is an overnight shift and punch-in is
    # before the scheduled end time, the shift started yesterday.
    if (
        (end_hour, end_minute) <= (start_hour, start_minute)
        and (punch_in.hour, punch_in.minute) < (end_hour, end_minute)
    ):
        start -= timedelta(days=1)

    elapsed_seconds = (punch_in - start).total_seconds()

    # Ten-minute grace period.
    if elapsed_seconds <= 600:
        return 0

    return int(elapsed_seconds // 60)


def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:           #------------FIX 17-----------#
    seconds = int((punch_out - punch_in).total_seconds())

    hours = Decimal(seconds) / Decimal(3600)

    return float(
        hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )


def compute_overtime(
    punch_out: datetime,
    shift_start: str,
    shift_end: str,
    date_str: str
) -> int:
    start_hour, start_minute = map(int, shift_start.split(":"))
    end_hour, end_minute = map(int, shift_end.split(":"))                                 #----------FIX 18--------#

    end = datetime.fromisoformat(date_str).replace(
        hour=end_hour,
        minute=end_minute,
        second=0,
        microsecond=0,
        tzinfo=IST
    )

    # Overnight shift: scheduled end is on the next day.
    if (end_hour, end_minute) <= (start_hour, start_minute):
        end += timedelta(days=1)

    overtime_seconds = (punch_out - end).total_seconds()

    # Overtime is counted only when extra work is at least 30 minutes.
    if overtime_seconds < 1800:
        return 0

    return int(overtime_seconds // 60)

# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class EmployeeIn(BaseModel):
    emp_code: str
    name: str
    email: str
    department: str
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str


class PunchInIn(BaseModel):                                     #------------FIX 4-------#
    emp_code: str
    punched_at: Optional[StrictInt] = None
    status: str = "PRESENT"

class PunchOutIn(BaseModel):                                        #-------------FIX 21---------#
    emp_code: str
    punched_at: Optional[StrictInt] = None

class RegularizeIn(BaseModel):
    status: Optional[str] = None
    punch_in: Optional[StrictInt] = None
    punch_out: Optional[StrictInt] = None
    reason: str = Field(min_length=5, max_length=200)
    regularized_by: str = Field(min_length=1, max_length=50)

    @field_validator("status")                                             #-------FIX 31-------#
    @classmethod
    def validate_status(cls, value):
        if value is not None and value not in {
            "PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"
        }:
            raise ValueError("Invalid attendance status")
        return value

def attendance_status_counts_as_present(status: str) -> bool:       #---------FIX 32-------#
    return status in {"PRESENT", "WFH", "ON_DUTY"}



def validate_punched_at(value: Optional[int]) -> None:                 #------------- FIX 5 -------- #
    if value is None:
        return

    if value <= 0:
        raise HTTPException(status_code=422, detail="Invalid timestamp")

    if value < 100_000_000_000:
        raise HTTPException(status_code=422, detail="Timestamp must be in milliseconds")

    if value > 4_102_444_800_000:                                                  #-----------FIX 22----------#
        raise HTTPException(
            status_code=422,
            detail="Timestamp out of range"
        )

    try:
        datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        raise HTTPException(status_code=422, detail="Timestamp out of range")

# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #
@app.get("/health")                                               #-----------FIX 2---------#
def health():
    try:
        db.command("ping")
        return {"status": "ok"}
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable")


@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    if db.employees.find_one({"emp_code": body.emp_code}):
        raise HTTPException(409, "emp_code already exists")
    doc = body.model_dump()                                       #-------------FIX 8--------#
    doc["created_at"] = datetime.now(IST)

    try:
        db.employees.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="emp_code already exists")

    doc["created_at"] = to_epoch_ms(doc["created_at"])

    doc.pop("_id", None)
    return doc


@app.get("/employees")
def list_employees(department: Optional[str] = None, page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),):   #--------FIX 12------#

    q = {}
    if department:
        q["department"] = department
    skip = (page - 1) * page_size                                        #----------FIX 9---------#
    total = db.employees.count_documents(q)
    items = list(
    db.employees.find(q, {"_id": 0})
    .sort("emp_code", 1)
    .skip(skip)
    .limit(page_size)
    )                                                                   #-------------FIX 13--------#

    for item in items:
        item["created_at"] = to_epoch_ms(item.get("created_at"))
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.post("/attendance/punch-in", status_code=201)                       #---------------FIX 6---------#
def punch_in(body: PunchInIn):
    validate_punched_at(body.punched_at)

    if body.status not in {"PRESENT", "WFH", "ON_DUTY"}:
        raise HTTPException(status_code=422, detail="Invalid attendance status")

    emp = db.employees.find_one({"emp_code": body.emp_code})
    if emp is None:
        raise HTTPException(status_code=404, detail="Employee not found")        #------- FIX 7------#
    if body.punched_at is not None:
        ts = datetime.fromtimestamp(body.punched_at / 1000, tz=timezone.utc).astimezone(IST)
    else:
        ts = datetime.now(IST)
    ts = ts.replace(microsecond=0)                                                #FIX 20 -----------#
    start_hour, start_minute = map(int, emp["shift_start"].split(":"))
    end_hour, end_minute = map(int, emp["shift_end"].split(":"))                        #------------FIX 19------#

    is_overnight = (end_hour, end_minute) <= (start_hour, start_minute)

    attendance_date = ts.date()

    if is_overnight and (ts.hour, ts.minute) < (end_hour, end_minute):
        attendance_date -= timedelta(days=1)

    d = attendance_date.isoformat()
    if db.attendance_logs.find_one({"emp_code": body.emp_code, "date": d}):
        raise HTTPException(409, "already punched in for this date")
    doc = {
        "emp_code": body.emp_code,
        "date": d,
        "status": body.status,
        "punch_in": ts,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes( ts, emp["shift_start"], emp["shift_end"] ),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }
    try:
        db.attendance_logs.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="already punched in for this date"
        )

    doc.pop("_id", None)
    return doc

@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):                                            #-------------FIX 23--------#
    validate_punched_at(body.punched_at)

    if body.punched_at is not None:
        ts = datetime.fromtimestamp(
            body.punched_at / 1000,
            tz=timezone.utc
        ).astimezone(IST)
    else:
        ts = datetime.now(IST)

    ts = ts.replace(microsecond=0)

    emp = db.employees.find_one({"emp_code": body.emp_code})

    if emp is None:
        raise HTTPException(status_code=404, detail="Employee not found")               #-----------FIX 24------#

    record = db.attendance_logs.find_one(
        {
            "emp_code": body.emp_code,
            "punch_in": {"$lte": ts}
        },
        sort=[("punch_in", -1)]
    )

    if record is None:
        raise HTTPException(
            status_code=404,
            detail="No punch-in found"
        )

    if record.get("punch_out") is not None:
        raise HTTPException(
            status_code=409,
            detail="Already punched out"
        )

    punch_in_time = to_ist(record["punch_in"])

    if ts <= punch_in_time:
        raise HTTPException(
            status_code=422,
            detail="Punch-out must be after punch-in"
        )

    work_hours = compute_work_hours(                                                       #---------FIX 24------#
        punch_in_time,
        ts
    )

    overtime_minutes = compute_overtime(                                                   #---------FIX 25-------#
        ts,
        emp["shift_start"],
        emp["shift_end"],
        record["date"]
    )

    half_day = work_hours < 4.50                                                            #---------FIX 26------#

    result = db.attendance_logs.update_one(
        {
            "_id": record["_id"],
            "punch_out": None
        },
        {
            "$set": {
                "punch_out": ts,
                "work_hours": work_hours,
                "overtime_minutes": overtime_minutes,                                       #----------FIX 27------#
                "half_day": half_day
            }
        }
    )

    if result.modified_count == 0:
        raise HTTPException(
            status_code=409,
            detail="Already punched out"
        )

    updated_record = db.attendance_logs.find_one(
        {"_id": record["_id"]},                                                             #-------FIX 28-------#
        {"_id": 0}
    )

    updated_record["punch_in"] = to_epoch_ms(
        updated_record["punch_in"]
    )

    updated_record["punch_out"] = to_epoch_ms(
        updated_record["punch_out"]
    )

    return updated_record



@app.patch("/attendance/{emp_code}/{date}")
def regularize_attendance(
    emp_code: str,
    date: str,
    data: RegularizeIn
):
    # Validate the attendance date.
    try:
        attendance_date = datetime.strptime(date, "%Y-%m-%d").date()
        if attendance_date.isoformat() != date:
            raise ValueError
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Invalid date format. Use YYYY-MM-DD"
        )

    employee = db.employees.find_one({"emp_code": emp_code})

    if employee is None:
        raise HTTPException(
            status_code=404,
            detail="Employee not found"
        )

    record = db.attendance_logs.find_one({
        "emp_code": emp_code,
        "date": date
    })

    if record is None:
        raise HTTPException(
            status_code=404,
            detail="Attendance record not found"
        )

    new_status = (
        data.status
        if data.status is not None
        else record.get("status", "PRESENT")
    )

    if new_status not in {"PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"}:
        raise HTTPException(
            status_code=422,
            detail="Invalid attendance status"
        )

    if new_status in {"ABSENT", "LEAVE"}:
        if data.punch_in is not None or data.punch_out is not None:
            raise HTTPException(
                status_code=422,
                detail="ABSENT or LEAVE cannot have punch times"
            )

    if data.punch_in is not None:
        validate_punched_at(data.punch_in)

    if data.punch_out is not None:
        validate_punched_at(data.punch_out)

    new_punch_in = (
        data.punch_in
        if data.punch_in is not None
        else to_epoch_ms(record.get("punch_in"))
    )

    new_punch_out = (
        data.punch_out
        if data.punch_out is not None
        else to_epoch_ms(record.get("punch_out"))
    )

    if attendance_status_counts_as_present(new_status):
        if new_punch_in is None:
            raise HTTPException(
                status_code=422,
                detail="Present attendance requires a punch-in time"
            )

    if new_punch_out is not None:
        if new_punch_in is None:
            raise HTTPException(
                status_code=422,
                detail="Punch-out requires a punch-in time"
            )

        if new_punch_out <= new_punch_in:
            raise HTTPException(
                status_code=422,
                detail="Punch-out must be after punch-in"
            )

        if new_punch_out - new_punch_in > 24 * 60 * 60 * 1000:
            raise HTTPException(
                status_code=422,
                detail="Punch-out cannot be more than 24 hours after punch-in"
            )

    if new_status in {"ABSENT", "LEAVE"}:
        new_punch_in = None
        new_punch_out = None

    # Truncate input timestamps to whole seconds before calculations.
    if new_punch_in is not None:
        new_punch_in = (new_punch_in // 1000) * 1000

    if new_punch_out is not None:
        new_punch_out = (new_punch_out // 1000) * 1000

    if (
        new_punch_in is not None
        and new_punch_out is not None
        and new_punch_out <= new_punch_in
    ):
        raise HTTPException(
            status_code=422,
            detail="Punch-out must be after punch-in"
        )

    punch_in_dt = (
        datetime.fromtimestamp(
            new_punch_in / 1000,
            tz=timezone.utc
        ).astimezone(ZoneInfo("Asia/Kolkata"))
        if new_punch_in is not None
        else None
    )

    punch_out_dt = (
        datetime.fromtimestamp(
            new_punch_out / 1000,
            tz=timezone.utc
        ).astimezone(ZoneInfo("Asia/Kolkata"))
        if new_punch_out is not None
        else None
    )

    late_minutes = 0
    work_hours = None
    overtime_minutes = 0
    half_day = False

    if punch_in_dt is not None:
        late_minutes = compute_late_minutes(
            punch_in_dt,
            employee["shift_start"],
            employee["shift_end"]
        )

    if punch_in_dt is not None and punch_out_dt is not None:
        work_hours = compute_work_hours(
            punch_in_dt,
            punch_out_dt
        )

        overtime_minutes = compute_overtime(
            punch_out_dt,
            employee["shift_start"],
            employee["shift_end"],
            date
        )

        half_day = work_hours < 4.5

    changes = {}

    old_status = record.get("status", "PRESENT")
    if old_status != new_status:
        changes["status"] = {
            "from": old_status,
            "to": new_status
        }

    old_punch_in = to_epoch_ms(record.get("punch_in"))
    if old_punch_in != new_punch_in:
        changes["punch_in"] = {
            "from": old_punch_in,
            "to": new_punch_in
        }

    old_punch_out = to_epoch_ms(record.get("punch_out"))
    if old_punch_out != new_punch_out:
        changes["punch_out"] = {
            "from": old_punch_out,
            "to": new_punch_out
        }

    calculated_fields = {
        "late_minutes": late_minutes,
        "work_hours": work_hours,
        "overtime_minutes": overtime_minutes,
        "half_day": half_day
    }

    for field, new_value in calculated_fields.items():
        old_value = record.get(field)

        if old_value != new_value:
            changes[field] = {
                "from": old_value,
                "to": new_value
            }

    if not changes:
        raise HTTPException(
            status_code=422,
            detail="No changes to regularize"
        )

    history_entry = {
        "at": datetime.now(timezone.utc),
        "by": data.regularized_by,
        "reason": data.reason,
        "changes": changes
    }

    # Compare-and-update protects against concurrent regularization.
    update_result = db.attendance_logs.update_one(
        {
            "_id": record["_id"],
            "history": record.get("history", [])
        },
        {
            "$set": {
                "status": new_status,
                "punch_in": (
                    punch_in_dt.astimezone(timezone.utc)
                    if punch_in_dt else None
                ),
                "punch_out": (
                    punch_out_dt.astimezone(timezone.utc)
                    if punch_out_dt else None
                ),
                "late_minutes": late_minutes,
                "work_hours": work_hours,
                "overtime_minutes": overtime_minutes,
                "half_day": half_day
            },
            "$push": {"history": history_entry}
        }
    )

    if update_result.modified_count == 0:
        raise HTTPException(
            status_code=409,
            detail="Attendance record changed concurrently; retry the request"
        )

    updated_record = db.attendance_logs.find_one(
        {"_id": record["_id"]}
    )

    if updated_record is None:
        raise HTTPException(
            status_code=404,
            detail="Attendance record not found after update"
        )

    updated_record.pop("_id", None)

    updated_record["punch_in"] = to_epoch_ms(
        updated_record.get("punch_in")
    )
    updated_record["punch_out"] = to_epoch_ms(
        updated_record.get("punch_out")
    )

    for entry in updated_record.get("history", []):
        entry["at"] = to_epoch_ms(entry.get("at"))

        # Normalize older persisted history entries as well.
        entry["changes"] = {
            field: {
                "from": values.get("from", values.get("before")),
                "to": values.get("to", values.get("after"))
            }
            for field, values in entry.get("changes", {}).items()
        }

    return updated_record



@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly_analytics(
    emp_code: str,
    year: int,
    month: int
):
    if month < 1 or month > 12:
        raise HTTPException(
            status_code=422,
            detail="Month must be between 1 and 12"
        )

    if year < 2000 or year > 2100:
        raise HTTPException(
            status_code=422,
            detail="Year must be between 2000 and 2100"
        )

    employee = db.employees.find_one({"emp_code": emp_code})

    if employee is None:
        raise HTTPException(
            status_code=404,
            detail="Employee not found"
        )

    start_date = f"{year:04d}-{month:02d}-01"

    if month == 12:
        end_date = f"{year + 1:04d}-01-01"
    else:
        end_date = f"{year:04d}-{month + 1:02d}-01"

    records = list(db.attendance_logs.find({
        "emp_code": emp_code,
        "date": {
            "$gte": start_date,
            "$lt": end_date
        }
    }))

    total_records = len(records)

    # Calculate working weekdays from the later of
    # the month start or the employee's joining date.
    month_start = date(year, month, 1)

    if month == 12:
        next_month_start = date(year + 1, 1, 1)
    else:
        next_month_start = date(year, month + 1, 1)

    month_end = next_month_start - timedelta(days=1)
    joined_on = date.fromisoformat(employee["joined_on"])
    effective_start = max(month_start, joined_on)

    working_days = 0
    current_day = effective_start

    while current_day <= month_end:
        if current_day.weekday() < 5:
            working_days += 1
        current_day += timedelta(days=1)

    # Present statuses count as present; half-days count as 0.5.
    
    present_days = sum(
        0.5 if record.get("half_day", False) else 1
        for record in records
        if (
            attendance_status_counts_as_present(
                record.get("status", "PRESENT")
            )
            and date.fromisoformat(record["date"]).weekday() < 5
        )
    )


    absent_days = sum(
        1 for record in records
        if record.get("status") == "ABSENT"
    )

    leave_days = sum(
        1 for record in records
        if record.get("status") == "LEAVE"
    )

    total_work_hours = float(
        Decimal(str(sum(
            float(record.get("work_hours") or 0)
            for record in records
        ))).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )
    )

    late_days = sum(
        1 for record in records
        if record.get("late_minutes", 0) > 0
    )

    total_overtime_minutes = sum(
        int(record.get("overtime_minutes") or 0)
        for record in records
    )

    half_days = sum(
        1 for record in records
        if record.get("half_day", False) is True
    )

    attendance_pct = (
        float(
            Decimal(str(present_days / working_days * 100)).quantize(
                Decimal("0.0001"),
                rounding=ROUND_HALF_UP
            )
        )
        if working_days > 0
        else None
    )

    return {
        "emp_code": emp_code,
        "name": employee["name"],
        "department": employee["department"],
        "year": year,
        "month": month,
        "total_records": total_records,
        "working_days": working_days,
        "present_days": present_days,
        "absent_days": absent_days,
        "leave_days": leave_days,
        "total_work_hours": total_work_hours,
        "late_days": late_days,
        "total_overtime_minutes": total_overtime_minutes,
        "half_days": half_days,
        "attendance_pct": attendance_pct
    }


@app.get("/analytics/departments/summary")
def department_summary(
    year: int,
    month: int
):
    if month < 1 or month > 12:
        raise HTTPException(
            status_code=422,
            detail="Month must be between 1 and 12"
        )

    if year < 2000 or year > 2100:
        raise HTTPException(
            status_code=422,
            detail="Year must be between 2000 and 2100"
        )

    start_date, end_date = get_month_date_range(year, month)

    # Include employees who joined by the end of this month,
    # even if they have no attendance records.
    month_end = date.fromisoformat(end_date) - timedelta(days=1)

    employees = list(db.employees.find({
        "joined_on": {"$lte": month_end.isoformat()}
    }))

    employees_by_code = {
        employee["emp_code"]: employee
        for employee in employees
    }

    records = list(db.attendance_logs.find({
        "date": {
            "$gte": start_date,
            "$lt": end_date
        }
    }))

    # Initialize one summary per department so departments with
    # zero attendance records are also included.
    department_records = {}

    for employee in employees:
        department = employee["department"]

        if department not in department_records:
            department_records[department] = []

    for record in records:
        emp_code = record.get("emp_code")
        employee = employees_by_code.get(emp_code)

        if employee is None:
            continue

        department = employee["department"]
        department_records.setdefault(department, []).append(record)

    summary = []

    for department in sorted(department_records):
        dept_records = department_records[department]

        present_days = 0.0
        absent_days = 0
        leave_days = 0
        on_duty_count = 0
        late_count = 0
        total_late_minutes = 0
        total_work_hours = 0.0
        work_hour_records = 0

        for record in dept_records:
            status = record.get("status", "PRESENT")

            # Present days count only on weekdays.
            is_weekday = (
                date.fromisoformat(record["date"]).weekday() < 5
            )

            if (
                is_weekday
                and attendance_status_counts_as_present(status)
            ):
                present_days += (
                    0.5 if record.get("half_day", False) else 1.0
                )

            if status == "ABSENT":
                absent_days += 1

            if status == "LEAVE":
                leave_days += 1

            if status == "ON_DUTY":
                on_duty_count += 1

            late_minutes = int(record.get("late_minutes") or 0)

            if late_minutes > 0:
                late_count += 1
                total_late_minutes += late_minutes

            # Average only records with a non-null work_hours value
            # and a present status.
            if (
                attendance_status_counts_as_present(status)
                and record.get("work_hours") is not None
            ):
                total_work_hours += float(record["work_hours"])
                work_hour_records += 1

        total_work_hours = float(
            Decimal(str(total_work_hours)).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP
            )
        )

        avg_work_hours = (
            float(
                Decimal(
                    str(total_work_hours / work_hour_records)
                ).quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP
                )
            )
            if work_hour_records > 0
            else None
        )

        summary.append({
            "department": department,
            "headcount": sum(
                1 for employee in employees
                if employee["department"] == department
            ),
            "total_records": len(dept_records),
            "present_days": present_days,
            "absent_days": absent_days,
            "leave_days": leave_days,
            "total_work_hours": total_work_hours,
            "avg_work_hours": avg_work_hours,
            "late_count": late_count,
            "total_late_minutes": total_late_minutes,
            "on_duty_count": on_duty_count
        })

    return {
        "year": year,
        "month": month,
        "departments": summary
    }


@app.get("/analytics/leaderboard/late")
def late_arrival_leaderboard(
    year: int,
    month: int,
    limit: int = 10,
    department: Optional[str] = None
):
    if month < 1 or month > 12:
        raise HTTPException(
            status_code=422,
            detail="Month must be between 1 and 12"
        )

    if year < 2000 or year > 2100:
        raise HTTPException(
            status_code=422,
            detail="Year must be between 2000 and 2100"
        )

    if limit < 1 or limit > 100:
        raise HTTPException(
            status_code=422,
            detail="Limit must be between 1 and 100"
        )

    start_date, end_date = get_month_date_range(year, month)

    match_stage = {
        "date": {
            "$gte": start_date,
            "$lt": end_date
        },
        "late_minutes": {"$gt": 0}
    }

    pipeline = [
        {"$match": match_stage},
        {
            "$group": {
                "_id": "$emp_code",
                "total_late_minutes": {"$sum": "$late_minutes"},
                "late_days": {"$sum": 1}
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "localField": "_id",
                "foreignField": "emp_code",
                "as": "employee"
            }
        },
        {"$unwind": "$employee"}
    ]

    if department is not None:
        pipeline.append({
            "$match": {"employee.department": department}
        })

    pipeline.extend([
        {
            "$setWindowFields": {
                "sortBy": {"total_late_minutes": -1},
                "output": {
                    "rank": {"$rank": {}}
                }
            }
        },
        {"$sort": {"total_late_minutes": -1, "_id": 1}},
        {"$match": {"rank": {"$lte": limit}}},
        {
            "$project": {
                "_id": 0,
                "emp_code": "$_id",
                "name": "$employee.name",
                "department": "$employee.department",
                "total_late_minutes": 1,
                "late_days": 1,
                "rank": 1
            }
        }
    ])

    leaderboard = list(db.attendance_logs.aggregate(pipeline))

    return {
        "year": year,
        "month": month,
        "leaderboard": leaderboard
    }






@app.get("/analytics/departments/{department}/trend")
def department_attendance_trend(
    department: str,
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
):
    if to_date < from_date:
        raise HTTPException(
            status_code=422,
            detail="'to' must be on or after 'from'"
        )

    total_days = (to_date - from_date).days + 1

    if total_days > 92:
        raise HTTPException(
            status_code=422,
            detail="Date range cannot exceed 92 days"
        )

    employee_codes = [
        employee["emp_code"]
        for employee in db.employees.find(
            {"department": department},
            {"_id": 0, "emp_code": 1}
        )
    ]

    if not employee_codes:
        raise HTTPException(
            status_code=404,
            detail="Department not found"
        )

    employees = list(db.employees.find(
        {
            "department": department,
            "joined_on": {"$lte": to_date.isoformat()}
        },
        {"_id": 0, "emp_code": 1, "joined_on": 1}
    ))

    pipeline = [
        {
            "$match": {
                "emp_code": {"$in": employee_codes},
                "date": {
                    "$gte": from_date.isoformat(),
                    "$lte": to_date.isoformat()
                }
            }
        },
        {
            "$group": {
                "_id": "$date",
                "present_count": {
                    "$sum": {
                        "$cond": [
                            {"$in": [
                                "$status",
                                ["PRESENT", "WFH", "ON_DUTY"]
                            ]},
                            {
                                "$cond": [
                                    {"$eq": ["$half_day", True]},
                                    0.5,
                                    1
                                ]
                            },
                            0
                        ]
                    }
                },
                "late_count": {
                    "$sum": {
                        "$cond": [
                            {"$gt": ["$late_minutes", 0]},
                            1,
                            0
                        ]
                    }
                }
            }
        }
    ]

    results = list(db.attendance_logs.aggregate(pipeline))
    records_by_date = {
        result["_id"]: result for result in results
    }

    rows = []
    current_date = from_date

    while current_date <= to_date:
        date_text = current_date.isoformat()

        headcount = sum(
            1 for employee in employees
            if employee.get("joined_on", "") <= date_text
        )

        record = records_by_date.get(date_text, {})
        present_count = float(record.get("present_count", 0))
        late_count = int(record.get("late_count", 0))
        is_working_day = current_date.weekday() < 5

        attendance_rate = None

        if is_working_day and headcount > 0:
            attendance_rate = float(
                Decimal(str(present_count / headcount)).quantize(
                    Decimal("0.0001"),
                    rounding=ROUND_HALF_UP
                )
            )

        rows.append({
            "date": date_text,
            "is_working_day": is_working_day,
            "headcount": headcount,
            "present_count": present_count,
            "late_count": late_count,
            "attendance_rate": attendance_rate
        })

        current_date += timedelta(days=1)

    for index, row in enumerate(rows):
        window = rows[max(0, index - 6):index + 1]
        rates = [
            item["attendance_rate"]
            for item in window
            if item["attendance_rate"] is not None
        ]

        row["moving_avg_7d"] = (
            float(
                Decimal(str(sum(rates) / len(rates))).quantize(
                    Decimal("0.0001"),
                    rounding=ROUND_HALF_UP
                )
            )
            if rates else None
        )

    return {
        "department": department,
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "trend": rows
    }




@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=422,
            detail="date_from must be before or equal to date_to"
        )

    q = {}

    if emp_code:
        q["emp_code"] = emp_code

    if date_from or date_to:
        q["date"] = {}

        if date_from:
            q["date"]["$gte"] = date_from

        if date_to:
            q["date"]["$lte"] = date_to

    if status:
        if status not in {
            "PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"
        }:
            raise HTTPException(
                status_code=422,
                detail="Invalid attendance status"
            )

        q["status"] = status

    total = db.attendance_logs.count_documents(q)

    page_docs = list(
        db.attendance_logs.find(q, {"_id": 0})
        .sort([("date", -1), ("emp_code", 1)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )

    for item in page_docs:
        item["punch_in"] = to_epoch_ms(item.get("punch_in"))
        item["punch_out"] = to_epoch_ms(item.get("punch_out"))

        for entry in item.get("history", []):
            entry["at"] = to_epoch_ms(entry.get("at"))

            changes = entry.get("changes", {})
            entry["changes"] = {
                field: {
                    "from": values.get("from", values.get("before")),
                    "to": values.get("to", values.get("after"))
                }
                for field, values in changes.items()
            }

    return {
        "items": page_docs,
        "total": total,
        "page": page,
        "page_size": page_size
    }

    
@app.get("/admin/explain/{endpoint}")
def explain_endpoint(
    endpoint: str,
    emp_code: Optional[str] = None,
    month: Optional[str] = None,
    department: Optional[str] = None,
    limit: int = Query(default=10, ge=1, le=50),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
):
    supported = {
        "attendance_list",
        "employee_monthly",
        "department_summary",
        "late_leaderboard",
        "department_trend",
    }

    if endpoint not in supported:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported endpoint. Choose one of: {sorted(supported)}",
        )

    def run_explain(collection_name: str, command: dict):
        try:
            result = db.command(
                "explain",
                command,
                verbosity="executionStats",
            )
            return {
                "endpoint": endpoint,
                "collection": collection_name,
                "explain": result,
            }
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"MongoDB explain failed: {str(exc)}",
            )

    if endpoint == "attendance_list":
        query = {}

        if emp_code:
            query["emp_code"] = emp_code
        if date_from or date_to:
            query["date"] = {}
            if date_from:
                query["date"]["$gte"] = date_from
            if date_to:
                query["date"]["$lte"] = date_to
        if status:
            if status not in {
                "PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"
            }:
                raise HTTPException(status_code=422, detail="Invalid status")
            query["status"] = status

        return run_explain(
            "attendance_logs",
            {
                "find": "attendance_logs",
                "filter": query,
                "sort": {"date": -1, "emp_code": 1},
                "skip": (page - 1) * page_size,
                "limit": page_size,
            },
        )

    if endpoint == "employee_monthly":
        if not emp_code or not month:
            raise HTTPException(
                status_code=422,
                detail="emp_code and month (YYYY-MM) are required",
            )

        try:
            year, month_number = map(int, month.split("-"))
            if len(month) != 7 or not 1 <= month_number <= 12:
                raise ValueError
            start_date = f"{year:04d}-{month_number:02d}-01"
            if month_number == 12:
                end_date = f"{year + 1:04d}-01-01"
            else:
                end_date = f"{year:04d}-{month_number + 1:02d}-01"
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="month must use YYYY-MM format",
            )

        pipeline = [
            {
                "$match": {
                    "emp_code": emp_code,
                    "date": {"$gte": start_date, "$lt": end_date},
                }
            },
            {"$sort": {"date": 1}},
            {
                "$group": {
                    "_id": "$emp_code",
                    "records": {"$sum": 1},
                }
            },
        ]

        return run_explain(
            "attendance_logs",
            {
                "aggregate": "attendance_logs",
                "pipeline": pipeline,
                "cursor": {},
            },
        )

    if endpoint == "department_summary":
        if not month:
            raise HTTPException(
                status_code=422,
                detail="month (YYYY-MM) is required",
            )

        try:
            year, month_number = map(int, month.split("-"))
            if len(month) != 7 or not 1 <= month_number <= 12:
                raise ValueError
            start_date = f"{year:04d}-{month_number:02d}-01"
            end_date = (
                f"{year + 1:04d}-01-01"
                if month_number == 12
                else f"{year:04d}-{month_number + 1:02d}-01"
            )
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="month must use YYYY-MM format",
            )

        pipeline = [
            {
                "$match": {
                    "date": {"$gte": start_date, "$lt": end_date}
                }
            },
            {
                "$group": {
                    "_id": "$emp_code",
                    "total_late_minutes": {"$sum": "$late_minutes"},
                }
            },
        ]

        return run_explain(
            "attendance_logs",
            {
                "aggregate": "attendance_logs",
                "pipeline": pipeline,
                "cursor": {},
            },
        )

    if endpoint == "late_leaderboard":
        if not month:
            raise HTTPException(
                status_code=422,
                detail="month (YYYY-MM) is required",
            )

        try:
            year, month_number = map(int, month.split("-"))
            if len(month) != 7 or not 1 <= month_number <= 12:
                raise ValueError
            start_date = f"{year:04d}-{month_number:02d}-01"
            end_date = (
                f"{year + 1:04d}-01-01"
                if month_number == 12
                else f"{year:04d}-{month_number + 1:02d}-01"
            )
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="month must use YYYY-MM format",
            )

        pipeline = [
            {
                "$match": {
                    "date": {"$gte": start_date, "$lt": end_date},
                    "late_minutes": {"$gt": 0},
                }
            },
            {
                "$group": {
                    "_id": "$emp_code",
                    "total_late_minutes": {"$sum": "$late_minutes"},
                }
            },
            {"$sort": {"total_late_minutes": -1, "_id": 1}},
            {"$limit": limit},
        ]

        return run_explain(
            "attendance_logs",
            {
                "aggregate": "attendance_logs",
                "pipeline": pipeline,
                "cursor": {},
            },
        )

    # department_trend
    if not department or not from_date or not to_date:
        raise HTTPException(
            status_code=422,
            detail="department, from, and to are required",
        )

    try:
        start = datetime.strptime(from_date, "%Y-%m-%d").date()
        end = datetime.strptime(to_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="from and to must use YYYY-MM-DD format",
        )

    if end < start or (end - start).days + 1 > 92:
        raise HTTPException(
            status_code=422,
            detail="Invalid date range; maximum range is 92 days",
        )

    employee_codes = [
        item["emp_code"]
        for item in db.employees.find(
            {"department": department},
            {"_id": 0, "emp_code": 1},
        )
    ]

    if not employee_codes:
        raise HTTPException(status_code=404, detail="Unknown department")

    pipeline = [
        {
            "$match": {
                "emp_code": {"$in": employee_codes},
                "date": {
                    "$gte": from_date,
                    "$lte": to_date,
                },
            }
        },
        {"$sort": {"date": 1}},
        {
            "$group": {
                "_id": "$date",
                "records": {"$sum": 1},
            }
        },
    ]

    return run_explain(
        "attendance_logs",
        {
            "aggregate": "attendance_logs",
            "pipeline": pipeline,
            "cursor": {},
        },
    )



# --------------------------------------------------------------------------- #
# TODO - the rest of the contract (see openapi.yaml):
#   POST  /attendance/punch-out
#   PATCH /attendance/{emp_code}/{date}
#   GET   /analytics/employees/{emp_code}/monthly
#   GET   /analytics/departments/summary
#   GET   /analytics/leaderboard/late
#   GET   /analytics/departments/{department}/trend
#   GET   /admin/explain/{endpoint}
# --------------------------------------------------------------------------- #
