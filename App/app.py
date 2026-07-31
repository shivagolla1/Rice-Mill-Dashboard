"""
Rice Mill Dashboard
- Orders:  reads from .mdb (IO + IO Details + Confirmation + Journal)
- Stocks:  reads from .mdb (Godowns)
- Data/Explore: full table browser + IO explorer
"""
import sys, os, traceback

# Global crash logger for troubleshooting startup issues
try:
    if getattr(sys, 'frozen', False):
        EXE_DIR = os.path.dirname(sys.executable)
    else:
        EXE_DIR = os.path.dirname(os.path.abspath(__file__))
    log_path = os.path.join(EXE_DIR, "crash_log.txt")
except Exception:
    log_path = "crash_log.txt"

def write_crash(msg):
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            from datetime import datetime
            f.write(f"--- CRASH LOG {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            f.write(msg + "\n\n")
    except:
        pass

sys.excepthook = lambda exctype, value, tb: write_crash("".join(traceback.format_exception(exctype, value, tb)))

# Prevent Flask/Click crashes in PyInstaller --noconsole mode
class DummyWriter:
    def write(self, x): pass
    def flush(self): pass

if sys.stdout is None or not hasattr(sys.stdout, 'write'):
    sys.stdout = DummyWriter()
if sys.stderr is None or not hasattr(sys.stderr, 'write'):
    sys.stderr = DummyWriter()

from flask import Flask, jsonify, render_template, request, redirect, url_for, session, g, send_from_directory, Response


import os, csv, re, io, json, subprocess, time, threading, shutil, gzip
from datetime import datetime, date as dobj

# Support PyInstaller standalone execution
if getattr(sys, 'frozen', False):
    BASE = sys._MEIPASS
else:
    BASE = os.path.dirname(os.path.abspath(__file__))

if BASE not in sys.path:
    sys.path.insert(0, BASE)

app  = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = os.environ.get('SESSION_SECRET', 'RiceMillDashboardSessionSecret2026!')
VERSION = "1.1.0"

# Import Crypto, Auth & Tenants helpers (resolved from sys.path)
import crypto_utils
import auth
import tenants

SUPER_ADMIN_PASSWORD = os.environ.get('SUPER_ADMIN_PASSWORD', 'SuperAdminPass2026!').strip()



# ── FEATURE FLAGS (Hardcode to True/False for client distribution packages) ──
SHOW_STOCKS = os.environ.get('SHOW_STOCKS', 'False').strip().lower() in ('true', '1', 'yes')
SHOW_BI_REPORTS = os.environ.get('SHOW_BI_REPORTS', 'False').strip().lower() in ('true', '1', 'yes')


# ── CONFIG ────────────────────────────────────────────────────────────────────
def load_config():
    d = {
        'MDB_FILE': '',
        'INDUSTRY_NAME': 'Rice Mill',
        'INDUSTRY_ADDRESS': '',
        'APP_TITLE': '',
        'INDUSTRY_LOGO': 'static/logo.jpg',
        'ENABLE_UPDATES': 'False'
    }
    p = os.path.join(EXE_DIR,'config.txt')
    if not os.path.exists(p): return d
    with open(p, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line: continue
            k,_,v = line.partition('='); k,v = k.strip(),v.strip()
            if k in d:
                d[k] = v
            else:
                d[k] = v
    return d

def save_config(mdb_path):
    p = os.path.join(EXE_DIR, 'config.txt')
    lines = []
    has_mdb_file = False
    if os.path.exists(p):
        with open(p, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip().startswith('MDB_FILE='):
                    lines.append(f"MDB_FILE={mdb_path}\n")
                    has_mdb_file = True
                else:
                    lines.append(line)
    if not has_mdb_file:
        lines.append(f"MDB_FILE={mdb_path}\n")
        
    with open(p, 'w', encoding='utf-8') as f:
        f.writelines(lines)

CFG = load_config()

# ── FIRST-RUN DETECTION ───────────────────────────────────────────────────────
def is_first_run():
    name = CFG.get('INDUSTRY_NAME', '').strip()
    return not name or name == 'Rice Mill'

# ── SAVE FULL CONFIG ──────────────────────────────────────────────────────────
def save_full_config(data: dict):
    """Write all config keys to config.txt preserving comments."""
    p = os.path.join(EXE_DIR, 'config.txt')
    # Build a key->line map from existing file to preserve comments
    lines = []
    written = set()
    if os.path.exists(p):
        with open(p, 'r', encoding='utf-8') as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith('#') and '=' in stripped:
                    k = stripped.split('=')[0].strip()
                    if k in data:
                        lines.append(f"{k} = {data[k]}\n")
                        written.add(k)
                        continue
                lines.append(line)
    # Append any keys not already in file
    for k, v in data.items():
        if k not in written:
            lines.append(f"{k} = {v}\n")
    with open(p, 'w', encoding='utf-8') as f:
        f.writelines(lines)

def find_mdb():
    """
    Find the .mdb file to use:
    1. If MDB_FILE in config.txt points to an existing file, use it.
    2. Check DATA_DIR environment variable if specified.
    3. Auto-detect any .mdb in data/ folder, /app/data, or app root.
    """
    configured = CFG.get('MDB_FILE', '').strip()
    if configured:
        full = configured if os.path.isabs(configured) else os.path.join(EXE_DIR, configured)
        if os.path.exists(full):
            return full

    env_data_dir = os.environ.get('DATA_DIR', '').strip()
    search_dirs = []
    if env_data_dir:
        search_dirs.append(env_data_dir)
    search_dirs.extend([os.path.join(EXE_DIR, 'data'), '/app/data', '/app/App/data', EXE_DIR])

    for search_dir in search_dirs:
        if not os.path.isdir(search_dir):
            continue
        files = [f for f in os.listdir(search_dir) if f.lower().endswith('.mdb')]
        if files:
            files.sort(key=lambda f: os.path.getmtime(os.path.join(search_dir, f)), reverse=True)
            return os.path.join(search_dir, files[0])

    default_dir = env_data_dir if env_data_dir else os.path.join(EXE_DIR, 'data')
    return configured if configured and os.path.isabs(configured) else os.path.join(default_dir, 'Database.mdb')

MDB_PATH = find_mdb()


# ── HELPERS ───────────────────────────────────────────────────────────────────
def sf(v):
    try: return float(str(v).replace(',','').strip())
    except: return 0.0

def unscale(v):
    """
    access_parser returns MS Access Currency fields as integers scaled × 10,000
    and some Decimal fields scaled × 100.  Detect and undo the scaling.
    Raw value heuristic: if the raw type from access_parser is int/Decimal and
    the number ends in at least 2 zeros of implied-decimal we divide down.
    We compare the Python type to decide divisor:
      - Python int  → likely Currency ×10,000 → divide by 10,000
      - Python float → already a real float, use as-is (access_parser does fp math)
      - Python Decimal → scaled ×100 → divide by 100
    Fallback: just return sf(v).
    """
    if v is None: return 0.0
    tname = type(v).__name__
    if tname == 'int':
        # Currency type: stored as integer × 10000
        return v / 10000.0
    if tname == 'Decimal':
        # Decimal type: access_parser returns scaled by 10^scale factor
        # Most money fields in Indian accounting use 2 decimal places → ÷100
        return float(v) / 100.0
    return sf(v)

def ss(v):
    if v is None: return ''
    try: return str(v).strip()
    except: return ''

def col_i(cols, hints, exact=False):
    """Find column index by hint keywords."""
    for i,c in enumerate(cols):
        cl = c.lower().strip()
        for h in hints:
            if exact:
                if cl == h.lower(): return i
            else:
                if h.lower() in cl: return i
    return None

def parse_date(v):
    """Return DD.MM.YY string from any date value."""
    if not v: return ''
    s = ss(v)
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', s)
    if m: return f'{m.group(3)}.{m.group(2)}.{m.group(1)[2:]}'
    if re.match(r'\d{2}\.\d{2}\.\d{2,4}', s): return s
    return s

def to_date(v):
    """Convert to date object."""
    if not v: return None
    s = ss(v)
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', s)
    if m:
        try: return dobj(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except: pass
    m2 = re.match(r'(\d{2})\.(\d{2})\.(\d{2,4})', s)
    if m2:
        d,mo,y = int(m2.group(1)), int(m2.group(2)), int(m2.group(3))
        if y < 100: y += 2000
        try: return dobj(y, mo, d)
        except: pass
    return None

def days_between(d1, d2):
    a,b = to_date(d1), to_date(d2)
    return (b-a).days if a and b else None

def days_since(d1):
    a = to_date(d1)
    return (dobj.today()-a).days if a else None

# ── MDB ACCESS + CACHE ────────────────────────────────────────────────────────
import threading


import logging
for _log_name in ("access_parser", "access_parser.access_parser"):
    _lg = logging.getLogger(_log_name)
    _lg.setLevel(logging.CRITICAL)
    _lg.propagate = False

class SuppressStderr:
    def __enter__(self):
        self._orig_stderr = sys.stderr
        try:
            sys.stderr = open(os.devnull, 'w')
        except Exception:
            pass
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if sys.stderr != self._orig_stderr:
                sys.stderr.close()
        except Exception:
            pass
        sys.stderr = self._orig_stderr

def mdb_open(path):
    from access_parser import AccessParser
    with SuppressStderr():
        return AccessParser(path)

def mdb_tables(db):
    return [t for t in db.catalog if not t.startswith('MSys')]

def mdb_read(db, tname):
    with SuppressStderr():
        raw = db.parse_table(tname)
    if not raw: return [], [], []
    cols = list(raw.keys())
    types = []
    for c in cols:
        vals = [v for v in raw[c] if v is not None]
        types.append(type(vals[0]).__name__ if vals else 'str')
    n = len(raw[cols[0]])
    rows = [[raw[c][i] for c in cols] for i in range(n)]
    return cols, types, rows


# ── PER-TENANT MDB ACCESS + CACHE ──────────────────────────────────────────────
import threading

_tenant_caches      = {}   # tenant_id → { "mtime": float, "tables": { tname: (cols, types, rows) } }
_tenant_cache_lock = threading.Lock()

def get_current_tenant_id():
    """Resolve active tenant_id for the current request context."""
    if hasattr(g, 'tenant_id') and g.tenant_id:
        return g.tenant_id
    if 'user' in session and isinstance(session['user'], dict):
        return session['user'].get('tenant_id', 'client_sgri')
    if 'tenant_id' in session and session['tenant_id']:
        return session['tenant_id']
    return 'client_sgri'

def get_current_tenant_mdb_path():
    """Return absolute path to the active tenant's Database.mdb file."""
    tenant_id = get_current_tenant_id()
    tenant_dir = tenants.get_tenant_dir(tenant_id)
    tenant_mdb = os.path.join(tenant_dir, 'Database.mdb')
    if os.path.exists(tenant_mdb):
        return tenant_mdb
    # Fallback to single-tenant MDB_PATH ONLY for primary tenant client_sgri
    if tenant_id == 'client_sgri' and 'MDB_PATH' in globals() and MDB_PATH and os.path.exists(MDB_PATH):
        return MDB_PATH
    return tenant_mdb

def get_cached_table(tname, tenant_id=None):
    """Return (cols, types, rows) from per-tenant in-memory cache."""
    if not tenant_id:
        tenant_id = get_current_tenant_id()

    mdb_path = get_current_tenant_mdb_path()
    if not mdb_path or not os.path.exists(mdb_path):
        return [], [], []

    try:
        mtime = os.path.getmtime(mdb_path)
    except Exception:
        return [], [], []

    with _tenant_cache_lock:
        if tenant_id not in _tenant_caches:
            _tenant_caches[tenant_id] = {"mtime": None, "tables": {}}
        t_cache = _tenant_caches[tenant_id]

        if t_cache["mtime"] == mtime and tname in t_cache["tables"]:
            return t_cache["tables"][tname]

    # Cache miss or modified file → parse table from disk
    try:
        db   = mdb_open(mdb_path)
        tbls = mdb_tables(db)
        with _tenant_cache_lock:
            if t_cache["mtime"] != mtime:
                t_cache["tables"].clear()
                t_cache["mtime"] = mtime
            if tname in tbls:
                t_cache["tables"][tname] = mdb_read(db, tname)
            else:
                t_cache["tables"][tname] = ([], [], [])
            return t_cache["tables"][tname]
    except Exception:
        return [], [], []

def get_cached_db():
    """Return a dict-like helper serving tables from the active tenant's database."""
    class CachedDB:
        def __init__(self):
            self._tables = None
        def tables(self):
            if self._tables is None:
                mdb_path = get_current_tenant_mdb_path()
                if not mdb_path or not os.path.exists(mdb_path): return []
                try:
                    db = mdb_open(mdb_path)
                    self._tables = mdb_tables(db)
                except: self._tables = []
            return self._tables
    return CachedDB()

def read_table(tname):
    """Open mdb and read one table. Returns (cols, types, rows) or ([], [], [])."""
    return get_cached_table(tname)


# ── ORDERS (IO + IO Details + Confirmation + Journal summary) ─────────────────
def get_transactions(mode_filter):
    mdb_path = get_current_tenant_mdb_path()
    if not os.path.exists(mdb_path):
        return []


    try:
        # Use cached tables — parsed once on startup, instant on subsequent calls
        io_cols,  _, io_rows   = get_cached_table('IO')
        det_cols, _, det_rows  = get_cached_table('IO Details')
        con_cols, _, con_rows  = get_cached_table('Confirmation')
        oth_cols, _, oth_rows  = get_cached_table('IO Other Details')

        if not io_cols:
            return {'error': 'IO table not found'}

        # ── IO column positions ───────────────────────────────────
        io_id_i    = col_i(io_cols, ['io id','ioid','id'])
        bill_no_i  = col_i(io_cols, ['bill no','billno'])
        date_i     = col_i(io_cols, ['transaction date','date','transdate','loaded'])
        conf_id_i  = col_i(io_cols, ['confirmation id','confirmid','confirm id','conf'])
        type_i     = col_i(io_cols, ['type'])
        mode_i     = col_i(io_cols, ['mode'])
        io_party_i = col_i(io_cols, ['party name','party','partyname'])  # fallback party

        # ── IO Details positions ──────────────────────────────────
        d_ioid_i  = col_i(det_cols, ['io id','ioid'])
        variety_i = col_i(det_cols, ['variety'])
        bags_i    = col_i(det_cols, ['bags'])
        unit_i    = col_i(det_cols, ['unit'])
        qtl_i     = col_i(det_cols, ['quintal','qtl','qty'])
        rate_i    = col_i(det_cols, ['rate'])
        amount_i  = col_i(det_cols, ['amount'])

        # ── Confirmation positions ────────────────────────────────
        c_id_i     = col_i(con_cols, ['confirmation id','conf id','id'])
        c_party_i  = col_i(con_cols, ['party name','party','partyname'])
        c_broker_i = col_i(con_cols, ['broker name','broker'])

        # ── Lookups ───────────────────────────────────────────────
        # Confirmation: conf_id → {party, broker}
        conf_lkp = {}
        for r in con_rows:
            cid = ss(r[c_id_i]) if c_id_i is not None else ''
            conf_lkp[cid] = {
                'party':  ss(r[c_party_i])  if c_party_i  is not None else '',
                'broker': ss(r[c_broker_i]) if c_broker_i is not None else '',
            }

        # IO Details: io_id → LIST of rows (can be multiple per IO ID)
        det_lkp = {}
        for r in det_rows:
            did = ss(r[d_ioid_i]) if d_ioid_i is not None else ''
            det_lkp.setdefault(did, []).append(r)

        # IO Other Details: io_id → PNo (Cash Discount)
        oth_lkp = {}
        if oth_cols:
            o_ioid_i = col_i(oth_cols, ['io id', 'ioid'])
            pno_i    = col_i(oth_cols, ['pno'])
            if o_ioid_i is not None and pno_i is not None:
                for r in oth_rows:
                    oid = ss(r[o_ioid_i])
                    val = ss(r[pno_i])
                    oth_lkp[oid] = val

        def agg_details(rows):
            """Return per-row details list plus totals."""
            if not rows:
                return None
            detail_rows = []
            for r in rows:
                detail_rows.append({
                    'variety': ss(r[variety_i]) if variety_i is not None else '—',
                    'bags':    sf(r[bags_i])    if bags_i    is not None else 0,
                    'unit':    ss(r[unit_i])    if unit_i    is not None else '',
                    'qtl':     round(sf(r[qtl_i]), 2) if qtl_i is not None else 0,
                    'rate':    unscale(r[rate_i]) if rate_i  is not None else 0,
                    'amount':  round(unscale(r[amount_i]), 2) if amount_i is not None else 0,
                })
            total_bags   = sum(d['bags']   for d in detail_rows)
            total_qtl    = round(sum(d['qtl']    for d in detail_rows), 2)
            total_amount = round(sum(d['amount'] for d in detail_rows), 2)
            # Summary variety: join unique values
            varieties = ' / '.join(dict.fromkeys(d['variety'] for d in detail_rows))
            units     = ' / '.join(dict.fromkeys(d['unit']     for d in detail_rows))
            return {
                'variety': varieties or '—',
                'bags':    total_bags,
                'unit':    units,
                'qtl':     total_qtl,
                'amount':  total_amount,
                'multi':   len(detail_rows) > 1,
                'details': detail_rows,   # individual line items
            }

        # Get payments from Journal table
        jnl_cols, _, jnl_rows = get_cached_table('Journal')
        j_ioid_i   = col_i(jnl_cols, ['io id','ioid'])
        j_date_i   = col_i(jnl_cols, ['transaction date','date','paydate'])
        j_dr_i     = col_i(jnl_cols, ['dr account','dr','debit','party'])
        j_cr_i     = col_i(jnl_cols, ['cr account','cr','credit'])
        j_amount_i = col_i(jnl_cols, ['amount'])

        payments_map = {}
        if j_ioid_i is not None and j_amount_i is not None:
            for r in jnl_rows:
                ioid = ss(r[j_ioid_i])
                if ioid:
                    amt = unscale(r[j_amount_i])
                    pay_raw = ss(r[j_date_i]) if j_date_i is not None else ''
                    dr = ss(r[j_dr_i]) if j_dr_i is not None else ''
                    cr = ss(r[j_cr_i]) if j_cr_i is not None else ''
                    
                    payments_map.setdefault(ioid, {'total': 0.0, 'entries': []})
                    payments_map[ioid]['total'] += amt
                    payments_map[ioid]['entries'].append({
                        'pay_date': parse_date(pay_raw),
                        'pay_raw': pay_raw,
                        'dr_account': dr,
                        'cr_account': cr,
                        'amount': amt
                    })

        # Get adjustments from IO DC table
        dc_cols, _, dc_rows = get_cached_table('IO DC')
        dc_ioid_i = col_i(dc_cols, ['io id','ioid'])
        dc_cred_i = col_i(dc_cols, ['credit'])
        dc_deb_i  = col_i(dc_cols, ['debit'])
        dc_acc_i  = col_i(dc_cols, ['account'])

        dc_map = {}
        if dc_ioid_i is not None and dc_cred_i is not None and dc_deb_i is not None and dc_acc_i is not None:
            for r in dc_rows:
                ioid = ss(r[dc_ioid_i])
                if ioid:
                    crd = unscale(r[dc_cred_i])
                    deb = unscale(r[dc_deb_i])
                    acc = ss(r[dc_acc_i])
                    if crd > 0 or deb > 0:
                        dc_map.setdefault(ioid, []).append({
                            'account': acc,
                            'credit': crd,
                            'debit': deb
                        })

        # ── Build transactions ────────────────────────────────────
        orders = []
        for row in io_rows:
            mode_val = ss(row[mode_i]).lower()  if mode_i  is not None else ''
            type_val = ss(row[type_i]).lower()  if type_i  is not None else ''

            if mode_filter == 'sales':
                if 'sale' not in mode_val and 'sale' not in type_val:
                    continue
            else:
                if 'purchase' not in mode_val and 'purchase' not in type_val:
                    continue

            io_id    = ss(row[io_id_i])   if io_id_i   is not None else ''
            bill_no  = ss(row[bill_no_i])  if bill_no_i is not None else ''
            conf_id  = ss(row[conf_id_i]) if conf_id_i is not None else ''
            raw_date = row[date_i]        if date_i    is not None else ''

            conf     = conf_lkp.get(conf_id, {'party':'','broker':''})
            # Fallback: if Confirmation has no party name, use IO.Party Name
            io_party = ss(row[io_party_i]) if io_party_i is not None else ''
            det    = agg_details(det_lkp.get(io_id, []))
            amount = det['amount'] if det else 0
            
            pay_info = payments_map.get(io_id, {'total': 0.0, 'entries': []})
            paid_amt = pay_info['total']
            
            # Enrich entries with days_to_pay
            entries = []
            for entry in pay_info['entries']:
                dtp = days_between(raw_date, entry['pay_raw'])
                entries.append({
                    'pay_date': entry['pay_date'],
                    'dr_account': entry['dr_account'],
                    'cr_account': entry['cr_account'],
                    'amount': entry['amount'],
                    'days_to_pay': dtp
                })
            # Sort entries by pay_date
            entries.sort(key=lambda x: x['pay_date'] or '')

            # Get adjustments from IO DC
            adjustments = dc_map.get(io_id, [])
            total_credit = sum(adj['credit'] for adj in adjustments)
            total_debit  = sum(adj['debit'] for adj in adjustments)

            if mode_filter != 'sales':
                balance = round(max(amount - total_credit + total_debit - paid_amt, 0.0), 2)
            else:
                balance = round(max(amount - paid_amt, 0.0), 2)

            orders.append({
                'io_id':       io_id,
                'bill_no':     bill_no,
                'conf_id':     conf_id,
                'party':       conf['party'] or io_party or '—',
                'broker':      conf['broker'] or '—',
                'loaded_date': parse_date(raw_date),
                'loaded_raw':  ss(raw_date),
                'type':        ss(row[type_i])  if type_i  is not None else '',
                'mode':        ss(row[mode_i])  if mode_i  is not None else '',
                'variety':     det['variety'] if det else '—',
                'bags':        det['bags']    if det else 0,
                'unit':        det['unit']    if det else '',
                'qtl':         det['qtl']     if det else 0,
                'amount':      amount,
                'paid':        round(paid_amt, 2),
                'balance':     balance,
                'multi_det':   det['multi']   if det else False,
                'details':     det['details'] if det else [],
                'adjustments': adjustments,
                'payments':    entries,
                'days_since_load': days_since(raw_date),
                'cd':          oth_lkp.get(io_id, ''),
            })

        return orders

    except Exception as e:
        return {'error': str(e)}


@app.route('/api/orders')
def api_orders():
    res = get_transactions('sales')
    if isinstance(res, dict) and 'error' in res:
        return jsonify(res)
    return jsonify({'status':'ok','orders':res,'count':len(res)})


@app.route('/api/purchases')
def api_purchases():
    res = get_transactions('purchases')
    if isinstance(res, dict) and 'error' in res:
        return jsonify(res)
    return jsonify({'status':'ok','orders':res,'count':len(res)})


@app.route('/api/journal')
def api_journal_all():
    """Return every Journal row for the Journal page."""
    mdb_path = get_current_tenant_mdb_path()
    if not os.path.exists(mdb_path):
        return jsonify({'error':'file_not_found'})
    try:
        jnl_cols, _, jnl_rows = get_cached_table('Journal')
        if not jnl_cols:
            return jsonify([])

        j_id_i     = col_i(jnl_cols, ['journal id'])
        j_date_i   = col_i(jnl_cols, ['transaction date','date'])
        j_amt_i    = col_i(jnl_cols, ['amount'])
        j_ioid_i   = col_i(jnl_cols, ['io id','ioid'])
        j_dr_i     = col_i(jnl_cols, ['dr account'])
        j_cr_i     = col_i(jnl_cols, ['cr account'])
        j_det_i    = col_i(jnl_cols, ['details'])
        j_ctrl_i   = col_i(jnl_cols, ['ctrl id'])
        j_type_i   = col_i(jnl_cols, ['type'])
        j_repno_i  = col_i(jnl_cols, ['report no'])
        j_vno_i    = col_i(jnl_cols, ['voucher no'])

        out = []
        for r in jnl_rows:
            raw_date = ss(r[j_date_i]) if j_date_i is not None else ''
            out.append({
                'journal_id':  r[j_id_i]  if j_id_i  is not None else '',
                'raw_date':    raw_date,
                'date':        parse_date(raw_date),
                'amount':      unscale(r[j_amt_i]) if j_amt_i is not None else 0,
                'io_id':       r[j_ioid_i] if j_ioid_i is not None else '',
                'dr_account':  ss(r[j_dr_i])  if j_dr_i  is not None else '',
                'cr_account':  ss(r[j_cr_i])  if j_cr_i  is not None else '',
                'details':     ss(r[j_det_i]) if j_det_i is not None else '',
                'ctrl_id':     ss(r[j_ctrl_i]) if j_ctrl_i is not None else '',
                'type':        ss(r[j_type_i]) if j_type_i is not None else '',
                'report_no':   ss(r[j_repno_i]) if j_repno_i is not None else '',
                'voucher_no':  ss(r[j_vno_i])  if j_vno_i  is not None else '',
            })

        out.sort(key=lambda x: x['raw_date'] or '', reverse=True)
        return jsonify(out)

    except ImportError:
        return jsonify({'error':'not_installed'})
    except Exception as e:
        return jsonify({'error': str(e)})


@app.route('/api/reports/summary')
def api_reports_summary():
    """Simplified P&L report and interactive Broker/Party analyzer."""
    if not SHOW_BI_REPORTS:
        return jsonify({'error': 'BI Reports are disabled.'}), 403
    mdb_path = get_current_tenant_mdb_path()
    if not os.path.exists(mdb_path):
        return jsonify({'error': 'file_not_found'})

    try:
        from_date_str = request.args.get('from', '')
        to_date_str = request.args.get('to', '')

        from_date = to_date(from_date_str) if from_date_str else None
        to_date_val = to_date(to_date_str) if to_date_str else None

        sales = get_transactions('sales')
        purchases = get_transactions('purchases')

        if isinstance(sales, dict) and 'error' in sales:
            return jsonify(sales)
        if isinstance(purchases, dict) and 'error' in purchases:
            return jsonify(purchases)

        # 1. Sales variety breakdown
        sales_rice = {}
        sales_broken = {'qtl': 0.0, 'amount': 0.0}
        sales_bran = {'qtl': 0.0, 'amount': 0.0}
        sales_husk = {'qtl': 0.0, 'amount': 0.0}
        sales_others = {'qtl': 0.0, 'amount': 0.0}

        # 2. Purchases variety breakdown
        purch_paddy = {}
        purch_others = {'qtl': 0.0, 'amount': 0.0}

        # 3. Party & Broker stats
        party_stats = {}
        broker_stats = {}

        def get_stats_node():
            return {
                'sales_qtl': 0.0, 'sales_amount': 0.0, 'sales_count': 0,
                'purchases_qtl': 0.0, 'purchases_amount': 0.0, 'purchases_count': 0
            }

        # Process sales
        for tx in sales:
            tx_date = to_date(tx['loaded_raw'])
            if tx_date:
                if from_date and tx_date < from_date: continue
                if to_date_val and tx_date > to_date_val: continue

            party = tx['party'].strip() or '—'
            broker = tx['broker'].strip() or '—'

            if party not in party_stats: party_stats[party] = get_stats_node()
            party_stats[party]['sales_amount'] += tx['amount']
            party_stats[party]['sales_qtl'] += tx['qtl']
            party_stats[party]['sales_count'] += 1

            if broker not in broker_stats: broker_stats[broker] = get_stats_node()
            broker_stats[broker]['sales_amount'] += tx['amount']
            broker_stats[broker]['sales_qtl'] += tx['qtl']
            broker_stats[broker]['sales_count'] += 1

            details = tx.get('details', [])
            if not details:
                details = [{
                    'variety': tx.get('variety', '—'),
                    'qtl': tx.get('qtl', 0.0),
                    'amount': tx.get('amount', 0.0)
                }]

            for d in details:
                var = d['variety'].strip() or '—'
                v_lower = var.lower()
                qtl = d['qtl']
                amt = d['amount']

                if 'broken' in v_lower:
                    sales_broken['qtl'] += qtl
                    sales_broken['amount'] += amt
                elif 'bran' in v_lower:
                    sales_bran['qtl'] += qtl
                    sales_bran['amount'] += amt
                elif 'husk' in v_lower:
                    sales_husk['qtl'] += qtl
                    sales_husk['amount'] += amt
                elif 'rice' in v_lower:
                    if var not in sales_rice: sales_rice[var] = {'qtl': 0.0, 'amount': 0.0}
                    sales_rice[var]['qtl'] += qtl
                    sales_rice[var]['amount'] += amt
                else:
                    sales_others['qtl'] += qtl
                    sales_others['amount'] += amt

        # Process purchases
        for tx in purchases:
            tx_date = to_date(tx['loaded_raw'])
            if tx_date:
                if from_date and tx_date < from_date: continue
                if to_date_val and tx_date > to_date_val: continue

            party = tx['party'].strip() or '—'
            broker = tx['broker'].strip() or '—'

            if party not in party_stats: party_stats[party] = get_stats_node()
            party_stats[party]['purchases_amount'] += tx['amount']
            party_stats[party]['purchases_qtl'] += tx['qtl']
            party_stats[party]['purchases_count'] += 1

            if broker not in broker_stats: broker_stats[broker] = get_stats_node()
            broker_stats[broker]['purchases_amount'] += tx['amount']
            broker_stats[broker]['purchases_qtl'] += tx['qtl']
            broker_stats[broker]['purchases_count'] += 1

            details = tx.get('details', [])
            if not details:
                details = [{
                    'variety': tx.get('variety', '—'),
                    'qtl': tx.get('qtl', 0.0),
                    'amount': tx.get('amount', 0.0)
                }]

            for d in details:
                var = d['variety'].strip() or '—'
                v_lower = var.lower()
                qtl = d['qtl']
                amt = d['amount']

                if 'paddy' in v_lower:
                    if var not in purch_paddy: purch_paddy[var] = {'qtl': 0.0, 'amount': 0.0}
                    purch_paddy[var]['qtl'] += qtl
                    purch_paddy[var]['amount'] += amt
                else:
                    purch_others['qtl'] += qtl
                    purch_others['amount'] += amt

        # Process expenses from Journal table
        j_cols, _, j_rows = get_cached_table('Journal')
        j_dr_i = col_i(j_cols, ['dr account'])
        j_cr_i = col_i(j_cols, ['cr account'])
        j_amt_i = col_i(j_cols, ['amount'])
        j_date_i = col_i(j_cols, ['transaction date', 'date'])

        paddy_freight = 0.0
        direct_labor = 0.0
        construction = 0.0
        new_godown = 0.0

        for r in j_rows:
            dt = ss(r[j_date_i]) if j_date_i is not None else ''
            tx_date = to_date(dt)
            if tx_date:
                if from_date and tx_date < from_date: continue
                if to_date_val and tx_date > to_date_val: continue

            dr = ss(r[j_dr_i]).strip()
            cr = ss(r[j_cr_i]).strip()
            amt = unscale(r[j_amt_i])

            if cr == 'Paddy Frieght' or dr == 'Paddy Lorry Advance':
                paddy_freight += amt
            elif cr in ('Labour Charges', 'Hamali'):
                direct_labor += amt
            elif cr == 'Construction':
                construction += amt
            elif cr == 'New Godown':
                new_godown += amt

        # Post-process variety stats to include average rate and round values
        def finalize_variety_map(m):
            out = {}
            for k, v in m.items():
                q = round(v['qtl'], 2)
                a = round(v['amount'], 2)
                rate = round(a / q, 2) if q > 0 else 0.0
                out[k] = {'qtl': q, 'amount': a, 'rate': rate}
            return out

        sales_rice_final = finalize_variety_map(sales_rice)
        purch_paddy_final = finalize_variety_map(purch_paddy)

        sales_broken_final = {'qtl': round(sales_broken['qtl'], 2), 'amount': round(sales_broken['amount'], 2), 'rate': round(sales_broken['amount'] / sales_broken['qtl'], 2) if sales_broken['qtl'] > 0 else 0.0}
        sales_bran_final = {'qtl': round(sales_bran['qtl'], 2), 'amount': round(sales_bran['amount'], 2), 'rate': round(sales_bran['amount'] / sales_bran['qtl'], 2) if sales_bran['qtl'] > 0 else 0.0}
        sales_husk_final = {'qtl': round(sales_husk['qtl'], 2), 'amount': round(sales_husk['amount'], 2), 'rate': round(sales_husk['amount'] / sales_husk['qtl'], 2) if sales_husk['qtl'] > 0 else 0.0}
        sales_others_final = {'qtl': round(sales_others['qtl'], 2), 'amount': round(sales_others['amount'], 2), 'rate': round(sales_others['amount'] / sales_others['qtl'], 2) if sales_others['qtl'] > 0 else 0.0}

        purch_others_final = {'qtl': round(purch_others['qtl'], 2), 'amount': round(purch_others['amount'], 2), 'rate': round(purch_others['amount'] / purch_others['qtl'], 2) if purch_others['qtl'] > 0 else 0.0}

        # Calculate totals
        total_revenue = sum(v['amount'] for v in sales_rice_final.values()) + sales_broken_final['amount'] + sales_bran_final['amount'] + sales_husk_final['amount'] + sales_others_final['amount']
        total_direct_costs = sum(v['amount'] for v in purch_paddy_final.values()) + purch_others_final['amount'] + paddy_freight + direct_labor
        net_contribution = total_revenue - total_direct_costs

        # Finalize party and broker list
        def finalize_summary_list(stats_map):
            lst = []
            for name, s in stats_map.items():
                if name == '—': continue
                lst.append({
                    'name': name,
                    'sales_qtl': round(s['sales_qtl'], 2),
                    'sales_amount': round(s['sales_amount'], 2),
                    'sales_count': s['sales_count'],
                    'purchases_qtl': round(s['purchases_qtl'], 2),
                    'purchases_amount': round(s['purchases_amount'], 2),
                    'purchases_count': s['purchases_count']
                })
            return lst

        res = {
            'sales_summary': {
                'rice_varieties': sales_rice_final,
                'broken_rice': sales_broken_final,
                'bran': sales_bran_final,
                'husk': sales_husk_final,
                'others': sales_others_final,
                'total_amount': round(total_revenue, 2)
            },
            'purchases_summary': {
                'paddy_varieties': purch_paddy_final,
                'others': purch_others_final,
                'total_amount': round(total_direct_costs, 2)
            },
            'expenses': {
                'paddy_freight': round(paddy_freight, 2),
                'direct_labor': round(direct_labor, 2)
            },
            'capital_expenditures': {
                'construction': round(construction, 2),
                'new_godown': round(new_godown, 2)
            },
            'net_trading_contribution': round(net_contribution, 2),
            'broker_summary': finalize_summary_list(broker_stats),
            'party_summary': finalize_summary_list(party_stats)
        }

        return jsonify(res)

    except Exception as e:
        return jsonify({'error': str(e)})



@app.route('/api/journal/<io_id>')
def api_journal(io_id):
    """All Journal entries for one IO ID with days-to-pay calculation."""
    mdb_path = get_current_tenant_mdb_path()
    if not os.path.exists(mdb_path):
        return jsonify({'error':'file_not_found'})
    try:
        jnl_cols, _, jnl_rows = get_cached_table('Journal')
        io_cols,  _, io_rows  = get_cached_table('IO')


        j_ioid_i   = col_i(jnl_cols, ['io id','ioid'])
        j_date_i   = col_i(jnl_cols, ['transaction date','date','paydate'])
        j_dr_i     = col_i(jnl_cols, ['dr account','dr','debit','party'])
        j_cr_i     = col_i(jnl_cols, ['cr account','cr','credit'])
        j_amount_i = col_i(jnl_cols, ['amount'])

        io_id_i = col_i(io_cols, ['io id','ioid','id'])
        date_i  = col_i(io_cols, ['transaction date','date'])

        # Get loaded date from IO
        loaded_raw = ''
        for r in io_rows:
            if io_id_i is not None and ss(r[io_id_i]) == io_id:
                loaded_raw = ss(r[date_i]) if date_i is not None else ''
                break

        # Get journal entries
        matched = [r for r in jnl_rows
                   if j_ioid_i is not None and ss(r[j_ioid_i]) == io_id]

        total_paid = 0
        entries = []
        for r in matched:
            pay_raw  = ss(r[j_date_i])   if j_date_i   is not None else ''
            dr       = ss(r[j_dr_i])     if j_dr_i     is not None else ''
            cr       = ss(r[j_cr_i])     if j_cr_i     is not None else ''
            amt      = unscale(r[j_amount_i]) if j_amount_i is not None else 0
            dtp      = days_between(loaded_raw, pay_raw)
            total_paid += amt
            entries.append({
                'pay_date':    parse_date(pay_raw),
                'pay_raw':     pay_raw,
                'dr_account':  dr,
                'cr_account':  cr,
                'amount':      amt,
                'days_to_pay': dtp,
            })

        entries.sort(key=lambda x: x['pay_date'] or '')

        # Get adjustments from IO DC
        dc_cols, _, dc_rows = get_cached_table('IO DC')
        dc_ioid_i = col_i(dc_cols, ['io id','ioid'])
        dc_cred_i = col_i(dc_cols, ['credit'])
        dc_deb_i  = col_i(dc_cols, ['debit'])
        dc_acc_i  = col_i(dc_cols, ['account'])

        adjustments = []
        if dc_ioid_i is not None and dc_cred_i is not None and dc_deb_i is not None and dc_acc_i is not None:
            for r in dc_rows:
                if ss(r[dc_ioid_i]) == io_id:
                    crd = unscale(r[dc_cred_i])
                    deb = unscale(r[dc_deb_i])
                    acc = ss(r[dc_acc_i])
                    if crd > 0 or deb > 0:
                        adjustments.append({
                            'account': acc,
                            'credit': crd,
                            'debit': deb
                        })

        return jsonify({
            'io_id':         io_id,
            'loaded_date':   parse_date(loaded_raw),
            'loaded_raw':    loaded_raw,
            'entries':       entries,
            'total_paid':    round(total_paid, 2),
            'days_since_load': days_since(loaded_raw),
            'adjustments':   adjustments,
        })

    except ImportError:
        return jsonify({'error':'not_installed'})
    except Exception as e:
        return jsonify({'error': str(e)})


# ── STOCKS TRIAL BALANCE ──────────────────────────────────────────────────────
# Only show Paddy and Raw Rice varieties on the Stocks page
ALLOWED_PREFIXES = ('paddy', 'raw rice')

@app.route('/api/stocks/trial-balance')
def api_stocks_trial_balance():
    """Schedule Trial Balance grouped by Variety → Type+Mode."""
    if not SHOW_STOCKS:
        return jsonify({'error': 'Stocks page is disabled.'}), 403
    mdb_path = get_current_tenant_mdb_path()
    if not os.path.exists(mdb_path):
        return jsonify({'error': 'file_not_found'})

    try:
        io_cols,  _, io_rows  = get_cached_table('IO')
        det_cols, _, det_rows = get_cached_table('IO Details')

        # IO index by IO ID → {type, mode, date}
        io_id_i   = col_i(io_cols, ['io id'])
        io_type_i = col_i(io_cols, ['type'])
        io_mode_i = col_i(io_cols, ['mode'])
        io_date_i = col_i(io_cols, ['transaction date', 'date'])

        io_map = {}
        for r in io_rows:
            iid = r[io_id_i] if io_id_i is not None else None
            if iid is None: continue
            io_map[iid] = {
                'type': ss(r[io_type_i]) if io_type_i is not None else '',
                'mode': ss(r[io_mode_i]) if io_mode_i is not None else '',
                'date': ss(r[io_date_i]) if io_date_i is not None else '',
            }

        # IO Details columns
        d_ioid_i = col_i(det_cols, ['io id'])
        d_var_i  = col_i(det_cols, ['variety'])
        d_bags_i = col_i(det_cols, ['bags'])
        d_qtl_i  = col_i(det_cols, ['quintals'])
        d_amt_i  = col_i(det_cols, ['amount'])

        # Accumulate: variety → (type, mode) → {bags, qtls, jama, kharchu, min_date}
        from collections import defaultdict
        groups = defaultdict(lambda: defaultdict(lambda: {
            'bags': 0.0, 'qtls': 0.0, 'jama': 0.0, 'kharchu': 0.0, 'min_date': ''
        }))

        for r in det_rows:
            variety = ss(r[d_var_i]) if d_var_i is not None else ''
            # Allowlist: only keep Paddy and Raw Rice
            if not variety or not any(variety.lower().startswith(p) for p in ALLOWED_PREFIXES):
                continue
            iid  = r[d_ioid_i] if d_ioid_i is not None else None
            io   = io_map.get(iid, {'type': '', 'mode': '', 'date': ''})
            typ  = io['type']
            mode = io['mode']
            # Include "Direct" entries (type="Direct", mode="") — skip only truly blank rows
            if not typ and not mode:
                continue

            bags = float(r[d_bags_i] or 0) if d_bags_i is not None else 0.0
            qtls = float(r[d_qtl_i]  or 0) if d_qtl_i  is not None else 0.0
            amt  = unscale(r[d_amt_i])      if d_amt_i  is not None else 0.0

            key = (typ, mode)
            grp = groups[variety][key]
            grp['bags']    += bags
            grp['qtls']    += qtls
            grp['min_date'] = io['date'] if (not grp['min_date'] or io['date'] < grp['min_date']) else grp['min_date']

            # Sales → Jama; everything else (Purchases, Sales Returns, Direct) → Kharchu
            if mode == 'Sales':
                grp['jama']    += amt
            else:
                grp['kharchu'] += amt

        # Serialize into ordered list
        result = []
        for variety in sorted(groups.keys()):
            subrows = []
            for (typ, mode) in sorted(groups[variety].keys()):
                grp = groups[variety][(typ, mode)]
                # Build label cleanly — skip empty parts so no trailing spaces
                parts = [p for p in [variety, typ, mode] if p]
                label = '  '.join(parts)
                subrows.append({
                    'account':  label,
                    'type':     typ,
                    'mode':     mode,
                    'bags':     round(grp['bags'],  2),
                    'qtls':     round(grp['qtls'],  2),
                    'jama':     round(grp['jama'],  2),
                    'kharchu':  round(grp['kharchu'], 2),
                    'min_date': parse_date(grp['min_date']),
                })
            result.append({'variety': variety, 'rows': subrows})

        return jsonify(result)


    except ImportError:
        return jsonify({'error': 'not_installed'})
    except Exception as e:
        return jsonify({'error': str(e)})


@app.route('/api/database-status')
def api_database_status():
    mdb_path = get_current_tenant_mdb_path()
    exists = os.path.exists(mdb_path) if mdb_path else False
    return jsonify({
        'path': mdb_path or '',
        'filename': os.path.basename(mdb_path) if (mdb_path and exists) else '',
        'exists': exists,
        'cache_ready': True
    })


def ctypes_select_file():
    import ctypes
    from ctypes import wintypes
    
    class OPENFILENAMEW(ctypes.Structure):
        _fields_ = [
            ("lStructSize", wintypes.DWORD),
            ("hwndOwner", wintypes.HWND),
            ("hInstance", wintypes.HINSTANCE),
            ("lpstrFilter", wintypes.LPCWSTR),
            ("lpstrCustomFilter", wintypes.LPWSTR),
            ("nMaxCustFilter", wintypes.DWORD),
            ("nFilterIndex", wintypes.DWORD),
            ("lpstrFile", wintypes.LPWSTR),
            ("nMaxFile", wintypes.DWORD),
            ("lpstrFileTitle", wintypes.LPWSTR),
            ("nMaxFileTitle", wintypes.DWORD),
            ("lpstrInitialDir", wintypes.LPCWSTR),
            ("lpstrTitle", wintypes.LPCWSTR),
            ("Flags", wintypes.DWORD),
            ("nFileOffset", wintypes.WORD),
            ("nFileExtension", wintypes.WORD),
            ("lpstrDefExt", wintypes.LPCWSTR),
            ("lCustData", wintypes.LPARAM),
            ("lpfnHook", ctypes.c_void_p),
            ("lpTemplateName", wintypes.LPCWSTR),
            ("pvReserved", ctypes.c_void_p),
            ("dwReserved", wintypes.DWORD),
            ("FlagsEx", wintypes.DWORD),
        ]
        
    ofn = OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
    
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        ofn.hwndOwner = hwnd
    except:
        ofn.hwndOwner = None
        
    ofn.lpstrFilter = "Access File (*.mdb)\0*.mdb\0All Files (*.*)\0*.*\0"
    
    buffer_size = 1024
    file_buffer = ctypes.create_unicode_buffer(buffer_size)
    ofn.lpstrFile = ctypes.cast(file_buffer, wintypes.LPWSTR)
    ofn.nMaxFile = buffer_size
    
    ofn.lpstrTitle = "Select Access File File"
    ofn.Flags = 0x00000800 | 0x00001000 | 0x00000008
    
    if ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(ofn)):
        return file_buffer.value
    return ""

@app.route('/api/select-database', methods=['POST'])
def api_select_database():
    global MDB_PATH

    
    selected_path = ""
    
    # Check if manual path was submitted via JSON
    body = request.get_json(silent=True) or {}
    manual_path = body.get('path', '').strip()
    
    if manual_path:
        # Check if relative or absolute
        if not os.path.isabs(manual_path):
            full_path = os.path.join(EXE_DIR, manual_path)
        else:
            full_path = manual_path
            
        if os.path.exists(full_path):
            selected_path = full_path
        else:
            return jsonify({'status': 'error', 'message': f"File not found: {manual_path}"})
    else:
        # Try 1: ctypes dialog (preferred on Windows)
        if os.name == 'nt':
            try:
                selected_path = ctypes_select_file()
            except Exception as e:
                print("ctypes dialog failed:", e)
                
        # Try 2: PowerShell dialog fallback
        if not selected_path:
            cmd = (
                "Add-Type -AssemblyName System.Windows.Forms; "
                "$dialog = New-Object System.Windows.Forms.OpenFileDialog; "
                "$dialog.Filter = 'Access File (*.mdb)|*.mdb'; "
                "$dialog.Title = 'Select Access File File'; "
                "$dialog.InitialDirectory = [System.IO.Directory]::GetCurrentDirectory(); "
                "$res = $dialog.ShowDialog(); "
                "if ($res -eq 'OK') { Write-Output $dialog.FileName }"
            )
            
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0 # SW_HIDE
                
            try:
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-STA", "-Command", cmd],
                    capture_output=True,
                    text=True,
                    startupinfo=startupinfo
                )
                selected_path = result.stdout.strip()
            except Exception as e:
                print("PowerShell dialog failed:", e)
                
        # Try 3: tkinter dialog fallback
        if not selected_path:
            tk_script = (
                "import tkinter as tk; "
                "import tkinter.filedialog as fd; "
                "root = tk.Tk(); "
                "root.withdraw(); "
                "root.wm_attributes('-topmost', 1); "
                "path = fd.askopenfilename(title='Select Access File File', filetypes=[('Access File', '*.mdb')]); "
                "if path: print(path)"
            )
            try:
                result = subprocess.run(
                    ["python", "-c", tk_script],
                    capture_output=True,
                    text=True,
                    startupinfo=startupinfo
                )
                selected_path = result.stdout.strip()
            except Exception as e:
                print("Tkinter dialog fallback failed:", e)
                
    try:
        if selected_path and os.path.exists(selected_path):
            save_config(selected_path)
            MDB_PATH = selected_path
            
            tenant_id = get_current_tenant_id()
            with _tenant_cache_lock:
                if tenant_id in _tenant_caches:
                    _tenant_caches[tenant_id]["mtime"] = None
                    _tenant_caches[tenant_id]["tables"].clear()

            
            return jsonify({
                'status': 'ok',
                'path': MDB_PATH,
                'filename': os.path.basename(MDB_PATH)
            })
        else:
            return jsonify({'status': 'cancelled'})
            
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/setup', methods=['GET'])
def setup():
    licensed_name = ""
    p = os.path.join(EXE_DIR, 'license.key')
    if os.path.exists(p):
        try:
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f)
            import license_validator
            if license_validator.verify_license_signature(data):
                licensed_name = data.get('industry_name', '').strip()
        except:
            pass
    return render_template('setup.html', licensed_name=licensed_name)

@app.route('/api/setup', methods=['POST'])
def api_setup():
    global CFG
    try:
        name    = request.form.get('name', '').strip()
        address = request.form.get('address', '').strip()

        if not name:
            return jsonify({'status': 'error', 'message': 'Company name is required.'}), 400

        # Save logo if uploaded
        logo_rel = CFG.get('INDUSTRY_LOGO', 'static/logo.jpg')
        if 'logo' in request.files:
            f = request.files['logo']
            if f and f.filename:
                # Clean up any existing logo and custom icon files in EXE_DIR
                try:
                    for filename in os.listdir(EXE_DIR):
                        if filename.startswith('logo.') or filename == 'logo_custom.ico':
                            try:
                                os.remove(os.path.join(EXE_DIR, filename))
                            except Exception as e:
                                print(f"Error removing old logo file {filename}: {e}")
                except Exception as e:
                    print(f"Error listing directory for logo cleanup: {e}")

                ext  = os.path.splitext(f.filename)[1].lower() or '.jpg'
                dest = os.path.join(EXE_DIR, f'logo{ext}')
                f.save(dest)
                logo_rel = f'logo{ext}'

        save_full_config({
            'INDUSTRY_NAME':    name,
            'INDUSTRY_ADDRESS': address,
            'INDUSTRY_LOGO':    logo_rel,
        })

        # Reload config in memory
        CFG = load_config()
        
        # Update shortcut and convert logo to ICO
        update_shortcut_icon(logo_rel if logo_rel and '/' not in logo_rel else None)
        
        check_license()

        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ── MULTI-TENANT LOGO ENDPOINTS ───────────────────────────────────────────────
@app.route('/logo')
@app.route('/logo/<tenant_id>')
def get_tenant_logo(tenant_id=None):
    if not tenant_id:
        user = session.get('user', {})
        if isinstance(user, dict) and user.get('tenant_id'):
            tenant_id = user.get('tenant_id')
        elif session.get('tenant_id'):
            tenant_id = session.get('tenant_id')
        else:
            tenant_id = 'client_sgri'

    tenant_dir = tenants.get_tenant_dir(tenant_id)

    for ext in ['.png', '.jpg', '.jpeg', '.webp', '.gif']:
        p = os.path.join(tenant_dir, f'logo{ext}')
        if os.path.exists(p):
            return send_from_directory(tenant_dir, f'logo{ext}')

    static_dir = os.path.join(EXE_DIR, 'static')
    if os.path.exists(os.path.join(static_dir, 'logo.jpg')):
        return send_from_directory(static_dir, 'logo.jpg')
    return send_from_directory(static_dir, 'logo.png')

@app.route('/api/upload-logo', methods=['POST'])
def api_upload_logo():
    if 'user' not in session or not isinstance(session['user'], dict):
        return jsonify({'status': 'error', 'message': 'Not authenticated'}), 401

    tenant_id = session['user'].get('tenant_id', 'client_sgri')
    if 'logo' not in request.files:
        return jsonify({'status': 'error', 'message': 'No logo file provided'}), 400

    f = request.files['logo']
    if not f or not f.filename:
        return jsonify({'status': 'error', 'message': 'Empty file'}), 400

    tenant_dir = tenants.get_tenant_dir(tenant_id)
    ext = os.path.splitext(f.filename)[1].lower() or '.png'

    for old_ext in ['.png', '.jpg', '.jpeg', '.webp', '.gif']:
        old_p = os.path.join(tenant_dir, f'logo{old_ext}')
        if os.path.exists(old_p):
            try:
                os.remove(old_p)
            except Exception:
                pass

    dest_p = os.path.join(tenant_dir, f'logo{ext}')
    f.save(dest_p)
    return jsonify({'status': 'ok', 'message': 'Mill logo updated successfully!'})

@app.route('/manifest.json')
def serve_manifest():
    static_dir = os.path.join(EXE_DIR, 'static')
    return send_from_directory(static_dir, 'manifest.json', mimetype='application/json')



@app.route('/api/shutdown', methods=['POST'])
def api_shutdown():
    import threading, time
    def kill_server():
        time.sleep(0.5)
        os._exit(0)
    threading.Thread(target=kill_server).start()
    return jsonify({'status': 'ok'})

# ── LICENSE VALIDATION & DESKTOP SHORTCUT ─────────────────────────────────────
import license_validator

IS_LICENSED = False
LICENSE_ERROR = ""

def check_license():
    global IS_LICENSED, LICENSE_ERROR
    # Check for test mode bypass
    is_test_cmd = '--test' in sys.argv or '-t' in sys.argv
    is_test_env = os.environ.get('DASHBOARD_TEST_MODE') == '1'
    is_test_cfg = CFG.get('TEST_MODE', 'False').strip().lower() in ('true', 'yes', '1')
    
    if is_test_cmd or is_test_env or is_test_cfg:
        IS_LICENSED = True
        LICENSE_ERROR = ""
        print("  [TEST MODE] License verification bypassed.")
        return True

    is_licensed, err_msg = license_validator.check_license(EXE_DIR, CFG.get('INDUSTRY_NAME', ''))
    IS_LICENSED = is_licensed
    LICENSE_ERROR = err_msg
    return IS_LICENSED

# Run initial license check on startup
check_license()

def create_desktop_shortcut(ico_path=None):
    try:
        import subprocess
        # Get desktop path dynamically
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        # Handle Windows Registry shell folder redirections
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
            desktop, _ = winreg.QueryValueEx(key, "Desktop")
            desktop = os.path.expandvars(desktop)
        except:
            pass
            
        shortcut_path = os.path.join(desktop, "Rice Mill Dashboard.lnk")
        exe_path = sys.executable
        
        # In development mode (not frozen), skip shortcut creation
        if not getattr(sys, 'frozen', False):
            return
            
        if not ico_path or not os.path.exists(ico_path):
            # Fall back to using the executable itself (which has the default icon embedded)
            ico_path = exe_path
                
        ps_command = (
            f"$WshShell = New-Object -ComObject WScript.Shell; "
            f"$Shortcut = $WshShell.CreateShortcut('{shortcut_path}'); "
            f"$Shortcut.TargetPath = '{exe_path}'; "
            f"$Shortcut.WorkingDirectory = '{EXE_DIR}'; "
            f"$Shortcut.IconLocation = '{ico_path}'; "
            f"$Shortcut.Description = 'Rice Mill Dashboard'; "
            f"$Shortcut.Save();"
        )
        
        # Run PowerShell command silently
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_command],
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except Exception as e:
        print(f"Error creating shortcut: {e}")


