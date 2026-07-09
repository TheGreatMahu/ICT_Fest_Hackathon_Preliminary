# Bug Report — CoWork API

This document lists every bug found in the codebase, organised by difficulty
tier.  For each bug: the file and line(s) affected, the root cause, and the
exact fix applied.

---

## Easy Bugs — 3 points each

### Bug 1 · `app/auth.py` line 50 — Access token expiry 60× too long

**Rule violated:** Rule 8 — "Access tokens expire in exactly 900 seconds."

**Root cause:**
```python
# BUGGY
lifetime = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES * 60)
# ACCESS_TOKEN_EXPIRE_MINUTES = 15 → 15 × 60 = 900 minutes = 54 000 seconds
```
`timedelta(minutes=…)` already interprets its argument as minutes.
Multiplying the constant by 60 again made tokens expire in 15 hours instead
of 15 minutes.

**Fix:**
```python
lifetime = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)  # = 900 s ✓
```

---

### Bug 2 · `app/auth.py` line 97 — Logout never actually invalidates a token

**Rule violated:** Rule 8 — "Logout immediately invalidates the presented access token."

**Root cause:**
```python
# BUGGY — checks the wrong field
if payload.get("sub") in _revoked_tokens:  # "sub" = user ID string
```
`revoke_access_token()` inserts `payload["jti"]` (unique token ID) into
`_revoked_tokens`, but the guard read `"sub"` (the user ID).  The two sets
never overlap, so every logged-out token remained valid.

**Fix:**
```python
if payload.get("jti") in _revoked_tokens:  # match on jti ✓
```

---

### Bug 3 · `app/timeutils.py` line 13 — UTC offset stripped without converting

**Rule violated:** Rule 1 — "Input datetimes carrying a UTC offset must be converted to UTC."

**Root cause:**
```python
# BUGGY
dt = dt.replace(tzinfo=None)   # strips offset, does NOT shift clock
# "14:00+05:30" stored as 14:00 UTC instead of correct 08:30 UTC
```
`.replace(tzinfo=None)` discards timezone info without adjusting the time
value, storing the local time as if it were UTC.

**Fix:**
```python
dt = dt.astimezone(timezone.utc).replace(tzinfo=None)  # convert then strip ✓
```

---

### Bug 4 · `app/routers/bookings.py` line 86 — 5-minute grace window on `start_time`

**Rule violated:** Rule 2 — "start_time must be strictly in the future — no grace window."

**Root cause:**
```python
# BUGGY — allowed start times up to 5 minutes in the past
if start <= now - timedelta(seconds=300):
```

**Fix:**
```python
if start <= now:  # strictly future, no grace window ✓
```

---

### Bug 5 · `app/routers/bookings.py` line 93 — missing minimum duration check

**Rule violated:** Rule 2 — "Duration … minimum 1, maximum 8."

**Root cause:**
```python
# BUGGY — only checked upper bound
if duration_hours > MAX_DURATION_HOURS:
```
Zero-hour and negative-duration bookings were accepted.

**Fix:**
```python
if duration_hours < MIN_DURATION_HOURS or duration_hours > MAX_DURATION_HOURS:
```

---

### Bug 6 · `app/routers/bookings.py` line 137 — pagination sorted descending

**Rule violated:** Rule 11 — "sorted ascending by start time."

**Root cause:**
```python
# BUGGY
base.order_by(Booking.start_time.desc(), Booking.id.asc())
```

**Fix:**
```python
base.order_by(Booking.start_time.asc(), Booking.id.asc())
```

---

### Bug 7 · `app/routers/bookings.py` line 138 — pagination offset off by one page

**Rule violated:** Rule 11 — "Sequential pages never skip or repeat items."

**Root cause:**
```python
# BUGGY — page=1 skips the first `limit` rows
.offset(page * limit)
```

**Fix:**
```python
.offset((page - 1) * limit)  # page=1 → offset 0 ✓
```

---

### Bug 8 · `app/routers/bookings.py` line 139 — limit hardcoded to 10

**Rule violated:** Rule 11 — caller-supplied `limit` parameter is ignored.

**Root cause:**
```python
# BUGGY
.limit(10)
```

**Fix:**
```python
.limit(limit)  # honour caller's limit ✓
```

---

### Bug 9 · `app/routers/bookings.py` line 166 — `start_time` overwritten with `created_at`

**Rule violated:** Rule 10 — booking response must return the correct `start_time`.

**Root cause:**
```python
# BUGGY — overwrites the correct start_time set by serialize_booking()
response["start_time"] = iso_utc(booking.created_at)
```

**Fix:** Line deleted entirely — `serialize_booking()` already sets `start_time` correctly.

---

## Medium Bugs — 5 points each

### Bug 10 · `app/routers/bookings.py` line 50 — back-to-back bookings rejected

**Rule violated:** Rule 3 — "Back-to-back bookings are allowed."

**Root cause:**
```python
# BUGGY — <= means touching endpoints are flagged as overlapping
if b.start_time <= end and start <= b.end_time:
```
A new booking whose `start == existing.end` (adjacent, not overlapping) was
incorrectly rejected.

