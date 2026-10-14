# DECISIONS.md

## 1. Indexes

I created a unique index on `employees.emp_code` to prevent duplicate employee codes, and a unique compound index on `attendance_logs.emp_code` and `date` to allow only one attendance record per employee per day. I also added indexes on attendance date and employee, employee and date, and status and date to support attendance filtering and sorting. I considered adding more indexes for individual analytics fields but avoided unnecessary indexes because they increase storage and write costs.

## 2. Punch-in race

If two identical punch-in requests arrive simultaneously, both may initially find no attendance record. Both attempt to insert, but the unique compound index permits only one insert. The other request encounters a duplicate-key error, which should be translated into HTTP 409 Conflict. The database constraint, rather than an application-level check alone, guarantees uniqueness.

## 3. Ties

The leaderboard uses competition ranking. Employees tied on total late minutes receive the same rank, such as 1, 2, 2, 4. The limit is applied after ranking, so employees tied at the cutoff are all returned.

## 4. Headcount

The department summary counts employees from the employees collection using their department and joining date. It does not rely only on attendance logs, so employees with zero logs are still counted.

## 5. Scaling to 100x data

I would move expensive analytics to optimized MongoDB aggregation pipelines, verify query plans with realistic datasets, and introduce suitable compound indexes based on measured query patterns.