def update_shortcut_icon(logo_filename=None):
    try:
        ico_path = os.path.join(EXE_DIR, 'logo_custom.ico')
        
        # If a custom logo exists and can be converted
        if logo_filename and not logo_filename.startswith('static/'):
            logo_path = logo_filename if os.path.isabs(logo_filename) else os.path.join(EXE_DIR, logo_filename)
            if os.path.exists(logo_path):
                from PIL import Image
                img = Image.open(logo_path)
                # Convert and save as ICO with standard sizes
                img.save(ico_path, format='ICO', sizes=[(256, 256), (128, 128), (64, 64), (32, 32)])
                create_desktop_shortcut(ico_path)
                return
                
        # If no custom logo exists, clean up any custom icons and point back to the exe
        if os.path.exists(ico_path):
            try: os.remove(ico_path)
            except: pass
        legacy_ico = os.path.join(EXE_DIR, 'logo.ico')
        if os.path.exists(legacy_ico):
            try: os.remove(legacy_ico)
            except: pass
            
        create_desktop_shortcut(None)
    except Exception as e:
        print(f"Error updating shortcut icon: {e}")

# Startup Task: Ensure Desktop shortcut exists on first run
try:
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
        desktop, _ = winreg.QueryValueEx(key, "Desktop")
        desktop = os.path.expandvars(desktop)
    except:
        pass
    shortcut_path = os.path.join(desktop, "Rice Mill Dashboard.lnk")
    if not os.path.exists(shortcut_path) and getattr(sys, 'frozen', False):
        update_shortcut_icon(CFG.get('INDUSTRY_LOGO', ''))
