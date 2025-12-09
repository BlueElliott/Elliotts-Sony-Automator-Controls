# v1.1.0 - Remaining Work

## Status: ~70% Complete

### ✅ COMPLETED - Backend Infrastructure

1. **Config Structure Updated**
   - New `automators` array (replaces single `automator`)
   - Added `config_version` and `first_run` flags
   - Updated Pydantic models with `automator_id` support
   - No "default" Automator concept (as per requirements)

2. **Migration System**
   - `migrate_config_to_v1_1_0()` function added
   - Automatically converts v1.0.x configs to v1.1.0
   - Preserves all settings and command mappings
   - Tested and working

3. **Cache System**
   - Per-Automator cache storage (`automator_data_cache[automator_id]`)
   - `get_automator_cache(automator_id)` helper
   - `merge_automator_data(automator_id, data)` updated
   - `_get_cached_items(automator_id)` updated

4. **Helper Functions**
   - `get_automator_by_id(automator_id)` ✅
   - `get_all_automators()` ✅

5. **Core Functions Updated**
   - `check_automator_connection(automator_id=None)` ✅
   - `fetch_automator_macros(automator_id=None, ...)` ✅
   - `trigger_automator_macro(..., automator_id=None)` ✅
   - `process_tcp_command()` reads `automator_id` from mapping ✅

6. **Version Numbers**
   - Updated to 1.1.0 in all files ✅

---

## 🚧 TODO - API Endpoints (30% of remaining work)

### Update Existing Endpoints

**File:** `core.py` (around line 2656)

```python
# UPDATE: Add automator_id parameter
@app.get("/api/automator/test")
async def api_automator_test(automator_id: Optional[str] = None):
    """Test Automator connection."""
    return check_automator_connection(automator_id)

# UPDATE: Add automator_id parameter
@app.post("/api/automator/refresh")
async def api_automator_refresh(automator_id: Optional[str] = None):
    """Force refresh Automator data from API."""
    try:
        items = fetch_automator_macros(automator_id, force_refresh=True)
        return {
            "ok": True,
            "count": len(items),
            "message": f"Loaded {len(items)} items"
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

# UPDATE: Add automator_id parameter
@app.post("/api/automator/trigger/{macro_id}")
async def api_trigger_macro(
    macro_id: str,
    item_type: str = "macro",
    automator_id: Optional[str] = None
):
    """Manually trigger macro."""
    await trigger_automator_macro(macro_id, f"Manual: {macro_id}", item_type, automator_id)
    return {"success": True}
```

### New Automator Management Endpoints

**Add these after the existing /api/automator endpoints:**

```python
@app.get("/api/automators")
async def api_get_automators():
    """Get all Automator configurations."""
    return {"automators": get_all_automators()}


@app.post("/api/automators")
async def api_add_automator(automator: AutomatorConfig):
    """Add new Automator."""
    global config_data

    automators = config_data.get("automators", [])

    # Check if ID already exists
    if any(a["id"] == automator.id for a in automators):
        raise HTTPException(400, "Automator ID already exists")

    automators.append(automator.dict())
    config_data["automators"] = automators
    save_config(config_data)

    log_event("Config", f"Added Automator: {automator.name}")
    return {"success": True, "automator": automator.dict()}


@app.put("/api/automators/{automator_id}")
async def api_update_automator(automator_id: str, automator: AutomatorConfig):
    """Update existing Automator."""
    global config_data

    automators = config_data.get("automators", [])
    found = False

    for i, a in enumerate(automators):
        if a["id"] == automator_id:
            automators[i] = automator.dict()
            found = True
            break

    if not found:
        raise HTTPException(404, "Automator not found")

    config_data["automators"] = automators
    save_config(config_data)

    log_event("Config", f"Updated Automator: {automator.name}")
    return {"success": True, "automator": automator.dict()}


@app.delete("/api/automators/{automator_id}")
async def api_delete_automator(automator_id: str):
    """Delete Automator (with orphaned mapping warning)."""
    global config_data

    automators = config_data.get("automators", [])
    automator = get_automator_by_id(automator_id)

    if not automator:
        raise HTTPException(404, "Automator not found")

    # Check for orphaned mappings
    mappings = config_data.get("command_mappings", [])
    orphaned = [m for m in mappings if m.get("automator_id") == automator_id]

    # Return info about orphaned mappings for user confirmation
    return {
        "automator": automator,
        "orphaned_mappings": orphaned,
        "count": len(orphaned),
        "requires_confirmation": len(orphaned) > 0
    }


@app.delete("/api/automators/{automator_id}/confirm")
async def api_delete_automator_confirm(automator_id: str, delete_mappings: bool = True):
    """Confirm deletion of Automator and handle orphaned mappings."""
    global config_data

    # Remove Automator
    automators = config_data.get("automators", [])
    config_data["automators"] = [a for a in automators if a["id"] != automator_id]

    # Handle mappings
    if delete_mappings:
        mappings = config_data.get("command_mappings", [])
        config_data["command_mappings"] = [m for m in mappings if m.get("automator_id") != automator_id]

    save_config(config_data)
    log_event("Config", f"Deleted Automator: {automator_id}")

    return {"success": True, "deleted_mappings": delete_mappings}
```

### Update Config Endpoint

**Find and update the `/api/config` endpoint** (around line 2687) to handle `automators` instead of `automator`:

