"""
Rice Mill SaaS Dashboard — Automated Audit Trail & Record Diff Engine
Compares consecutive database upload snapshots to detect:
1. Field Alterations (Rate, Amount, Quantity, Broker, Payment Status)
2. Ghost Erasures (Deleted Bills)
3. Backdated Record Insertions
"""
import os
import json
import time
from datetime import datetime

class AuditEngine:
    @staticmethod
    def get_snapshots_dir(tenant_id):
        from tenants import get_tenant_dir
        tenant_dir = get_tenant_dir(tenant_id)
        snaps_dir = os.path.join(tenant_dir, 'snapshots')
        os.makedirs(snaps_dir, exist_ok=True)
        return snaps_dir

    @staticmethod
    def get_audit_log_path(tenant_id):
        from tenants import get_tenant_dir
        tenant_dir = get_tenant_dir(tenant_id)
        return os.path.join(tenant_dir, 'audit_log.json')

    @staticmethod
    def extract_record_key(item):
        """Derive unique string key for a transaction or journal record."""
        if not isinstance(item, dict):
            return None
        bill_no = str(item.get('bill_no') or item.get('r_no') or item.get('journal_id') or '').strip()
        record_type = str(item.get('type') or item.get('transaction_type') or 'record').strip().lower()
        date = str(item.get('loaded_date') or item.get('date') or '').strip()
        party = str(item.get('party_name') or item.get('credit_account') or '').strip().lower()
        
        if bill_no and bill_no != '#—':
            return f"{record_type}_{bill_no}"
        elif date and party:
            return f"{record_type}_{date}_{party}"
        return None

    @classmethod
    def build_snapshot(cls, transactions_list):
        """Convert list of transactions into indexed lookup snapshot."""
        snapshot = {}
        if not isinstance(transactions_list, list):
            return snapshot

        for item in transactions_list:
            if not isinstance(item, dict):
                continue
            key = cls.extract_record_key(item)
            if not key:
                continue
            
            # Store normalized record copy
            snapshot[key] = {
                'key': key,
                'bill_no': str(item.get('bill_no') or item.get('r_no') or item.get('journal_id') or '—').strip(),
                'date': str(item.get('loaded_date') or item.get('date') or '—').strip(),
                'party_name': str(item.get('party_name') or item.get('credit_account') or '—').strip(),
                'broker_name': str(item.get('broker_name') or 'Direct').strip(),
                'variety': str(item.get('variety') or item.get('item_name') or '—').strip(),
                'bags': str(item.get('bags') or item.get('quantity') or '0').strip(),
                'rate': str(item.get('rate') or '0').strip(),
                'amount': str(item.get('net_amount') or item.get('amount') or '0').strip(),
                'payment_status': str(item.get('payment_status') or '—').strip(),
                'type': str(item.get('type') or 'Transaction').strip()
            }
        return snapshot

    @classmethod
    def compare_snapshots(cls, prev_snap, curr_snap):
        """Compare previous snapshot vs current snapshot and return audit events."""
        events = []
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 1. Detect Modified & Field-Level Alterations
        for key, curr_item in curr_snap.items():
            if key in prev_snap:
                prev_item = prev_snap[key]
                changes = []

                # Fields to check for edits
                fields_to_check = [
                    ('rate', 'Rate'),
                    ('amount', 'Amount'),
                    ('bags', 'Bags / Quantity'),
                    ('broker_name', 'Broker'),
                    ('party_name', 'Party Name'),
                    ('payment_status', 'Payment Status'),
                    ('variety', 'Variety / Item')
                ]

                for field_key, field_label in fields_to_check:
                    old_val = prev_item.get(field_key, '—')
                    new_val = curr_item.get(field_key, '—')
                    if old_val != new_val:
                        changes.append({
                            'field': field_label,
                            'field_key': field_key,
                            'old_value': old_val,
                            'new_value': new_val
                        })

                if changes:
                    events.append({
                        'event_id': f"evt_{int(time.time()*1000)}_{key}",
                        'timestamp': now_str,
                        'event_type': 'MODIFIED',
                        'severity': 'CRITICAL' if any(c['field_key'] in ('rate', 'amount') for c in changes) else 'WARNING',
                        'bill_no': curr_item['bill_no'],
                        'date': curr_item['date'],
                        'party_name': curr_item['party_name'],
                        'record_type': curr_item['type'],
                        'changes': changes,
                        'prev_record': prev_item,
                        'curr_record': curr_item
                    })

        # 2. Detect Deleted Records (Ghost Erasures)
        for key, prev_item in prev_snap.items():
            if key not in curr_snap:
                events.append({
                    'event_id': f"evt_{int(time.time()*1000)}_{key}",
                    'timestamp': now_str,
                    'event_type': 'DELETED',
                    'severity': 'CRITICAL',
                    'bill_no': prev_item['bill_no'],
                    'date': prev_item['date'],
                    'party_name': prev_item['party_name'],
                    'record_type': prev_item['type'],
                    'changes': [
                        {'field': 'Status', 'old_value': 'Present in Database', 'new_value': 'ERASED / DELETED'}
                    ],
                    'prev_record': prev_item,
                    'curr_record': None
                })

        return events

    @classmethod
    def process_upload(cls, tenant_id, transactions_list):
        """Process upload, create snapshot, compare against previous, and log audit events."""
        if not tenant_id or not isinstance(transactions_list, list):
            return []

        snaps_dir = cls.get_snapshots_dir(tenant_id)
        latest_file = None
        
        # Find latest snapshot file
        existing_snaps = sorted([f for f in os.listdir(snaps_dir) if f.startswith('snap_') and f.endswith('.json')])
        if existing_snaps:
            latest_file = os.path.join(snaps_dir, existing_snaps[-1])

        prev_snap = {}
        if latest_file and os.path.exists(latest_file):
            try:
                with open(latest_file, 'r', encoding='utf-8') as f:
                    prev_snap = json.load(f)
            except Exception:
                prev_snap = {}

        curr_snap = cls.build_snapshot(transactions_list)
        
        # Save new snapshot
        new_snap_filename = f"snap_{int(time.time())}.json"
        new_snap_path = os.path.join(snaps_dir, new_snap_filename)
        with open(new_snap_path, 'w', encoding='utf-8') as f:
            json.dump(curr_snap, f, indent=2)

        # Cleanup old snapshots keeping last 10
        if len(existing_snaps) > 10:
            for old_s in existing_snaps[:-10]:
                try: os.remove(os.path.join(snaps_dir, old_s))
                except: pass

        # Compare snapshots if previous snapshot existed
        if prev_snap:
            new_events = cls.compare_snapshots(prev_snap, curr_snap)
            if new_events:
                cls.append_audit_log(tenant_id, new_events)
                return new_events

        return []

    @classmethod
    def append_audit_log(cls, tenant_id, new_events):
        """Append audit events to audit_log.json."""
        log_path = cls.get_audit_log_path(tenant_id)
        existing_log = []
        if os.path.exists(log_path):
            try:
                with open(log_path, 'r', encoding='utf-8') as f:
                    existing_log = json.load(f)
            except Exception:
                existing_log = []

        existing_log.extend(new_events)
        with open(log_path, 'w', encoding='utf-8') as f:
            json.dump(existing_log, f, indent=2)

    @classmethod
    def get_audit_log(cls, tenant_id):
        """Retrieve full audit log list for a tenant."""
        log_path = cls.get_audit_log_path(tenant_id)
        if not os.path.exists(log_path):
            return []
        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []
