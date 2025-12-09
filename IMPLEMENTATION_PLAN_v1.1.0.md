# Implementation Plan: v1.1.0 - Multi-Automator Support & First-Run Experience

## Overview
Version 1.1.0 adds support for multiple Automator instances and improves the first-run experience for new users.

## Current State (v1.0.8)
- ✅ Single Automator configuration
- ✅ Persistent caching system
- ✅ File-based logging with rotation
- ✅ HTTP connection pooling with httpx
- ✅ Performance optimizations

## Goals for v1.1.0

### 1. Multi-Automator Support
Allow users to configure and manage multiple Automator instances simultaneously.

**Use Cases:**
- Production + Backup Automator
- Multiple locations/studios
- Different Automator instances for different purposes

### 2. First-Run Experience
Provide helpful guidance for new users on first launch.

**Features:**
- Welcome banner on home page
- Getting started guide
- Empty state messaging
- Configuration hints

---

## Implementation Details

### Phase 1: Backend Infrastructure (Core Changes)

#### 1.1 Configuration Structure Update

**Current (v1.0.8):**
```python
DEFAULT_CONFIG = {
    "version": __version__,
    "theme": "dark",
    "web_port": 3114,
    "tcp_listeners": [...],
    "tcp_commands": [...],
    "automator": {
        "url": "http://127.0.0.1:7070",
        "api_key": "",
        "enabled": False
    },
    "command_mappings": [...]
}
```

**New (v1.1.0):**
```python
DEFAULT_CONFIG = {
    "version": __version__,
    "config_version": "1.1.0",  # NEW: track config format version
    "theme": "dark",
    "web_port": 3114,
    "first_run": True,  # NEW: detect first-run for welcome
    "tcp_listeners": [],  # Empty for first-run
    "tcp_commands": [],  # Empty for first-run
    "automators": [],  # NEW: array of Automator configs
    "command_mappings": []
}
```

**New Automator Config Structure:**
```python
{
    "id": "auto_abc123",  # Unique ID
    "name": "Primary Automator",  # User-friendly name
    "url": "http://127.0.0.1:7070",
    "api_key": "",
    "enabled": True,
    "default": True  # Mark as default
}
```

**Updated Command Mapping:**
```python
{
    "tcp_command_id": "cmd_1",
    "automator_id": "auto_abc123",  # NEW: which Automator
    "automator_macro_id": "macro_123",
    "automator_macro_name": "Play",
    "item_type": "macro"  # macro, button, shortcut
}
```

#### 1.2 Migration Function

**File:** `core.py`
**Function:** `migrate_config_to_v1_1_0(old_config: dict) -> dict`

**What it does:**
1. Detects old single `automator` config
2. Converts to new `automators` array
3. Updates all command mappings to include `automator_id`
4. Sets `config_version = "1.1.0"`
5. Sets `first_run = False` if had previous config

**Migration Logic:**
- If old config has `automator` with URL → create first Automator in array
- Assign ID: `auto_{uuid.hex[:8]}`
- Name: "Primary Automator"
- Mark as `default: True`
- Update all mappings to reference this Automator ID

#### 1.3 Cache System Update

**Current:** Single global cache
```python
automator_data_cache = {
    "macros": [],
    "buttons": [],
    "shortcuts": [],
    "last_updated": None
}
```

**New:** Per-Automator cache
```python
automator_data_cache = {
    "auto_abc123": {
        "macros": [],
        "buttons": [],
        "shortcuts": [],
        "last_updated": "2025-12-09T..."
    },
    "auto_xyz789": {
        "macros": [],
        "buttons": [],
        "shortcuts": [],
        "last_updated": "2025-12-09T..."
    }
}
```

**New Functions:**
- `get_automator_cache(automator_id: str) -> dict`
- `merge_automator_data(automator_id: str, new_data: dict)`
- `_get_cached_items(automator_id: str) -> List[Dict]`

#### 1.4 Helper Functions

**New Functions in core.py:**

```python
def get_default_automator() -> Optional[dict]:
    """Get the default Automator (marked default or first enabled)."""

def get_automator_by_id(automator_id: str) -> Optional[dict]:
    """Get specific Automator by ID."""

def get_all_automators() -> List[dict]:
    """Get all Automator configurations."""
```

#### 1.5 Update Core Functions

**Update `check_automator_connection()`:**
- Add parameter: `automator_id: Optional[str] = None`
- If None, use default Automator
- Return includes `automator_id` and `automator_name`