except:
    pass

@app.route('/logo')
def serve_logo():
    from flask import send_file, send_from_directory
    logo_filename = CFG.get('INDUSTRY_LOGO', '').strip()
    if logo_filename:
        # Resolve path relative to the external EXE directory
        ext_logo_path = logo_filename if os.path.isabs(logo_filename) else os.path.join(EXE_DIR, logo_filename)
        if os.path.exists(ext_logo_path):
            return send_file(ext_logo_path)
            
    # Fallback to embedded default logo inside the .exe
    return send_from_directory(os.path.join(BASE, 'static'), 'logo.jpg')

# ── LOGIN & USER MANAGEMENT ───────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login_page():
    if request.method == 'GET':
        if 'user' in session:
            return redirect(url_for('index'))
        return render_template('login.html')
        
    company_code = request.form.get('company_code', 'SGRI').strip()
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    
    user, err_msg = auth.authenticate_user(company_code, username, password)
    if user:
        session['user'] = user
        session['role'] = user.get('role', 'staff')
        session['tenant_id'] = user.get('tenant_id', 'client_sgri')
        session['company_code'] = user.get('company_code', 'SGRI')
        session['company_name'] = user.get('company_name', 'Rice Mill')
        next_url = request.args.get('next') or url_for('index')
        return redirect(next_url)
    
    return render_template('login.html', error=err_msg or "Invalid login credentials.", company_code=company_code)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))

