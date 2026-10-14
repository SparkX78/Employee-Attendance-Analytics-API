# Employee Attendance & Analytics API

A REST API built with FastAPI and MongoDB for employee management, attendance tracking, attendance regularization, and workforce analytics.

## Features

- Employee creation and retrieval
- Punch-in and punch-out with timestamp validation
- Shift-aware late arrival and overtime calculations
- Attendance history and regularization with audit trails
- Paginated attendance records
- Monthly employee analytics
- Department attendance summaries and daily trends
- Late-arrival leaderboard with competition ranking
- MongoDB indexes and query explain endpoint

## Prerequisites

- Python 3.11 or later
- MongoDB 6.0 or later
- Dependencies listed in `requirements.txt`

## Local Setup

1. Open a terminal in the project directory.
2. Create and activate a virtual environment on Windows:

   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   ```

3. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

4. Configure `MONGO_URI` and `MONGO_DB` as environment variables. The application defaults to `mongodb://localhost:27017` and database `attendance_db` if they are not supplied.

5. Start the application:

   ```powershell
   python -m uvicorn app.main:app --reload --port 8000
   ```

## API Documentation

Once the server is running, open:

- Swagger UI: `http://127.0.0.1:8000/docs`
- Health check: `http://127.0.0.1:8000/health`

## Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Check API health |
| POST | `/employees` | Create an employee |
| GET | `/employees` | List employees |
| POST | `/attendance/punch-in` | Record punch-in |
| POST | `/attendance/punch-out` | Record punch-out |
| GET | `/attendance` | List attendance with filters and pagination |
| PATCH | `/attendance/{emp_code}/{date}` | Regularize an attendance record |
| GET | `/analytics/employees/{emp_code}/monthly` | Monthly employee analytics |
| GET | `/analytics/departments/summary` | Department summary |
| GET | `/analytics/leaderboard/late` | Late-arrival leaderboard |
| GET | `/analytics/departments/{department}/trend` | Daily department attendance trend |
| GET | `/admin/explain/{endpoint}` | Inspect MongoDB query execution plans |

Refer to Swagger UI for the exact request schemas, query parameters, and response models.

## Data and Configuration

- MongoDB stores employee records and attendance logs.
- API timestamps use epoch milliseconds.
- Attendance dates and shift calculations use Indian Standard Time.
- Required indexes are created during application startup.
- `sample_seed.py` can be used to load the supplied sample data when the MongoDB database is configured.

## Submission Notes

Include `app/main.py`, `requirements.txt`, `README.md`, `REVIEW.md`, and `DECISIONS.md` in the repository. Do not commit `.env` files, credentials, virtual environments, database dumps, or a Dockerfile.