**Update `fetch_automator_macros()`:**
- Add parameter: `automator_id: Optional[str] = None`
- If None, use default Automator
- Uses per-Automator cache

**Update `trigger_automator_macro()`:**
- Add parameter: `automator_id: Optional[str] = None`
- If None, use default Automator
- Gets URL from specific Automator config

**Update `process_tcp_command()`:**
- Read `automator_id` from command mapping
- Pass to `trigger_automator_macro()`

#### 1.6 Update Pydantic Models

```python
class AutomatorConfig(BaseModel):
    id: str
    name: str
    url: str
    api_key: str = ""
    enabled: bool
    default: bool = False

class CommandMapping(BaseModel):
    tcp_command_id: str
    automator_id: str  # NEW
    automator_macro_id: str
    automator_macro_name: str = ""
    item_type: str = "macro"
```

---

### Phase 2: Web UI Updates

#### 2.1 Home Page - First-Run Welcome

**File:** `core.py` - `home()` function

**Check for first-run:**
```python
is_first_run = config_data.get("first_run", False)
has_automators = len(config_data.get("automators", [])) == 0
has_tcp_listeners = len(config_data.get("tcp_listeners", [])) == 0
has_tcp_commands = len(config_data.get("tcp_commands", [])) == 0

show_welcome = is_first_run or (has_automators and has_tcp_listeners)
```

**Welcome Banner (if first-run):**
```html
<div class="welcome-banner">
    <h2>👋 Welcome to Sony Automator Controls!</h2>
    <p>Let's get you set up in 4 easy steps:</p>
    <ol>
        <li>Add an Automator connection</li>
        <li>Configure TCP listeners</li>
        <li>Define TCP commands</li>
        <li>Map commands to Automator macros</li>
    </ol>
    <button onclick="dismissWelcome()">Got it!</button>
</div>
```

**Dismiss Welcome:**
- POST to `/api/config` with `first_run: false`

#### 2.2 NEW PAGE: Automator Management

**Route:** `/automators`
**Nav:** Add new nav item "Automators"

**Features:**
- List all Automators with status
- Add new Automator
- Edit existing Automator
- Delete Automator
- Set default Automator
- Test connection per Automator
- View cached data per Automator

**UI Layout:**
```
┌─────────────────────────────────────┐
│ Automators                          │
│ ┌─────────────────────────────────┐ │
│ │ [+] Add Automator               │ │
│ └─────────────────────────────────┘ │
│                                     │
│ ┌─────────────────────────────────┐ │
│ │ Primary Automator [DEFAULT]     │ │
│ │ http://localhost:7070           │ │
│ │ ● Connected | 42 items cached   │ │
│ │ [Edit] [Test] [Refresh] [Delete]│ │
│ └─────────────────────────────────┘ │
│                                     │
│ ┌─────────────────────────────────┐ │
│ │ Backup Automator                │ │
│ │ http://192.168.1.100:7070       │ │
│ │ ○ Disconnected | 38 items cached│ │
│ │ [Edit] [Test] [Refresh] [Delete]│ │
│ └─────────────────────────────────┘ │
└─────────────────────────────────────┘
```

**API Endpoints Needed:**
- `POST /api/automators` - Add new Automator
- `PUT /api/automators/{id}` - Update Automator
- `DELETE /api/automators/{id}` - Delete Automator
- `POST /api/automators/{id}/test` - Test connection
- `POST /api/automators/{id}/refresh` - Refresh data
- `PUT /api/automators/{id}/set-default` - Set as default

#### 2.3 Update Automator Controls Page

**Changes:**
- Show Automator selector dropdown at top
- Load/Reload button refreshes selected Automator
- Display which Automator's data is shown
- Show cache age per Automator

**UI Changes:**
```html
<div class="section">
    <h2>Automator Controls</h2>
    <label>Select Automator:</label>
    <select id="automatorSelect" onchange="loadAutomatorData()">
        <option value="auto_abc123">Primary Automator</option>
        <option value="auto_xyz789">Backup Automator</option>
    </select>

    <!-- Rest of page shows data for selected Automator -->
</div>
```

#### 2.4 Update Command Mapping Page

**Changes:**
- Add Automator selector for each mapping
- Show which Automator each mapping targets
- Filter macros by selected Automator

