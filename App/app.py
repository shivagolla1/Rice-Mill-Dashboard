"""
Rice Mill Dashboard
- Orders:  reads from .mdb (IO + IO Details + Confirmation + Journal)
- Stocks:  reads from .mdb (Godowns)
- Data/Explore: full table browser + IO explorer
"""
from flask import Flask, jsonify, render_template, request, redirect, url_for
import os, csv, re, io, json, subprocess, time, threading, shutil
from datetime import datetime, date as dobj

app  = Flask(__name__, template_folder='templates', static_folder='static')
BASE = os.path.dirname(os.path.abspath(__file__))
VERSION = "1.0.1"

# ── CONFIG ────────────────────────────────────────────────────────────────────
def load_config():
    d = {
        'MDB_FILE': '',
        'INDUSTRY_NAME': 'Rice Mill',
        'INDUSTRY_ADDRESS': '',
        'CURRENCY_SYMBOL': 'Rs.',
        'APP_TITLE': '',
        'INDUSTRY_LOGO': 'static/logo.jpg'
    }
    p = os.path.join(BASE,'config.txt')
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
    p = os.path.join(BASE, 'config.txt')
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
    p = os.path.join(BASE, 'config.txt')
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
    2. Otherwise, auto-detect any .mdb in the data/ folder.
    3. Fallback: any .mdb in the app root folder.
    """
    configured = CFG.get('MDB_FILE', '').strip()
    if configured:
        full = configured if os.path.isabs(configured) else os.path.join(BASE, configured)
        if os.path.exists(full):
            return full

    # Auto-detect: look in data/ first, then root
    for search_dir in [os.path.join(BASE, 'data'), BASE]:
        if not os.path.isdir(search_dir):
            continue
        files = [f for f in os.listdir(search_dir) if f.lower().endswith('.mdb')]
        if files:
            # Prefer most recently modified
            files.sort(key=lambda f: os.path.getmtime(os.path.join(search_dir, f)), reverse=True)
            return os.path.join(search_dir, files[0])

    # Nothing found — return the configured path anyway so error messages are clear
    return configured if configured and os.path.isabs(configured) else os.path.join(BASE, configured) if configured else os.path.join(BASE, 'data', 'Database.mdb')

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

_db_cache        = {}          # table_name → (cols, types, rows)
_db_cache_mtime  = None        # mtime of .mdb when cache was last built
_db_cache_lock   = threading.Lock()
_db_cache_ready  = threading.Event()  # set once warmup is complete

def mdb_open(path):
    from access_parser import AccessParser
    return AccessParser(path)

def mdb_tables(db):
    return [t for t in db.catalog if not t.startswith('MSys')]

def mdb_read(db, tname):
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

def _cache_valid():
    """Return True if in-memory cache matches the current file on disk."""
    if not os.path.exists(MDB_PATH): return False
    try:
        return _db_cache_mtime == os.path.getmtime(MDB_PATH)
    except: return False

def get_cached_table(tname):
    """Return (cols, types, rows) from cache; re-parse file only when mtime changes."""
    global _db_cache, _db_cache_mtime
    with _db_cache_lock:
        if _cache_valid() and tname in _db_cache:
            return _db_cache[tname]
    # Cache miss or stale → rebuild from disk
    if not os.path.exists(MDB_PATH):
        return [], [], []
    try:
        db    = mdb_open(MDB_PATH)
        tbls  = mdb_tables(db)
        mtime = os.path.getmtime(MDB_PATH)
        with _db_cache_lock:
            # Only reset cache if file actually changed (avoid thundering herd)
            if _db_cache_mtime != mtime:
                _db_cache.clear()
                _db_cache_mtime = mtime
            if tname not in _db_cache:
                if tname in tbls:
                    _db_cache[tname] = mdb_read(db, tname)
                else:
                    _db_cache[tname] = ([], [], [])
        return _db_cache.get(tname, ([], [], []))
    except:
        return [], [], []

def get_cached_db():
    """Return a dict-like helper that serves tables from cache."""
    class CachedDB:
        def __init__(self):
            self._tables = None
        def tables(self):
            if self._tables is None:
                if not os.path.exists(MDB_PATH): return []
                try:
                    db = mdb_open(MDB_PATH)
                    self._tables = mdb_tables(db)
                except: self._tables = []
            return self._tables
    return CachedDB()

def read_table(tname):
    """Open mdb and read one table. Returns (cols, types, rows) or ([], [], [])."""
    return get_cached_table(tname)

def _warmup():
    """Pre-parse the most-used tables in the background so first page load is fast."""
    key_tables = ['IO', 'IO Details', 'Confirmation', 'Journal', 'IO DC']
    print('  [Warmup]  Warming up database cache...', flush=True)
    for t in key_tables:
        try:
            get_cached_table(t)
            print(f'  [OK]  Cached: {t}', flush=True)
        except Exception as e:
            print(f'  [Error]  Could not cache {t}: {e}', flush=True)
    _db_cache_ready.set()
    print('  [OK]  Database cache ready — dashboard will be fast!', flush=True)

# Start warmup immediately when app loads
if os.path.exists(MDB_PATH):
    _warmup_thread = threading.Thread(target=_warmup, daemon=True)
    _warmup_thread.start()

# ── ORDERS (IO + IO Details + Confirmation + Journal summary) ─────────────────
def get_transactions(mode_filter):
    if not os.path.exists(MDB_PATH):
        return {'error':'file_not_found', 'path': MDB_PATH}
    try:
        # Use cached tables — parsed once on startup, instant on subsequent calls
        io_cols,  _, io_rows   = get_cached_table('IO')
        det_cols, _, det_rows  = get_cached_table('IO Details')
        con_cols, _, con_rows  = get_cached_table('Confirmation')

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
    if not os.path.exists(MDB_PATH):
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


@app.route('/api/journal/<io_id>')
def api_journal(io_id):
    """All Journal entries for one IO ID with days-to-pay calculation."""
    if not os.path.exists(MDB_PATH):
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
    if not os.path.exists(MDB_PATH):
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
            g   = groups[variety][key]
            g['bags']    += bags
            g['qtls']    += qtls
            g['min_date'] = io['date'] if (not g['min_date'] or io['date'] < g['min_date']) else g['min_date']

            # Sales → Jama; everything else (Purchases, Sales Returns, Direct) → Kharchu
            if mode == 'Sales':
                g['jama']    += amt
            else:
                g['kharchu'] += amt

        # Serialize into ordered list
        result = []
        for variety in sorted(groups.keys()):
            subrows = []
            for (typ, mode) in sorted(groups[variety].keys()):
                g = groups[variety][(typ, mode)]
                # Build label cleanly — skip empty parts so no trailing spaces
                parts = [p for p in [variety, typ, mode] if p]
                label = '  '.join(parts)
                subrows.append({
                    'account':  label,
                    'type':     typ,
                    'mode':     mode,
                    'bags':     round(g['bags'],  2),
                    'qtls':     round(g['qtls'],  2),
                    'jama':     round(g['jama'],  2),
                    'kharchu':  round(g['kharchu'], 2),
                    'min_date': parse_date(g['min_date']),
                })
            result.append({'variety': variety, 'rows': subrows})

        return jsonify(result)

    except ImportError:
        return jsonify({'error': 'not_installed'})
    except Exception as e:
        return jsonify({'error': str(e)})


# ── DATA BROWSER ──────────────────────────────────────────────────────────────
@app.route('/api/db_info')
def api_db_info():
    if not os.path.exists(MDB_PATH):
        return jsonify({'status':'file_not_found','path':MDB_PATH,'tables':[]})
    try:
        db     = mdb_open(MDB_PATH)
        tables = mdb_tables(db)
        result = []
        for t in tables:
            try:
                cols, types, rows = mdb_read(db, t)
                result.append({'name':t,'columns':[{'name':c,'type':tp}
                    for c,tp in zip(cols,types)],'row_count':len(rows)})
            except Exception as e:
                result.append({'name':t,'columns':[],'row_count':0,'error':str(e)})
        return jsonify({'status':'ok','tables':result,'file':CFG['MDB_FILE']})
    except ImportError:
        return jsonify({'status':'not_installed','tables':[]})
    except Exception as e:
        return jsonify({'status':'error','message':str(e),'tables':[]})


@app.route('/api/query', methods=['POST'])
def api_query():
    body  = request.get_json(silent=True) or {}
    tname = body.get('table','')
    limit = min(int(body.get('limit',100)),1000)
    where = body.get('where','').strip().lower()
    if not tname: return jsonify({'error':'No table specified'})
    if not os.path.exists(MDB_PATH): return jsonify({'error':'file_not_found'})
    try:
        db     = mdb_open(MDB_PATH)
        tables = mdb_tables(db)
        if tname not in tables: return jsonify({'error':f'Table "{tname}" not found'})
        cols, types, rows = mdb_read(db, tname)
        if where:
            rows = [r for r in rows if any(where in ss(v).lower() for v in r)]
        total = len(rows); rows = rows[:limit]
        return jsonify({'table':tname,'columns':cols,'col_types':types,
                        'rows':[[ss(v) for v in r] for r in rows],
                        'total':total,'shown':len(rows)})
    except ImportError:
        return jsonify({'error':'not_installed'})
    except Exception as e:
        return jsonify({'error':str(e)})


@app.route('/api/io_explore')
def api_io_explore():
    search = request.args.get('search','').strip().lower()
    io_id  = request.args.get('io_id','').strip()
    if not os.path.exists(MDB_PATH): return jsonify({'error':'file_not_found'})
    try:
        db     = mdb_open(MDB_PATH)
        tables = mdb_tables(db)

        def rd(t):
            if t not in tables: return [],[], []
            return mdb_read(db, t)

        def lkp(cols, rows, key_hints, val_hints):
            ki = col_i(cols, key_hints) or 0
            vi = col_i(cols, val_hints) or (1 if len(cols)>1 else 0)
            return {ss(r[ki]):ss(r[vi]) for r in rows}

        ac_cols,_,ac_rows = rd('Accounts')
        br_cols,_,br_rows = rd('Brokers')
        tp_cols,_,tp_rows = rd('Type')
        party_lkp  = lkp(ac_cols, ac_rows, ['id','acno','accode'], ['name','account','acname'])
        broker_lkp = lkp(br_cols, br_rows, ['id','brno','brcode'], ['name','broker'])
        type_lkp   = lkp(tp_cols, tp_rows, ['id','typeno'],        ['name','type','description'])

        io_cols,io_types,io_rows = rd('IO')
        id_i  = col_i(io_cols,['io id','ioid','id']) or 0
        pi    = col_i(io_cols,['party','acno','account'])
        bi    = col_i(io_cols,['broker','brno'])
        ti    = col_i(io_cols,['type'])

        enrich_cols  = list(io_cols)+(['Party Name'] if pi is not None else [])+\
                                     (['Broker Name'] if bi is not None else [])+\
                                     (['Type Name']   if ti is not None else [])
        enrich_rows = []
        for r in io_rows:
            row = list(r)
            if pi is not None: row.append(party_lkp.get(ss(r[pi]),ss(r[pi])))
            if bi is not None: row.append(broker_lkp.get(ss(r[bi]),ss(r[bi])))
            if ti is not None: row.append(type_lkp.get(ss(r[ti]),ss(r[ti])))
            enrich_rows.append(row)

        if search:
            enrich_rows = [r for r in enrich_rows if any(search in ss(v).lower() for v in r)]

        io_data = {'columns':enrich_cols,'col_types':io_types+['str','str','str'],
                   'rows':[[ss(v) for v in r] for r in enrich_rows[:300]],
                   'total':len(enrich_rows),'id_col_idx':id_i}

        related = {}
        if io_id:
            for tname in ['IO Details','IO Other Details','IO DC',
                          'IO Receipts','IODetailsTaxValues','IO NOW','Accounts','Brokers']:
                cols,types,rows = rd(tname)
                if not cols: continue
                li = col_i(cols,['ioid','io id','io_id','iono','io no']) or 0
                is_master = tname in ('Accounts','Brokers')
                matched = rows if is_master else [r for r in rows if ss(r[li])==io_id]
                related[tname] = {
                    'columns':cols,'col_types':types,
                    'rows':[[ss(v) for v in r] for r in matched[:50]],
                    'link_col':cols[li],'total_matched':len(matched)
                }

        return jsonify({'status':'ok','io':io_data,'related':related,
                        'io_id':io_id,'all_tables':tables,
                        'lookups':{'party_count':len(party_lkp),
                                   'broker_count':len(broker_lkp)}})
    except ImportError:
        return jsonify({'error':'not_installed'})
    except Exception as e:
        return jsonify({'error':str(e)})



@app.route('/api/database-status')
def api_database_status():
    global MDB_PATH
    exists = os.path.exists(MDB_PATH) if MDB_PATH else False
    return jsonify({
        'path': MDB_PATH or '',
        'filename': os.path.basename(MDB_PATH) if (MDB_PATH and exists) else '',
        'exists': exists
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
        
    ofn.lpstrFilter = "Access Database (*.mdb)\0*.mdb\0All Files (*.*)\0*.*\0"
    
    buffer_size = 1024
    file_buffer = ctypes.create_unicode_buffer(buffer_size)
    ofn.lpstrFile = ctypes.cast(file_buffer, wintypes.LPWSTR)
    ofn.nMaxFile = buffer_size
    
    ofn.lpstrTitle = "Select Access Database File"
    ofn.Flags = 0x00000800 | 0x00001000 | 0x00000008
    
    if ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(ofn)):
        return file_buffer.value
    return ""

@app.route('/api/select-database', methods=['POST'])
def api_select_database():
    global MDB_PATH, _db_cache_mtime
    
    selected_path = ""
    
    # Check if manual path was submitted via JSON
    body = request.get_json(silent=True) or {}
    manual_path = body.get('path', '').strip()
    
    if manual_path:
        # Check if relative or absolute
        if not os.path.isabs(manual_path):
            full_path = os.path.join(BASE, manual_path)
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
                "$dialog.Filter = 'Access Database (*.mdb)|*.mdb'; "
                "$dialog.Title = 'Select Access Database File'; "
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
                "path = fd.askopenfilename(title='Select Access Database File', filetypes=[('Access Database', '*.mdb')]); "
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
            
            with _db_cache_lock:
                _db_cache.clear()
                _db_cache_mtime = None
                _db_cache_ready.clear()
                
            # Start warmup thread
            threading.Thread(target=_warmup, daemon=True).start()
            
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
    return render_template('setup.html')

@app.route('/api/setup', methods=['POST'])
def api_setup():
    global CFG
    try:
        name    = request.form.get('name', '').strip()
        address = request.form.get('address', '').strip()
        symbol  = request.form.get('currency', 'Rs.').strip()

        if not name:
            return jsonify({'status': 'error', 'message': 'Company name is required.'}), 400

        # Save logo if uploaded
        logo_rel = CFG.get('INDUSTRY_LOGO', 'static/logo.jpg')
        if 'logo' in request.files:
            f = request.files['logo']
            if f and f.filename:
                ext  = os.path.splitext(f.filename)[1].lower() or '.jpg'
                dest = os.path.join(BASE, 'static', f'logo{ext}')
                f.save(dest)
                logo_rel = f'static/logo{ext}'

        save_full_config({
            'INDUSTRY_NAME':    name,
            'INDUSTRY_ADDRESS': address,
            'CURRENCY_SYMBOL':  symbol,
            'INDUSTRY_LOGO':    logo_rel,
        })

        # Reload config in memory
        CFG = load_config()

        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/shutdown', methods=['POST'])
def api_shutdown():
    import threading, time
    def kill_server():
        time.sleep(0.5)
        os._exit(0)
    threading.Thread(target=kill_server).start()
    return jsonify({'status': 'ok'})

@app.route('/')
def index():
    if is_first_run():
        return redirect(url_for('setup'))
    name = CFG.get('INDUSTRY_NAME', 'Rice Mill')
    
    # Get computer name for stable network access URL
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
        app_title=CFG.get('APP_TITLE', '').strip() or name,
        industry_logo=CFG.get('INDUSTRY_LOGO', 'static/logo.jpg'),
        network_url=network_url
    )

@app.route('/api/update/check')
def update_check():
    import urllib.request, re
    try:
        # Check remote app.py version
        url_app = "https://raw.githubusercontent.com/shivagolla1/Rice-Mill-Dashboard/main/App/app.py"
        req_app = urllib.request.Request(url_app, headers={'User-Agent': 'Mozilla/5.0'})
        remote_app_version = VERSION
        with urllib.request.urlopen(req_app, timeout=5) as r:
            chunk = r.read(2000).decode('utf-8')
            match = re.search(r'VERSION\s*=\s*["\']([^"\']+)["\']', chunk)
            if match:
                remote_app_version = match.group(1)
                
        # Check remote index.html version
        url_html = "https://raw.githubusercontent.com/shivagolla1/Rice-Mill-Dashboard/main/App/templates/index.html"
        req_html = urllib.request.Request(url_html, headers={'User-Agent': 'Mozilla/5.0'})
        remote_html_version = VERSION
        with urllib.request.urlopen(req_html, timeout=5) as r:
            chunk = r.read(2000).decode('utf-8')
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
    import urllib.request
    try:
        html_url = "https://raw.githubusercontent.com/shivagolla1/Rice-Mill-Dashboard/main/App/templates/index.html"
        app_url = "https://raw.githubusercontent.com/shivagolla1/Rice-Mill-Dashboard/main/App/app.py"
        
        # Download files
        req_h = urllib.request.Request(html_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req_h, timeout=10) as r:
            html_data = r.read()
            
        req_a = urllib.request.Request(app_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req_a, timeout=10) as r:
            app_data = r.read()
            
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
        print(f'  [OK]  Database: {os.path.basename(MDB_PATH)}')
    else:
        print(f'  [INFO]  No database selected yet — use the DB selector in the dashboard.')

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
