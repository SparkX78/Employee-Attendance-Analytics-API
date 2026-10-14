# REVIEW.md

## Defects Found in the Starter `app/main.py`

The following table documents defects investigated during implementation and testing. Function names should be checked against the original starter implementation.

| # | Where (function / line) | What is wrong | How you'd notice it (test, input, or symptom) | How you fixed it |
|---|---|---|---|---|

| 1 | Timestamp validation and punch-in/punch-out handlers | Millisecond timestamps may retain fractional seconds, causing inconsistent calculations and storage. | Submit timestamps containing milliseconds and compare stored values and calculations. | Validate epoch-millisecond inputs and truncate to whole seconds before calculation and storage. |


| 2 | Attendance date calculation | Using UTC calendar dates instead of Indian Standard Time can assign attendance to the wrong day. | Submit a timestamp near midnight UTC and inspect its attendance date in IST. | Convert timestamps to `Asia/Kolkata` before deriving the attendance date. |


| 3 | `compute_late_minutes()` | Late-arrival calculations may mishandle the shift start or the 10-minute grace period. | Test arrivals exactly at shift start, at 10 minutes late, and one second beyond the grace period. | Apply the specified grace-period boundary and calculate lateness from the shift start. |


| 4 | `compute_late_minutes()` | Overnight shifts may calculate lateness incorrectly when the shift crosses midnight. | Test a shift such as 22:00–06:00 with arrivals around midnight. | Handle overnight shift boundaries explicitly. |


| 5 | `compute_overtime()` | Overtime may be counted before the minimum 30-minute threshold or calculated incorrectly for overnight shifts. | Test punch-outs 29 minutes and 30 minutes after shift end, including an overnight shift. | Handle overnight shift-end calculations and apply the required minimum overtime threshold. |


| 6 | `compute_work_hours()` and punch-out handler | Work hours may be reported before a valid punch-out exists. | Create an attendance record with punch-in only and inspect `work_hours`. | Keep `work_hours` null until both valid punch timestamps are available. |


| 7 | Attendance calculation and monthly analytics | Half-day classification may use an incorrect threshold or unrounded work hours. | Test work durations around 4.5 hours and inspect `half_day`. | Round work hours using half-up rounding to two decimal places, then classify durations below 4.5 hours as half-days. |


| 8 | Attendance status handling | Statuses such as `WFH` and `ON_DUTY` may not count as present, or `ABSENT` and `LEAVE` may be counted incorrectly. | Create records with each supported status and inspect analytics totals. | Centralize the rule for which statuses count as present and apply it consistently. |


| 9 | Monthly employee analytics | Weekend attendance records may incorrectly increase monthly present days. | Add a present record on Saturday and verify the monthly total. | Count present days only on weekdays while preserving the attendance record. |


| 10 | Monthly employee analytics | Employees joining mid-month may be assigned the full month's working-day denominator. | Test an employee who joins halfway through a month. | Calculate working days from the later of the month start and the employee's joining date. |


| 11 | Department summary analytics | Employees without attendance records may be omitted from department headcount. | Add an employee who has not punched in and request the department summary. | Derive headcount from employees whose joining date is on or before the reporting period's end. |


| 12 | Attendance list pagination | Pagination totals may be calculated before filters are applied, producing an incorrect `total`. | Apply an employee, date, or status filter and compare `total` with the number of matching records. | Calculate the total after applying the same filters as the list query, before pagination. |


| 13 | Late-arrival leaderboard | Employees with equal late-minute totals may receive different ranks or ties may be removed by the limit. | Create tied totals and request a leaderboard with a limit near the tie boundary. | Use competition ranking, deterministic secondary sorting, and apply the limit after ranking so tied employees are preserved. |


| 14 | Department trend analytics | Dates with no attendance records may be missing from the trend response. | Request a date range containing weekends and weekdays with no records; verify that every date appears. | Generate a complete daily series for the requested date range and fill missing-day metrics appropriately. |


| 15 | Department trend analytics | A seven-day moving average may include weekends or missing rates incorrectly, or use future dates. | Compare the moving average against a hand-calculated rolling window. | Average non-null attendance rates from the current row and up to six preceding rows within the requested range. |


| 16 | `/admin/explain/{endpoint}` | A simplified or hard-coded execution plan may not represent the actual endpoint query and its filters. | Compare the explain request parameters and returned plan with the endpoint's actual query or aggregation. | Build the explain query or pipeline from the same filters, sort, and pagination logic as the corresponding endpoint, then return MongoDB's real explain output. |


| 17 | MongoDB startup and index creation | Index creation may conflict with an existing index name or fail to enforce the required uniqueness. | Restart the application and inspect index-creation errors; attempt duplicate employee codes and attendance records. | Create the required indexes idempotently, using consistent definitions and unique constraints. |


| 18 | Attendance regularization endpoint | Regularization may accept invalid timestamp order, silently overwrite concurrent changes, or record inconsistent audit history. | Try equal punch timestamps, a punch-out before punch-in, and concurrent updates to one record. | Validate timestamp order and duration, update atomically, detect concurrent modifications, and append a history entry containing the actor, reason, timestamp, and field changes. |

## Items Reviewed and Considered Not to Be Defects

| Item | Why it was not considered a defect |
|---|---|
| Unique employee-code and attendance-record indexes | These enforce the required uniqueness constraints and prevent duplicate records. |
| Returning epoch milliseconds in API responses | This is the required API timestamp format; MongoDB may store the corresponding values as UTC datetimes. |
| Competition ranking with skipped ranks | Ranks such as `1, 2, 2, 4` are intentional when employees tie. |
| Null attendance rates on weekends | Weekends are non-working days, so their attendance rate is not applicable. |
| Null work hours before punch-out | Work duration cannot be finalized until both punch timestamps are available. |

**Verification note:** The table records the issues investigated and the intended fixes. Confirm each defect against the original starter code and retain only entries supported by an actual defect you found.