@app.route('/api/forgot-password', methods=['POST'])
def api_forgot_password():
    data = request.get_json() or {}
    company_code = data.get('company_code', '').strip()
    license_key = data.get('license_key', '').strip()
    username = data.get('username', 'admin').strip()
    new_password = data.get('new_password', '').strip()

    if not company_code or not license_key or not new_password:
        return jsonify({'status': 'error', 'message': 'Company Code, License Key, and New Password are required.'}), 400

    success, msg = auth.reset_password_with_license_key(company_code, license_key, username, new_password)
    if success:
        return jsonify({'status': 'ok', 'message': msg})
    return jsonify({'status': 'error', 'message': msg}), 400

@app.route('/api/change-password', methods=['POST'])
def api_change_password():
    if 'user' not in session or not isinstance(session['user'], dict):
        return jsonify({'status': 'error', 'message': 'Not authenticated'}), 401
    
    data = request.get_json() or {}
    old_password = data.get('old_password', '').strip()
    new_password = data.get('new_password', '').strip()

    tenant_id = session['user'].get('tenant_id', 'client_sgri')
    username = session['user'].get('username')

    success, msg = auth.change_user_password(tenant_id, username, old_password, new_password)
    if success:
        return jsonify({'status': 'ok', 'message': msg})
    return jsonify({'status': 'error', 'message': msg}), 400

# ── DIRECT WEB UI File UPLOAD ENDPOINT (Zero Desktop Software Required) ────
@app.route('/api/upload-database', methods=['POST'])
def api_upload_database():
    if 'user' not in session or not isinstance(session['user'], dict):
        return jsonify({'status': 'error', 'message': 'Not authenticated'}), 401

    tenant_id = session['user'].get('tenant_id', 'client_sgri')
    if 'file' not in request.files:
        return jsonify({'status': 'error', 'message': 'No file uploaded'}), 400

    f = request.files['file']
    raw_bytes = f.read()
    if not raw_bytes:
        return jsonify({'status': 'error', 'message': 'Uploaded file is empty'}), 400

    tenant = tenants.get_tenant_by_id(tenant_id)
    enc_key = tenant.get('encryption_key', '') if tenant else ''

    # Attempt decrypt if encrypted via Web Crypto API
    try:
        decrypted_bytes = crypto_utils.decrypt_data(raw_bytes, enc_key)
    except Exception:
        decrypted_bytes = raw_bytes

    # Attempt decompress if GZIP compressed
    try:
        mdb_bytes = gzip.decompress(decrypted_bytes)
    except Exception:
        mdb_bytes = decrypted_bytes

    tenant_dir = tenants.get_tenant_dir(tenant_id)
    target_mdb = os.path.join(tenant_dir, 'Database.mdb')

    with open(target_mdb, 'wb') as out_f:
        out_f.write(mdb_bytes)

    # Invalidate cache for this tenant
    with _tenant_cache_lock:
        if tenant_id in _tenant_caches:
            _tenant_caches[tenant_id]["mtime"] = None
            _tenant_caches[tenant_id]["tables"].clear()

    return jsonify({
        'status': 'ok',
        'message': 'File updated successfully! Reports will now reflect the new data.',
        'filename': f.filename,
        'size_bytes': len(mdb_bytes)
    })

@app.route('/api/delete-database', methods=['POST'])
def api_delete_database():
    if 'user' not in session or not isinstance(session['user'], dict):
        return jsonify({'status': 'error', 'message': 'Not authenticated'}), 401
        
    tenant_id = session['user'].get('tenant_id', 'client_sgri')
    tenant_dir = tenants.get_tenant_dir(tenant_id)
    target_mdb = os.path.join(tenant_dir, 'Database.mdb')

    if os.path.exists(target_mdb):
        try:
            os.remove(target_mdb)
        except Exception as e:
            return jsonify({'status': 'error', 'message': f'Failed to delete File: {str(e)}'}), 500

    with _tenant_cache_lock:
        if tenant_id in _tenant_caches:
            _tenant_caches[tenant_id]["mtime"] = None
            _tenant_caches[tenant_id]["tables"].clear()

    return jsonify({
        'status': 'ok',
        'message': 'File deleted successfully! You can now upload a new .mdb file.'
    })


# ── SUPER-ADMIN SaaS MANAGEMENT PORTAL ───────────────────────────────────────
@app.route('/super-admin', methods=['GET', 'POST'])
def super_admin_page():
    if request.method == 'POST':
        entered_pass = request.form.get('password', '').strip()
        if entered_pass == SUPER_ADMIN_PASSWORD:
            session['is_super_admin'] = True
            session['user'] = {'username': 'superadmin', 'role': 'super_admin', 'name': 'Super Admin'}
            return redirect(url_for('super_admin_page'))
        return render_template('super_admin_login.html', error="Invalid Super-Admin Security Password.")

    if not session.get('is_super_admin'):
        return render_template('super_admin_login.html')

    all_tenants = tenants.load_tenants()
    tenant_list = list(all_tenants.values())
    return render_template('super_admin.html', tenants=tenant_list, super_admin_pass=SUPER_ADMIN_PASSWORD)