**UI Changes:**
```html
<tr>
    <td><strong>{tcp_name}</strong></td>
    <td>
        <select class="automator-select" data-tcp-id="{tcp_id}" onchange="automatorChanged()">
            <option value="auto_abc123">Primary Automator</option>
            <option value="auto_xyz789">Backup Automator</option>
        </select>
    </td>
    <td>
        <input list="macros-{tcp_id}-{automator_id}" ... />
        <!-- Datalist filtered by selected Automator -->
    </td>
    <td>
        <button class="play-btn" onclick="testMapping()">▶</button>
    </td>
</tr>
```

---

### Phase 3: API Endpoints

#### 3.1 New Endpoints

```python
# Automator Management
POST   /api/automators              # Add Automator
PUT    /api/automators/{id}         # Update Automator
DELETE /api/automators/{id}         # Delete Automator
POST   /api/automators/{id}/test    # Test connection
POST   /api/automators/{id}/refresh # Refresh cache
PUT    /api/automators/{id}/default # Set as default

# Config
POST   /api/config/dismiss-welcome  # Mark first-run complete
```

#### 3.2 Update Existing Endpoints

**Update:**
- `POST /api/automator/refresh` → Add `automator_id` parameter
- `POST /api/automator/trigger/{macro_id}` → Add `automator_id` parameter
- `GET /api/automator/test` → Add `automator_id` parameter

---

### Phase 4: Testing & Validation

#### 4.1 Migration Testing
- [ ] Fresh install (v1.1.0 from scratch)
- [ ] Upgrade from v1.0.4
- [ ] Upgrade from v1.0.8
- [ ] Config migration preserves all settings
- [ ] Command mappings work after migration

#### 4.2 Multi-Automator Testing
- [ ] Add 2+ Automators
- [ ] Set different default
- [ ] Delete Automator (orphaned mappings?)
- [ ] Command mapping targets correct Automator
- [ ] Cache isolated per Automator

#### 4.3 First-Run Testing
- [ ] Welcome banner shows on first run
- [ ] Dismiss welcome works
- [ ] Empty states helpful
- [ ] Guide users through setup

---

## Implementation Order

1. ✅ **Version Update** (5 min)
   - Update version to 1.1.0 in all files

2. **Backend Core** (60 min)
   - Update config structure
   - Add migration function
   - Update cache system
   - Add helper functions
   - Update core functions (check, fetch, trigger)
   - Update Pydantic models

3. **API Endpoints** (30 min)
   - New Automator management endpoints
   - Update existing endpoints

4. **Automator Management Page** (45 min)
   - Create new page
   - List/Add/Edit/Delete UI
   - Test/Refresh functionality

5. **Home Page Updates** (20 min)
   - First-run welcome banner
   - Dismiss welcome

6. **Automator Controls Page** (15 min)
   - Add Automator selector
   - Update refresh logic

7. **Command Mapping Page** (30 min)
   - Add Automator selector per mapping
   - Update auto-save logic
   - Update test button

8. **Testing** (30 min)
   - End-to-end workflow
   - Migration testing
   - Multi-Automator scenarios

**Total Estimated Time: ~4 hours**

---

## Risks & Considerations

### Backward Compatibility
✅ **Migration handles it**: Old configs automatically converted

### Breaking Changes
⚠️ **Command mappings** now require `automator_id`
- Migration adds this field
- New mappings must specify Automator

### Data Loss Prevention
✅ **Cache preserved**: Per-Automator cache keeps all data
✅ **Config migration**: All settings preserved

### Performance
✅ **No regression**: Still uses httpx connection pooling
✅ **Same caching**: Per-Automator cache equally fast

---

## Success Criteria

- [ ] Fresh v1.1.0 install shows welcome banner
- [ ] v1.0.8 → v1.1.0 upgrade works seamlessly
- [ ] Can add/manage multiple Automators
- [ ] Command mappings target correct Automator
- [ ] All v1.0.8 features still work
- [ ] Performance maintained
- [ ] No data loss in migration

---

## Questions for Review

1. **Config structure** - Does the new `automators` array make sense?
2. **Migration** - Should we keep old `automator` field for safety or remove it?
3. **First-run** - Is the welcome banner helpful or annoying?
4. **UI placement** - Should "Automators" be in nav or under settings?
5. **Default behavior** - What happens if no Automator set as default?
6. **Orphaned mappings** - What to do with mappings when Automator deleted?

---

**Ready to proceed?** Let me know if this plan looks good or if you want changes!