**Fix:**
```python
if b.start_time < end and start < b.end_time:  # strict < allows back-to-back ✓
```

---

### Bug 11 · `app/routers/bookings.py` line 201 — refund boundary `>48h` instead of `>=48h`

**Rule violated:** Rule 6 — "notice ≥ 48 hours → 100% refund."

**Root cause:**
```python
# BUGGY — used truncated integer hours AND strict >
notice_hours = int(notice.total_seconds() // 3600)
if notice_hours > 48:   # exactly 48 h → falls into 50% tier
```
Truncating to integer hours AND using `>` instead of `>=` meant a cancellation
exactly 48 hours before the booking got 50% instead of 100%.

**Fix:**
```python
if notice >= timedelta(hours=48):  # exact timedelta comparison, no truncation ✓
```

---

### Bug 12 · `app/routers/bookings.py` line 206 — `<24h` notice gives 50% instead of 0%

**Rule violated:** Rule 6 — "notice < 24 hours → 0% refund."

**Root cause:**
```python
# BUGGY — final else returned 50 instead of 0
else:
    refund_percent = 50
```
Every cancellation gave at least 50% regardless of notice, incorrectly
rewarding last-minute cancellations.

**Fix:**
```python
else:
    refund_percent = 0
```

---

### Bug 13 · `app/routers/auth.py` lines 37–43 — duplicate username returns 201 instead of 409

**Rule violated:** Rule 15 — "A duplicate username within the org → 409 USERNAME_TAKEN."

**Root cause:**
```python
# BUGGY — silently returns the existing user's data
if existing is not None:
    return {"user_id": existing.id, ...}
```

**Fix:**
```python
if existing is not None:
    raise AppError(409, "USERNAME_TAKEN", "Username already taken")
```

---

### Bug 14 · `app/routers/auth.py` lines 81–93 — refresh token reusable forever

**Rule violated:** Rule 8 — "Refresh tokens are single-use: reuse → 401."

**Root cause:** The `/auth/refresh` endpoint decoded the token, fetched the
user, and issued new tokens without ever recording the used token's `jti` as
revoked.  The same refresh token could be replayed indefinitely.

**Fix:**
```python
if data.get("jti") in _revoked_tokens:
    raise AppError(401, "UNAUTHORIZED", "Refresh token already used")
_revoked_tokens.add(data["jti"])   # invalidate before issuing new tokens ✓
```

---

### Bug 15 · `app/services/refunds.py` lines 15–17 — refund amount truncated not rounded

**Rule violated:** Rule 6 — "Refund amount rounds to the nearest cent, half-cents rounding up."

**Root cause:**
```python
# BUGGY — dollar round-trip loses precision; int() truncates (floors)
dollars = booking.price_cents / 100.0
refund_dollars = dollars * (percent / 100.0)
amount_cents = int(refund_dollars * 100)   # 50.5 → 50 (wrong)
```

**Fix:**
```python
# math.floor(x + 0.5) is "round half up" — correct per spec
raw = booking.price_cents * percent / 100.0
amount_cents = math.floor(raw + 0.5)       # 50.5 → 51 ✓
```

---

### Bug 16 · `app/services/export.py` lines 48–50 — multi-tenancy bypass in CSV export

**Rule violated:** Rule 9 — "A user may only ever read data belonging to their own organisation."

**Root cause:**
```python
# BUGGY — fetch_bookings_raw has NO org_id filter
if include_all:
    if room_id is not None:
        rows = fetch_bookings_raw(db, room_id)   # leaks cross-org data
```
An admin could supply `?include_all=true&room_id=<other_org_room_id>` and
receive another organisation's bookings.

**Fix:** Removed `fetch_bookings_raw`.  All paths now route through
`_fetch_scoped` which always filters by `org_id`.

---

### Bug 17 · `app/cache.py` lines 13, 26 — stale cache violates "current state immediately"

**Rules violated:** Rules 12, 13 — availability and usage-reports must reflect current state immediately.

**Root cause:** `get_report()` and `get_availability()` returned cached dicts.
A booking cancelled between two reads still appeared as confirmed in the
cached report/availability response.

**Fix:** Both getters now unconditionally return `None` (cache miss); every
request hits the database.  The `set_*` helpers become no-ops so no call-site
needs changing.

---

## Hard Bugs — 10 points each

### Bug 18 · `app/services/notifications.py` lines 24–35 — AB/BA deadlock

**Rule violated:** Rule 16 — "No combination of concurrent valid requests may hang the service."

**Root cause:**
```
notify_created()   acquires _email_lock  then _audit_lock   (A → B)
notify_cancelled() acquires _audit_lock  then _email_lock   (B → A)
```
When thread 1 holds A and waits for B while thread 2 holds B and waits for A,
both block permanently.  Any concurrent create+cancel pair hangs the service.

**Fix:** Replaced both locks with a single `_notification_lock`.  One lock
cannot deadlock with itself.

---

### Bug 19 · `app/services/reference.py` lines 17–21 — duplicate reference codes under concurrency

**Rule violated:** Rule 7 — "Every booking's reference code is unique, including under concurrent creation."

**Root cause:**
```python
# No lock — concurrent threads all read the same counter value during sleep
current = _counter["value"]   # Thread A and B both read 1000
_format_pause()               # both sleep 0.12 s
_counter["value"] = current + 1   # both write 1001
return f"CW-{current:06d}"   # both return "CW-001000" — duplicate!
```

**Fix:** Wrapped the read→sleep→increment in `with _counter_lock:` making it
atomic.

---

### Bug 20 · `app/routers/bookings.py` lines 100–124 — TOCTOU race in booking creation

**Rules violated:** Rules 3, 4 — conflict and quota checks must hold under concurrent requests.

**Root cause:** `_has_conflict()` sleeps 0.12 s inside the check.  Two
concurrent requests both see "no conflict" during the sleep window, both pass
the quota check, then both insert — producing double-booked rooms or
over-quota bookings.

**Fix:** Wrapped the conflict check, quota check, and INSERT in
`with _booking_lock:`, serialising concurrent creates.

---

### Bug 21 · `app/routers/bookings.py` lines 195–214 — TOCTOU race in cancellation

**Rule violated:** Rule 6 — "A cancelled booking has exactly one RefundLog entry."

**Root cause:** Two concurrent cancel requests both read `status=="confirmed"`,
both pass the `ALREADY_CANCELLED` guard, both call `log_refund`, both write
`status="cancelled"` — leaving two `RefundLog` rows for one booking.

**Fix:** Wrapped `db.refresh(booking)` + status check + refund log + status
update in `with _cancel_lock:`.

---

### Bug 22 · `app/services/stats.py` lines 15–26 — lost updates in room statistics

**Rule violated:** Rule 14 — "always consistent with the bookings themselves, including after bursts of concurrent activity."

**Root cause:**
```python
# No lock — concurrent creates all read stale {count: 0} during sleep
current = _stats.get(room_id, {"count": 0, "revenue": 0})
_aggregate_pause()   # 0.1 s window
_stats[room_id] = {"count": count + 1, ...}
# 10 concurrent creates → all write count=1 instead of count=10
```

**Fix:** Wrapped the read→pause→write in `with _stats_lock:`.  Additionally,
the `/rooms/{id}/stats` endpoint now queries the DB directly, guaranteeing
consistency even after server restarts.

---

### Bug 23 · `app/services/ratelimit.py` lines 18–26 — rate limiter bypassed under concurrency

**Rule violated:** Rule 5 — "20 requests per rolling 60 seconds … must hold under concurrent requests."

**Root cause:**
```python
# No lock — all concurrent threads read the same empty bucket during sleep
bucket = _buckets.get(user_id, [])   # all read []
_settle_pause()                       # all sleep 0.1 s
bucket.append(now)
_buckets[user_id] = bucket            # all write [now] — length 1
if len(bucket) > _MAX_REQUESTS:       # 1 > 20 is False — all pass!
```

**Fix:** Wrapped trim→sleep→append→check in `with _buckets_lock:`.

---

## Summary Table

| # | File | Lines | Difficulty | Points |
|---|------|-------|-----------|--------|
| 1 | `app/auth.py` | 50 | Easy | 3 |
| 2 | `app/auth.py` | 97 | Easy | 3 |
| 3 | `app/timeutils.py` | 13 | Easy | 3 |
| 4 | `app/routers/bookings.py` | 86 | Easy | 3 |
| 5 | `app/routers/bookings.py` | 93 | Easy | 3 |
| 6 | `app/routers/bookings.py` | 137 | Easy | 3 |
| 7 | `app/routers/bookings.py` | 138 | Easy | 3 |
| 8 | `app/routers/bookings.py` | 139 | Easy | 3 |
| 9 | `app/routers/bookings.py` | 166 | Easy | 3 |
| 10 | `app/routers/bookings.py` | 50 | Medium | 5 |
| 11 | `app/routers/bookings.py` | 201 | Medium | 5 |
| 12 | `app/routers/bookings.py` | 206 | Medium | 5 |
| 13 | `app/routers/auth.py` | 37–43 | Medium | 5 |
| 14 | `app/routers/auth.py` | 81–93 | Medium | 5 |
| 15 | `app/services/refunds.py` | 15–17 | Medium | 5 |
| 16 | `app/services/export.py` | 48–50 | Medium | 5 |
| 17 | `app/cache.py` | 13, 26 | Medium | 5 |
| 18 | `app/services/notifications.py` | 24–35 | Hard | 10 |
| 19 | `app/services/reference.py` | 17–21 | Hard | 10 |
| 20 | `app/routers/bookings.py` | 100–124 | Hard | 10 |
| 21 | `app/routers/bookings.py` | 195–214 | Hard | 10 |
| 22 | `app/services/stats.py` | 15–26 | Hard | 10 |
| 23 | `app/services/ratelimit.py` | 18–26 | Hard | 10 |

**Total: 9 × 3 + 7 × 5 + 6 × 10 = 27 + 35 + 60 = 122 points**