@app.route('/api/super-admin/update-company-name', methods=['POST'])
@auth.login_required(role='super_admin')
def api_super_admin_update_company_name():
    data = request.get_json() or {}
    license_key = data.get('license_key', '').strip()
    new_company_name = data.get('company_name', '').strip()

    success, msg = tenants.update_tenant_company_name(license_key, new_company_name)
    if success:
        return jsonify({'status': 'ok', 'message': msg})
    return jsonify({'status': 'error', 'message': msg}), 400


@app.route('/api/super-admin/add-client', methods=['POST'])
@auth.login_required(role='super_admin')
def api_super_admin_add_client():
    data = request.get_json() or {}
    company_name = data.get('company_name', '').strip()
    company_code = data.get('company_code', '').strip().upper()
    admin_password = data.get('admin_password', '').strip()
    months = int(data.get('months', 12))
    show_stocks = data.get('show_stocks', False)
    show_bi_reports = data.get('show_bi_reports', False)

    if not company_name or not company_code or not admin_password:
        return jsonify({'status': 'error', 'message': 'Company Name, Code, and Admin Password are required'}), 400

    success, msg, tenant_info = tenants.create_tenant(company_name, company_code, admin_password, months, show_stocks, show_bi_reports)
    if success:
        return jsonify({'status': 'ok', 'message': msg, 'tenant': tenant_info})
    return jsonify({'status': 'error', 'message': msg}), 400

@app.route('/api/super-admin/reset-password', methods=['POST'])
@auth.login_required(role='super_admin')
def api_super_admin_reset_password():
    data = request.get_json() or {}
    company_code = data.get('company_code', '').strip()
    username = data.get('username', 'admin').strip()
    new_password = data.get('new_password', '').strip()

    tenant = tenants.get_tenant_by_code(company_code)
    if not tenant:
        return jsonify({'status': 'error', 'message': f"Company Code '{company_code}' not found"}), 400

    tenant_id = tenant.get('tenant_id')
    users = auth.load_tenant_users(tenant_id)
    username_clean = username.lower()
    
    if username_clean not in users:
        users[username_clean] = {'username': username_clean, 'password_hash': auth.hash_password(new_password), 'role': 'admin', 'name': username_clean.capitalize()}
    else:
        users[username_clean]['password_hash'] = auth.hash_password(new_password)

    auth.save_tenant_users(tenant_id, users)
    return jsonify({'status': 'ok', 'message': f"Password for {username} @ {company_code} reset successfully!"})

@app.route('/api/super-admin/update-subscription', methods=['POST'])
@auth.login_required(role='super_admin')
def api_super_admin_update_subscription():
    data = request.get_json() or {}
    license_key = data.get('license_key', '').strip()
    status = data.get('status')
    expiry_date = data.get('expiry_date')
    show_stocks = data.get('show_stocks')
    show_bi_reports = data.get('show_bi_reports')

    success, msg = tenants.update_tenant_status(license_key, status, expiry_date, show_stocks, show_bi_reports)
    if success:
        return jsonify({'status': 'ok', 'message': msg})
    return jsonify({'status': 'error', 'message': msg}), 400


@app.route('/api/super-admin/download-uploader/<license_key>')
@auth.login_required(role='super_admin')
def api_super_admin_download_uploader(license_key):
    import io, zipfile
    from flask import Response
    tenant = tenants.get_tenant_by_key(license_key)
    if not tenant:
        return jsonify({'status': 'error', 'message': 'Client mill not found'}), 404

    company_code = tenant.get('company_code', 'MILL')
    company_name = tenant.get('company_name', 'Rice Mill')

    config_content = f"""# Rice Mill Dashboard — 2-Click Desktop Sync Configuration
CLOUD_URL=https://ricemilldashboard.up.railway.app
LICENSE_KEY={license_key}
COMPANY_CODE={company_code}
"""


    search_dirs = [os.path.dirname(EXE_DIR), EXE_DIR, os.getcwd(), os.path.dirname(os.path.abspath(__file__))]

    def read_file_content(filename):
        for b in search_dirs:
            p = os.path.join(b, filename)
            if os.path.exists(p):
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        return f.read()
                except Exception:
                    with open(p, 'rb') as f:
                        return f.read()
        return None

    shortcut_bat_content = """@echo off
set "SCRIPT_DIR=%~dp0"
set "TARGET=%SCRIPT_DIR%sync_now.bat"

powershell -ExecutionPolicy Bypass -NoProfile -Command "$desktop=[Environment]::GetFolderPath('Desktop'); $lnk=Join-Path $desktop 'Sync Database to Cloud.lnk'; $s=(New-Object -COM WScript.Shell).CreateShortcut($lnk); $s.TargetPath='%TARGET%'; $s.WorkingDirectory='%SCRIPT_DIR%'; $s.Save()"

echo.
echo ====================================================
echo  [SUCCESS] Desktop Shortcut Created!
echo ====================================================
echo.
echo  You can now double-click "Sync Database to Cloud"
echo  directly from your Windows Desktop.
echo.
pause
"""


    bat_code = read_file_content('sync_now.bat')
    ps1_code = read_file_content('sync_uploader.ps1')

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('sync_config.txt', config_content)
        zf.writestr('create_shortcut.bat', shortcut_bat_content)
        if ps1_code:
            zf.writestr('sync_uploader.ps1', ps1_code)
        if bat_code:
            zf.writestr('sync_now.bat', bat_code)




    zip_buffer.seek(0)
    safe_filename = f"{company_code}_2Click_Uploader.zip"

    return Response(
        zip_buffer.getvalue(),
        mimetype='application/zip',
        headers={'Content-Disposition': f'attachment; filename={safe_filename}'}
    )




# ── CLOUD SYNC ENDPOINT (AES-256 Encrypted + GZIP Compressed) ──────────────────
@app.route('/api/sync-database', methods=['POST'])
def api_sync_database():
    global MDB_PATH

    
    tenant_key = request.headers.get('X-License-Key', '').strip()
    company_code = request.headers.get('X-Company-Code', '').strip()
    sync_token = request.headers.get('X-Sync-Token', '').strip()

    tenant = (tenants.get_tenant_by_key(tenant_key) if tenant_key else None) or \
             (tenants.get_tenant_by_code(company_code) if company_code else None)

    if not tenant and 'user' in session and isinstance(session['user'], dict):
        tenant = tenants.get_tenant_by_id(session['user'].get('tenant_id'))

    expected_token = os.environ.get('SYNC_SECRET_TOKEN', 'RiceMillSyncSecretToken2026!').strip()
    if not tenant and (not sync_token or sync_token != expected_token):
        return jsonify({'status': 'error', 'message': 'Invalid license key or unauthorized sync request'}), 401

        
    try:
        import base64
        chunk_idx = 0
        total_chunks = 1
        upload_id = "default"
        chunk_bytes = b''

        if request.is_json:
            json_data = request.get_json(silent=True) or {}
            b64_str = json_data.get('data', '')
            chunk_bytes = base64.b64decode(b64_str) if b64_str else b''
            chunk_idx = int(json_data.get('chunk_idx', 0))
            total_chunks = int(json_data.get('total_chunks', 1))
            upload_id = json_data.get('upload_id', 'default')
            if not sync_token:
                sync_token = json_data.get('token', '').strip()
        elif 'file' in request.files:
            chunk_bytes = request.files['file'].read()
            chunk_idx = int(request.headers.get('X-Chunk-Index', 0))
            total_chunks = int(request.headers.get('X-Total-Chunks', 1))
            upload_id = request.headers.get('X-Upload-ID', 'default')
        else:
            chunk_bytes = request.data
            chunk_idx = int(request.headers.get('X-Chunk-Index', 0))
            total_chunks = int(request.headers.get('X-Total-Chunks', 1))
            upload_id = request.headers.get('X-Upload-ID', 'default')

        if not chunk_bytes and total_chunks > 0:
            return jsonify({'status': 'error', 'message': 'Empty payload'}), 400

        temp_dir = os.environ.get('DATA_DIR', '') or (os.path.dirname(MDB_PATH) if MDB_PATH else os.path.join(EXE_DIR, 'data'))
        try:
            os.makedirs(temp_dir, exist_ok=True)
        except Exception:
            temp_dir = '/tmp' if os.name != 'nt' else os.path.join(EXE_DIR, 'data')
            os.makedirs(temp_dir, exist_ok=True)

        temp_file = os.path.join(temp_dir, f"temp_{upload_id}.part")


        # Write or append chunk to temp file
        mode = 'wb' if chunk_idx == 0 else 'ab'
        with open(temp_file, mode) as f:
            f.write(chunk_bytes)

        # If more chunks are expected, return success for chunk
        if chunk_idx < total_chunks - 1:
            return jsonify({'status': 'chunk_received', 'chunk_idx': chunk_idx, 'total_chunks': total_chunks})

        # Final chunk received: assemble complete payload
        with open(temp_file, 'rb') as f:
            payload = f.read()

        try: os.remove(temp_file)
        except: pass

        enc_key = os.environ.get('ENCRYPTION_KEY', 'RiceMillDashboardDefaultEncryptionKey2026!')
        
        try:
            decrypted_bytes = crypto_utils.decrypt_data(payload, enc_key)
        except Exception:
            decrypted_bytes = payload

        try:
            mdb_bytes = gzip.decompress(decrypted_bytes)
        except Exception:
            mdb_bytes = decrypted_bytes

        # Resolve target tenant directory from license key, company code, or session
        tenant_key = request.headers.get('X-License-Key', '').strip()
        company_code = request.headers.get('X-Company-Code', '').strip()

        tenant = (tenants.get_tenant_by_key(tenant_key) if tenant_key else None) or \
                 (tenants.get_tenant_by_code(company_code) if company_code else None)

        if not tenant and 'user' in session and isinstance(session['user'], dict):
            tenant = tenants.get_tenant_by_id(session['user'].get('tenant_id'))

        tenant_id = tenant.get('tenant_id', 'client_sgri') if tenant else 'client_sgri'
        company_name = tenant.get('company_name', 'Rice Mill') if tenant else 'Rice Mill'
        
        tenant_dir = tenants.get_tenant_dir(tenant_id)
        target_mdb = os.path.join(tenant_dir, 'Database.mdb')

        with open(target_mdb, 'wb') as f:
            f.write(mdb_bytes)

        if tenant_id == 'client_sgri':
            MDB_PATH = target_mdb

        with _tenant_cache_lock:
            if tenant_id in _tenant_caches:
                _tenant_caches[tenant_id]["mtime"] = None
                _tenant_caches[tenant_id]["tables"].clear()

        return jsonify({
            'status': 'ok',
            'message': f'Database synced successfully for {company_name}',
            'company_name': company_name,
            'filename': os.path.basename(target_mdb),
            'size_bytes': len(mdb_bytes)
        })




    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Sync failed: {str(e)}'}), 500


@app.before_request
def restrict_unlicensed():
    # Always allow static files, setup, license, login, SaaS endpoints, and sync endpoints
    allowed_paths = ('/static/', '/manifest.json', '/api/license/activate', '/license', '/setup', '/api/setup', '/logo', '/login', '/logout', '/api/sync-database', '/super-admin', '/api/super-admin', '/api/forgot-password', '/api/upload-database', '/api/delete-database')


    if any(request.path.startswith(p) for p in allowed_paths) or request.path in allowed_paths:
        return

    
    # Check if first run (redirect to setup, which is allowed)
    if is_first_run():
        return
        
    # Check license status
    if not IS_LICENSED:
        if check_license():
            return
        return redirect(url_for('license_page'))

    # Check user login authentication
    auth_enabled = os.environ.get('ENABLE_AUTH', 'True').strip().lower() in ('true', '1', 'yes')
    if auth_enabled:
        user = session.get('user')
        if not user:

            if request.path.startswith('/api/'):
                return jsonify({'error': 'unauthorized', 'message': 'Authentication required'}), 401
            return redirect(url_for('login_page', next=request.url))


@app.route('/license')
def license_page():
    cfg_name = CFG.get('INDUSTRY_NAME', 'Rice Mill')
    return render_template('license.html', industry_name=cfg_name, error=LICENSE_ERROR)

@app.route('/api/license/activate', methods=['POST'])
def activate_license():
    try:
        req_data = request.get_json()
        key_str = req_data.get('key', '').strip()
        if not key_str:
            return jsonify({'success': False, 'message': 'Key cannot be empty'}), 400
        
        # Attempt to parse key as JSON
        try:
            key_json = json.loads(key_str)
        except json.JSONDecodeError:
            return jsonify({'success': False, 'message': 'Invalid key format. Must be a valid JSON license key.'}), 400
        
        # Write to license.key in EXE_DIR
        p = os.path.join(EXE_DIR, 'license.key')
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(key_json, f, indent=2)
            
        # Re-check license
        if check_license():
            return jsonify({'success': True, 'message': 'License activated successfully'})
        else:
            # If invalid, remove the invalid file so we don't load it next time
            if os.path.exists(p):
                os.remove(p)
            return jsonify({'success': False, 'message': LICENSE_ERROR}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f'Activation error: {str(e)}'}), 500

@app.route('/')
def index():
    if is_first_run():
        return redirect(url_for('setup'))

    user = session.get('user', {})
    tenant_id = user.get('tenant_id', 'client_sgri') if isinstance(user, dict) else session.get('tenant_id', 'client_sgri')
    tenant = tenants.get_tenant_by_id(tenant_id) or tenants.get_tenant_by_code(session.get('company_code', 'SGRI'))

    name = (tenant.get('company_name') if tenant and tenant.get('company_name') else None) or session.get('company_name') or CFG.get('INDUSTRY_NAME', 'Rice Mill')
    show_stocks = tenant.get('show_stocks', False) if tenant else SHOW_STOCKS
    show_bi_reports = tenant.get('show_bi_reports', False) if tenant else SHOW_BI_REPORTS

    import socket
    try:
        hostname = socket.gethostname()
        network_url = f"http://{hostname}:5000"
    except:
        network_url = None

    return render_template(
        'index.html',
        industry_name=name,
        industry_address=CFG.get('INDUSTRY_ADDRESS', ''),
        currency_symbol=CFG.get('CURRENCY_SYMBOL', 'Rs.'),
        app_title=name,
        industry_logo='logo',
        network_url=network_url,
        show_bi_reports=show_bi_reports,
        show_stocks=show_stocks,
        user=user
    )


def download_url(url, timeout=10):
    import urllib.request
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception:
        import ssl
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.read()

@app.route('/api/update/check')
def update_check():
    enable_updates = CFG.get('ENABLE_UPDATES', 'False').strip().lower() in ('true', 'yes', '1')
    if not enable_updates:
        return jsonify({
            'update_available': False,
            'message': 'Updates are disabled in config'
        })
    import re
    try:
        # Check remote app.py version
        url_app = "https://raw.githubusercontent.com/shivagolla1/Rice-Mill-Dashboard/main/App/app.py"
        remote_app_version = VERSION
        chunk = download_url(url_app, timeout=5).decode('utf-8')
        match = re.search(r'VERSION\s*=\s*["\']([^"\']+)["\']', chunk)
        if match:
            remote_app_version = match.group(1)
                
        # Check remote index.html version
        url_html = "https://raw.githubusercontent.com/shivagolla1/Rice-Mill-Dashboard/main/App/templates/index.html"
        remote_html_version = VERSION
        chunk = download_url(url_html, timeout=5).decode('utf-8')
        match = re.search(r'DASHBOARD_VERSION\s*=\s*["\']([^"\']+)["\']', chunk)
        if match:
            remote_html_version = match.group(1)
        
        backend_changed = (remote_app_version != VERSION)
        frontend_changed = (remote_html_version != VERSION)
        
        return jsonify({
            'update_available': backend_changed or frontend_changed,
            'backend_changed': backend_changed,
            'frontend_changed': frontend_changed,
            'latest_version': remote_app_version if backend_changed else remote_html_version
        })
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/update/apply', methods=['POST'])
def update_apply():
    enable_updates = CFG.get('ENABLE_UPDATES', 'False').strip().lower() in ('true', 'yes', '1')
    if not enable_updates:
        return jsonify({
            'status': 'error',
            'message': 'Updates are disabled in config'
        })
    try:
        html_url = "https://raw.githubusercontent.com/shivagolla1/Rice-Mill-Dashboard/main/App/templates/index.html"
        app_url = "https://raw.githubusercontent.com/shivagolla1/Rice-Mill-Dashboard/main/App/app.py"
        
        # Download files
        html_data = download_url(html_url, timeout=10)
        app_data = download_url(app_url, timeout=10)
        
        # Overwrite local files
        with open(os.path.join(BASE, 'templates', 'index.html'), 'wb') as f:
            f.write(html_data)
        with open(os.path.join(BASE, 'app.py'), 'wb') as f:
            f.write(app_data)
            
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/api/update/restart', methods=['POST'])
def update_restart():
    import subprocess, sys, time, threading
    def self_restart():
        time.sleep(0.5)
        # Windows ping command to sleep 1 second, then run python app.py
        cmd = f'ping 127.0.0.1 -n 2 > nul && "{sys.executable}" "{sys.argv[0]}"'
        subprocess.Popen(cmd, shell=True)
        os._exit(0)
    threading.Thread(target=self_restart).start()
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    # 1. Free port 5000 if occupied to prevent silent startup crash
    try:
        output = subprocess.check_output('netstat -aon', shell=True).decode('utf-8', errors='ignore')
        for line in output.splitlines():
            if ':5000' in line and 'LISTENING' in line:
                parts = line.strip().split()
                if len(parts) >= 5:
                    pid = parts[-1]
                    if int(pid) != os.getpid():
                        print(f"Port 5000 occupied by PID {pid}. Terminating it...")
                        subprocess.run(f'taskkill /F /PID {pid}', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"Error freeing port 5000: {e}")

    # 2. Auto-open default web browser on startup
    def auto_open_browser():
        time.sleep(1.5)
        try:
            os.startfile("http://localhost:5000")
        except:
            try:
                import webbrowser
                webbrowser.open("http://localhost:5000")
            except:
                pass
    threading.Thread(target=auto_open_browser, daemon=True).start()

    import socket
    try:
        hostname = socket.gethostname()
        net_url = f"http://{hostname}:5000"
    except:
        net_url = None
    print(f'\n  *  Rice Mill Dashboard  ->  http://localhost:5000')
    if net_url:
        print(f'  *  On your network     ->  {net_url}\n')
    if os.path.exists(MDB_PATH):
        print(f'  [OK]  File: {os.path.basename(MDB_PATH)}')
    else:
        print(f'  [INFO]  No File selected yet — use the DB selector in the dashboard.')

    # ── IDLE WATCHDOG: auto-shutdown after 120 min of no browser activity ──────
    _last_active = [time.time()]

    @app.before_request
    def _touch():
        _last_active[0] = time.time()

    def _watchdog():
        IDLE_MINUTES = 120
        while True:
            time.sleep(60)
            idle = (time.time() - _last_active[0]) / 60
            if idle >= IDLE_MINUTES:
                print(f'\n  [AUTO-STOP]  No activity for {IDLE_MINUTES} min. Shutting down.')
                os._exit(0)

    t = threading.Thread(target=_watchdog, daemon=True)
    t.start()
    # ──────────────────────────────────────────────────────────────────────────

    app.run(debug=False, port=5000, host='0.0.0.0')
