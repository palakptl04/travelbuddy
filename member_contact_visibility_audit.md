# Member Contact Visibility — Full Audit Report

## How the Feature Works

### What it does
Controls whether confirmed trip members can see each other's phone numbers and email addresses. The owner decides this at trip creation (or edit time) via the **Open Roster** toggle.

---

## Where the Setting is Stored

| Layer | Location | Detail |
|---|---|---|
| **Database column** | `trips.open_roster` | `BOOLEAN`, `DEFAULT 0`, `NOT NULL` |
| **SQLAlchemy model** | `Trip.open_roster` | `db.Column(db.Boolean, default=False, nullable=False, server_default='0')` |
| **Migration** | `a1b2c3d4e5f6_add_join_deadline_open_roster_contact_log.py` | Added `open_roster` + `join_deadline` + `contact_access_logs` table |

---

## Visibility Rules (Who Can See What)

Governed entirely by `Trip.contact_visible_for(viewer_id, target_user_id)` in [models.py](file:///c:/Users/palak/Downloads/travelbuddy_v6/travelbuddy/app/models.py#L456-L502).

| Condition | Can viewer see target's phone/email? |
|---|---|
| Trip is **CANCELLED** | ❌ Never |
| `viewer_id == target_user_id` | ✅ Always (own data) |
| Trip status is **OPEN** or **AWAITING_CONFIRMATION** | ❌ No contacts visible to anyone |
| Trip is **CONFIRMED / ACTIVE / COMPLETED** + viewer is **owner** | ✅ Owner sees all members |
| Trip is **CONFIRMED / ACTIVE / COMPLETED** + target is **owner** | ✅ All members see owner |
| Trip is **CONFIRMED / ACTIVE / COMPLETED** + member ↔ member + `open_roster=True` | ✅ Members see each other |
| Trip is **CONFIRMED / ACTIVE / COMPLETED** + member ↔ member + `open_roster=False` | ❌ Members cannot see each other |
| Viewer or target is not an **active participant** (removed/declined) | ❌ No access |

---

## All Involved Files

### Models
- **[models.py](file:///c:/Users/palak/Downloads/travelbuddy_v6/travelbuddy/app/models.py)**
  - `Trip.open_roster` column (L170–171)
  - `Trip.contact_visible_for()` — core logic (L456–502)
  - `Trip._is_active_participant()` — helper (L504–511)
  - `User.get_phone()` / `User.get_email()` — decryption hooks (L63–69)
  - `User.set_phone()` — encryption hook for write path (L71–72) *(unused — see audit)*
  - `_encrypt_contact()` / `_decrypt_contact()` — passthrough stubs (L20–27) *(partial dead code — see audit)*
  - `ContactAccessLog` model — audit trail (L673–697)

### Forms
- **[trips/forms.py](file:///c:/Users/palak/Downloads/travelbuddy_v6/travelbuddy/app/trips/forms.py#L42-L45)**
  - `TripForm.open_roster = BooleanField(...)` (L42–45)

### Routes
- **[trips/routes.py](file:///c:/Users/palak/Downloads/travelbuddy_v6/travelbuddy/app/trips/routes.py)**
  - `_log_contact_access()` — writes one `ContactAccessLog` row (L20–31)
  - `_log_visible_contacts()` — calls above for each visible user on page load (L34–42)
  - `detail()` route — builds `contact_visible` dict and calls logger (L186–205)
  - `create()` — sets `open_roster` from form (L131)
  - `edit()` — updates `open_roster` from form (L258)
- **[api/routes.py](file:///c:/Users/palak/Downloads/travelbuddy_v6/travelbuddy/app/api/routes.py)**
  - `TripCreateSchema.open_roster` field (L42)
  - `_trip_to_dict()` serialises `open_roster` (L88)
  - `create_trip()` sets `open_roster` (L425)
  - `update_trip()` (PUT) sets `open_roster` (L596)
  - `patch_trip()` (PATCH) sets `open_roster` conditionally (L705)

### Templates
- **[trips/create.html](file:///c:/Users/palak/Downloads/travelbuddy_v6/travelbuddy/app/templates/trips/create.html#L170-L180)** — Open Roster checkbox (L170–180)
- **[trips/edit.html](file:///c:/Users/palak/Downloads/travelbuddy_v6/travelbuddy/app/templates/trips/edit.html#L304-L314)** — Open Roster checkbox (L304–314)
- **[trips/detail.html](file:///c:/Users/palak/Downloads/travelbuddy_v6/travelbuddy/app/templates/trips/detail.html)**
  - Roster badge display (L324–330)
  - Owner contact line (L672–683)
  - Member contact line (L700–712)
  - Uses `trip.owner.get_email()`, `trip.owner.get_phone()`, `m.user.get_email()`, `m.user.get_phone()`

### Database / Migrations
- **[a1b2c3d4e5f6_add_join_deadline_open_roster_contact_log.py](file:///c:/Users/palak/Downloads/travelbuddy_v6/travelbuddy/migrations/versions/a1b2c3d4e5f6_add_join_deadline_open_roster_contact_log.py)** — adds `open_roster`, `join_deadline`, `contact_access_logs`

### Tests
- **[tests/test_trips.py](file:///c:/Users/palak/Downloads/travelbuddy_v6/travelbuddy/tests/test_trips.py)**
  - `TestContactVisibility` class (L545–721) — 7 tests covering all visibility rules
  - `TestContactAccessLog` class (L728–773) — 1 integration test verifying log writes

---

## Security / Privacy Checks

1. **Route-level**: `detail()` requires `@login_required`. Non-members are shown a lock notice; `contact_visible` dict is only built for members.
2. **Model-level**: `contact_visible_for()` enforces status, participant status (active only), and role-based rules before returning `True`.
3. **Audit trail**: `ContactAccessLog` records every contact reveal — viewer, target, trip, and timestamp with composite indices for fast queries.
4. **Cancelled trip guard**: Hard `return False` at the top of `contact_visible_for()` before any other check.
5. **Removed-member guard**: `_is_active_participant()` ensures declined/left members lose access immediately.

---

## Dead Code Audit

### ✅ Code that is actively used (do NOT remove)
| Item | Why it's needed |
|---|---|
| `_decrypt_contact()` | Called by `get_phone()` and `get_email()`, which ARE used in `detail.html` |
| `get_phone()`, `get_email()` | Called from `detail.html` Jinja2 templates |
| `ContactAccessLog` model | Written by `_log_contact_access()` on every detail page load; tested |
| `Trip.contact_visible_for()` | Core logic, called from routes and tests |
| `Trip._is_active_participant()` | Called by `contact_visible_for()` |
| `open_roster` field everywhere | Core feature field |
| All 8 tests | Pass, cover all branches |

### ❌ Dead Code Found (candidates for removal)

| Item | File | Lines | Reason |
|---|---|---|---|
| `set_phone()` method | [models.py](file:///c:/Users/palak/Downloads/travelbuddy_v6/travelbuddy/app/models.py#L71-L72) | L71–72 | **Never called anywhere.** Profile route writes directly to `current_user.phone`. No template, no route, no test calls `set_phone()`. |
| `_encrypt_contact()` function | [models.py](file:///c:/Users/palak/Downloads/travelbuddy_v6/travelbuddy/app/models.py#L20-L22) | L20–22 | **Only called from `set_phone()`** which is itself dead code. No other callers exist in the entire project. |

> [!NOTE]
> The comment block (L14–18) documenting the encryption hook pattern is retained — it documents the *intent* for future real encryption and is still accurate for `_decrypt_contact` / `get_phone` / `get_email`.

---

## Cleanup Performed

### Removed: `set_phone()` method (models.py L71–72)
```diff
-    def set_phone(self, value: str):
-        self.phone = _encrypt_contact(value)
-
```

### Removed: `_encrypt_contact()` function (models.py L20–22)
```diff
-def _encrypt_contact(value: str) -> str:
-    """Encrypt a contact field before storing. Override for real encryption."""
-    return value or ''
-
```
The companion comment block (L14–18) and `_decrypt_contact()` are retained as they remain relevant.

---

## Post-Cleanup Verification

All 8 contact visibility / access log tests pass after removal:

```
tests/test_trips.py::TestContactVisibility::test_no_contacts_before_confirmation PASSED
tests/test_trips.py::TestContactVisibility::test_cancelled_trip_hides_all_contacts PASSED
tests/test_trips.py::TestContactVisibility::test_confirmed_owner_sees_all_contacts PASSED
tests/test_trips.py::TestContactVisibility::test_confirmed_member_sees_owner_always PASSED
tests/test_trips.py::TestContactVisibility::test_confirmed_member_cannot_see_other_member_without_open_roster PASSED
tests/test_trips.py::TestContactVisibility::test_confirmed_member_sees_other_member_with_open_roster PASSED
tests/test_trips.py::TestContactVisibility::test_removed_member_loses_contact_access PASSED
tests/test_trips.py::TestContactAccessLog::test_contact_log_written_on_detail_view PASSED

8 passed in 12.73s
```