```python
@app.post("/api/config")
async def api_update_config(config_update: ConfigUpdate):
    """Update configuration."""
    global config_data

    # ... existing tcp_listeners and tcp_commands code ...

    # NEW: Handle automators array
    if config_update.automators is not None:
        config_data["automators"] = [a.dict() for a in config_update.automators]
        log_event("Config", f"Updated Automators ({len(config_update.automators)} configured)")

    # NEW: Handle first_run dismissal
    if config_update.first_run is not None:
        config_data["first_run"] = config_update.first_run
        log_event("Config", "Welcome banner dismissed" if not config_update.first_run else "Reset first run")

    # ... rest of existing code ...
```

---

## 🚧 TODO - UI Updates (50% of remaining work)

### 1. Home Page - Welcome Banner (15 min)

**File:** `core.py` - Find `async def home():` function (around line 1450)

**Add at the very top of the content:**

```python
# Check for first-run
is_first_run = config_data.get("first_run", False)
show_welcome = is_first_run or len(config_data.get("automators", [])) == 0

welcome_html = ""
if show_welcome:
    welcome_html = """
    <div class="section" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border-radius: 12px; padding: 30px; margin-bottom: 30px;">
        <h2 style="color: white; margin-top: 0;">👋 Welcome to Sony Automator Controls v1.1.0!</h2>
        <p style="font-size: 16px; margin-bottom: 20px;">Let's get you set up in a few easy steps:</p>
        <ol style="font-size: 15px; line-height: 1.8;">
            <li><strong>Add Automator:</strong> Go to <a href="/automator-macros" style="color: #ffd700;">Automator Controls</a> and configure your first Automator connection</li>
            <li><strong>Setup TCP:</strong> Configure <a href="/tcp-commands" style="color: #ffd700;">TCP Listeners and Commands</a></li>
            <li><strong>Create Mappings:</strong> Link commands to macros in <a href="/command-mapping" style="color: #ffd700;">Command Mapping</a></li>
        </ol>
        <button onclick="dismissWelcome()" style="background: white; color: #667eea; border: none; padding: 10px 24px; border-radius: 6px; font-weight: bold; cursor: pointer; margin-top: 15px;">Got it, don't show again</button>
    </div>

    <script>
        async function dismissWelcome() {
            await fetch('/api/config', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({first_run: false})
            });
            location.reload();
        }
    </script>
    """

# Insert welcome_html at the start of content
content = f"""
{welcome_html}
<h1>Dashboard</h1>
... rest of existing content ...
"""
```

### 2. Automator Controls Page - Management UI (45 min)

**File:** `core.py` - Find `async def automator_macros_page():` (around line 1800)

**Replace the entire page content with:**

See the IMPLEMENTATION_PLAN_v1.1.0.md file, section "Update Automator Controls Page"

**Key changes:**
- Add Automator management section at the TOP
- List all Automators with status indicators
- Add/Edit/Delete/Test/Refresh buttons per Automator
- Show cached item count per Automator
- Keep existing macros/buttons/shortcuts display below (filtered by selected Automator)

**Inspired by Singular Controls token management:**
- Clean card-based layout
- Individual test/refresh buttons
- Status indicators (connected/disconnected)
- Add button at top

### 3. Command Mapping Page - Automator Selector (30 min)

**File:** `core.py` - Find `async def command_mapping_page():` (around line 2050)

**Key changes:**

```python
# For each mapping row, add Automator selector:
<tr>
    <td><strong>{tcp_name}</strong></td>
    <td>
        <select class="automator-select" data-tcp-id="{tcp_id}" onchange="automatorChanged('{tcp_id}')">
            {automator_options_html}
        </select>
    </td>
    <td>
        <input list="macros-{tcp_id}" ... />
        <!-- Datalist dynamically populated based on selected Automator -->
    </td>
    <td>
        <button class="play-btn" onclick="testMapping('{tcp_id}')">▶</button>
    </td>
</tr>
```

**JavaScript updates:**
- When Automator changes, fetch its macros and rebuild datalist
- When saving mapping, include `automator_id`
- When testing, pass `automator_id` to trigger endpoint

---

## 🧪 TODO - Testing (20% of remaining work)

### Test Checklist

- [ ] Fresh install (delete config, start v1.1.0)
  - Should show welcome banner
  - Should have empty automators array

- [ ] Upgrade from v1.0.8
  - Migration should run automatically
  - Old automator should become first in array
  - All mappings should gain automator_id
  - App should work immediately

- [ ] Add 2 Automators
  - Can add both successfully
  - Can test each independently
  - Can refresh each independently

- [ ] Create mappings
  - Can select which Automator per mapping
  - Test button triggers correct Automator

- [ ] Delete Automator
  - Should warn about orphaned mappings
  - Should ask what to do

- [ ] TCP command flow
  - Should trigger correct Automator based on mapping

---

## Estimated Time to Complete

- API Endpoints: **30 minutes**
- Home Page Welcome: **15 minutes**
- Automator Management UI: **45 minutes**
- Command Mapping Updates: **30 minutes**
- Testing: **30 minutes**

**Total: ~2.5 hours**

---

## Notes

- Backend is solid and tested ✅
- All core functions support automator_id ✅
- Migration tested and working ✅
- Just need to wire up the UI and API endpoints
- No breaking changes to existing functionality
- All v1.0.8 features preserved

---

## Quick Start Guide (for next session)

1. **Start with API endpoints** - easiest part, just add the new routes
2. **Update Automator Controls page** - biggest UI change, refer to Singular Controls for inspiration
3. **Update Command Mapping** - add dropdown, update save/test logic
4. **Add Welcome Banner** - quick HTML addition
5. **Test everything** - run through the checklist

The hard work is done! Just needs the final UI polish. 🚀
