#!/usr/bin/env python3
"""Deterministic synthetic collections workflow dataset generator.
No real customer data or external data sources are used.
"""
import argparse, csv, json, random, hashlib, sqlite3
from pathlib import Path
from datetime import date, timedelta, datetime, time
from collections import Counter

SEED_DEFAULT = 20261022
AS_OF = date(2026, 10, 22)
OUT_DEFAULT = Path('output')

DATA_DICTIONARY = {
'Customer': {'pk':'customer_id','fields': {
'customer_id':['string','required','unique','CUS-YYYY-NNNNNN; immutable deterministic ID'], 'first_name':['string','required','', 'synthetic first name'], 'last_name':['string','required','', 'synthetic last name'], 'created_date':['date','required','','not after as_of_date'], 'customer_segment':['enum','required','standard|vulnerable|small_business','allowed enum'], 'preferred_language':['enum','required','en|hi|te|ta|kn','allowed enum']}},
'Account': {'pk':'account_id','fields': {
'account_id':['string','required','unique','ACC-YYYY-NNNNNN'], 'customer_id':['string','required','FK Customer','must reference Customer'], 'opened_date':['date','required','','<= as_of_date'], 'account_status':['enum','required','active|closed|paid_off','closed accounts must have zero balance where applicable'], 'hardship_flag':['boolean','required','','true/false'], 'risk_band':['enum','required','low|medium|high','allowed enum']}},
'Loan': {'pk':'loan_id','fields': {
'loan_id':['string','required','unique','LOAN-2026-NNNNNN'], 'account_id':['string','required','FK Account','must reference Account'], 'principal_amount':['decimal','required','INR','> 0'], 'annual_interest_rate':['decimal','required','percent','0..40'], 'term_months':['integer','required','months','exactly 3 installments per 12-month synthetic loan cohort'], 'origination_date':['date','required','','<= first due date'], 'loan_status':['enum','required','active|paid_off|closed','paid_off requires zero outstanding'], 'currency':['string','required','INR','fixed INR']}},
'Installment': {'pk':'installment_id','fields': {
'installment_id':['string','required','unique','INS-<loan-id>-NNN'], 'loan_id':['string','required','FK Loan','must reference Loan'], 'installment_number':['integer','required','1..3','unique with loan_id'], 'due_date':['date','required','','ascending within loan'], 'scheduled_amount':['decimal','required','INR','> 0'], 'paid_amount':['decimal','required','INR','>= 0; derived from allocated payments'], 'outstanding_amount':['decimal','required','INR','max(0, scheduled-paid) except labelled allocation anomaly'], 'installment_status':['enum','required','paid|partial|overdue|upcoming','derived from amounts and due date']}},
'DelinquencySnapshot': {'pk':'snapshot_id','fields': {
'snapshot_id':['string','required','unique','DS-YYYY-NNNNNN'], 'loan_id':['string','required','FK Loan','must reference Loan'], 'snapshot_date':['date','required','','as_of_date'], 'days_past_due':['integer','required','days','max(0, as_of_date-oldest unpaid due date)'], 'arrears_amount':['decimal','required','INR','sum outstanding for due installments'], 'oldest_unpaid_due_date':['date','optional','','null when no arrears'], 'snapshot_status':['enum','required','current|delinquent|paid_off|disputed','derived from loan/installment state']}},
'ContactPreference': {'pk':'preference_id','fields': {
'preference_id':['string','required','unique','PREF-<customer-id>'], 'customer_id':['string','required','FK Customer','one active preference per customer'], 'effective_from':['date','required','','<= as_of_date'], 'effective_to':['date','optional','','>= effective_from'], 'timezone':['string','required','Asia/Kolkata','fixed for synthetic data'], 'allowed_start_local':['time','required','','09:00 or 10:00'], 'allowed_end_local':['time','required','','18:00 or 19:00'], 'channel':['enum','required','phone|sms|email|letter','allowed channel'], 'do_not_contact':['boolean','required','','true blocks proactive contact']}},
'ContactAttempt': {'pk':'contact_attempt_id','fields': {
'contact_attempt_id':['string','required','unique','CTP-<case-id>-NNN'], 'case_id':['string','required','FK CollectionCase','must reference CollectionCase'], 'attempt_at':['datetime','required','','within preference window unless labelled anomaly'], 'channel':['enum','required','phone|sms|email|letter','must respect contact preference'], 'outcome':['enum','required','reached|no_answer|voicemail|dispute|hardship|promise_made|wrong_number|do_not_contact','allowed enum'], 'agent_id':['string','required','','synthetic agent ID'], 'notes_code':['enum','required','none|payment_plan|financial_difficulty|identity_check|dispute_raised','no free-text personal data']}},
'PromiseToPay': {'pk':'promise_id','fields': {
'promise_id':['string','required','unique','PTP-YYYY-NNNNNN'], 'case_id':['string','required','FK CollectionCase','must reference CollectionCase'], 'contact_attempt_id':['string','required','FK ContactAttempt','must reference a promise_made attempt'], 'promised_amount':['decimal','required','INR','>0 and <= arrears at promise time unless labelled anomaly'], 'promise_date':['date','required','','>= attempt date'], 'due_date':['date','required','','promise date..promise date+30 days'], 'promise_status':['enum','required','pending|kept|partial|broken|cancelled','reconciled from subsequent payments and due date']}},
'Payment': {'pk':'payment_id','fields': {
'payment_id':['string','required','unique','PMT-2026-NNNNNN'], 'loan_id':['string','required','FK Loan','must reference Loan'], 'installment_id':['string','required','FK Installment','must reference installment; deliberate mismatch only in labelled anomaly'], 'payment_date':['date','required','','<= as_of_date'], 'amount':['decimal','required','INR','>0'], 'payment_status':['enum','required','settled|reversed|pending','only settled payments count toward paid amount'], 'source':['enum','required','bank_transfer|upi|card|cash|standing_order','allowed enum']}},
'CollectionCase': {'pk':'case_id','fields': {
'case_id':['string','required','unique','COL-2026-NNNNNN'], 'loan_id':['string','required','FK Loan','must reference Loan'], 'snapshot_id':['string','required','FK DelinquencySnapshot','must reference snapshot'], 'case_status':['enum','required','open|paused_dispute|paused_hardship|closed_paid|closed_resolved','derived from delinquency, dispute and hardship'], 'priority_score':['decimal','required','0..100','explainable formula using arrears, DPD and risk band'], 'priority_band':['enum','required','low|medium|high|urgent','derived from score'], 'dispute_flag':['boolean','required','','disputed debt must be paused pending review'], 'hardship_flag':['boolean','required','','pause/adjust cadence as applicable'], 'next_action_date':['date','optional','','null if no contact permitted or case paused/closed'], 'decision_reason':['string','required','','rule codes, not free text']}},
}

def iso(x): return x.isoformat() if x else ''
def dtiso(x): return x.isoformat(timespec='minutes') if x else ''
def month_add(d, months):
    m=d.month-1+months; y=d.year+m//12; m=m%12+1
    import calendar
    return date(y,m,min(d.day,calendar.monthrange(y,m)[1]))
def money(x): return round(float(x)+1e-9,2)
def pick(rng, xs): return xs[rng.randrange(len(xs))]
def write_csv(path, rows):
    if not rows: return
    with path.open('w', newline='', encoding='utf-8') as f:
        w=csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()

def generate(n_loans=10000, seed=SEED_DEFAULT, out=OUT_DEFAULT, inject_anomalies=True):
    rng=random.Random(seed); out=Path(out); out.mkdir(parents=True,exist_ok=True)
    n_customers=n_loans; customers=[]; accounts=[]; loans=[]; installments=[]; snapshots=[]; prefs=[]; payments=[]; cases=[]; attempts=[]; promises=[]; truth=[]
    first_names=['Aarav','Ananya','Ishaan','Diya','Kabir','Meera','Arjun','Saanvi','Rohan','Tara','Kiran','Nisha']
    last_names=['Rao','Sharma','Reddy','Patel','Kumar','Iyer','Das','Singh','Naidu','Gupta','Menon','Joshi']
    # Master data first: deterministic IDs and valid references.
    for i in range(1,n_customers+1):
        cid=f'CUS-2026-{i:06d}'; created=AS_OF-timedelta(days=rng.randint(90,1800))
        seg=pick(rng,['standard']*78+['vulnerable']*15+['small_business']*7)
        customers.append(dict(customer_id=cid,first_name=pick(rng,first_names),last_name=pick(rng,last_names),created_date=iso(created),customer_segment=seg,preferred_language=pick(rng,['en','hi','te','ta','kn'])))
        aid=f'ACC-2026-{i:06d}'; hardship=rng.random()<0.09; risk=pick(rng,['low']*45+['medium']*38+['high']*17)
        accounts.append(dict(account_id=aid,customer_id=cid,opened_date=iso(created),account_status='active',hardship_flag=str(hardship).lower(),risk_band=risk))
        pref_do_not=rng.random()<0.06; start=pick(rng,['09:00','10:00']); end='18:00' if start=='09:00' else '19:00'
        prefs.append(dict(preference_id=f'PREF-{cid}',customer_id=cid,effective_from=iso(created),effective_to='',timezone='Asia/Kolkata',allowed_start_local=start,allowed_end_local=end,channel=pick(rng,['phone','sms','email','letter']),do_not_contact=str(pref_do_not).lower()))
    # Loan schedules and transaction history.
    for i in range(1,n_loans+1):
        aid=f'ACC-2026-{i:06d}'; lid=f'LOAN-2026-{i:06d}'; orig=AS_OF-timedelta(days=rng.randint(100,450)); principal=money(rng.uniform(15000,500000)); rate=round(rng.uniform(5,24),2); term=3
        # Three installments per loan; schedule spans a maximum of 12 months.
        installment_amt=money(principal*(1+rate/100*term/12)/term)
        loan_inst=[]
        for k in range(1,4):
            due=month_add(orig, k*4); iid=f'INS-{lid}-{k:03d}'
            loan_inst.append(dict(installment_id=iid,loan_id=lid,installment_number=k,due_date=iso(due),scheduled_amount=installment_amt,paid_amount=0.0,outstanding_amount=installment_amt,installment_status='upcoming'))
        # Use payment behavior to derive paid amounts. No independent balance assignment.
        for inst in loan_inst:
            if date.fromisoformat(inst['due_date']) <= AS_OF:
                behavior=rng.random()
                if behavior < .49: paid=inst['scheduled_amount']
                elif behavior < .63: paid=money(inst['scheduled_amount']*rng.uniform(.2,.85))
                else: paid=0.0
                if paid>0:
                    pdate=min(AS_OF,date.fromisoformat(inst['due_date'])+timedelta(days=rng.randint(-5,35)))
                    payments.append(dict(payment_id=f'PMT-2026-{len(payments)+1:06d}',loan_id=lid,installment_id=inst['installment_id'],payment_date=iso(pdate),amount=money(paid),payment_status='settled',source=pick(rng,['bank_transfer','upi','card','standing_order'])))
        loans.append(dict(loan_id=lid,account_id=aid,principal_amount=principal,annual_interest_rate=rate,term_months=term,origination_date=iso(orig),loan_status='active',currency='INR'))
        installments.extend(loan_inst)
    # Reconcile payments to installment IDs before deriving snapshots and cases.
    p_by_inst=Counter()
    for p in payments:
        if p['payment_status']=='settled': p_by_inst[p['installment_id']]+=p['amount']
    inst_by_loan={}
    for inst in installments:
        paid=money(p_by_inst[inst['installment_id']]); inst['paid_amount']=paid; inst['outstanding_amount']=money(max(0,inst['scheduled_amount']-paid))
        due=date.fromisoformat(inst['due_date'])
        inst['installment_status']='paid' if inst['outstanding_amount']<=0.009 else ('partial' if paid>0 else ('overdue' if due<=AS_OF else 'upcoming'))
        inst['scheduled_amount']=money(inst['scheduled_amount']); inst['paid_amount']=money(inst['paid_amount']); inst['outstanding_amount']=money(inst['outstanding_amount'])
        inst_by_loan.setdefault(inst['loan_id'],[]).append(inst)
    # One delinquency snapshot and collection case per loan.
    account_by_id={a['account_id']:a for a in accounts}; pref_by_customer={p['customer_id']:p for p in prefs}
    for i,loan in enumerate(loans,1):
        lid=loan['loan_id']; group=inst_by_loan[lid]; due_unpaid=[x for x in group if date.fromisoformat(x['due_date'])<=AS_OF and x['outstanding_amount']>0.009]
        arrears=money(sum(x['outstanding_amount'] for x in due_unpaid)); oldest=min((date.fromisoformat(x['due_date']) for x in due_unpaid),default=None); dpd=max(0,(AS_OF-oldest).days) if oldest else 0
        aid=loan['account_id']; acct=account_by_id[aid]; cid=acct['customer_id']; pref=pref_by_customer[cid]
        disputed=rng.random()<.035; hardship=acct['hardship_flag']=='true'; paid_off=all(x['outstanding_amount']<=0.009 for x in group)
        snap_id=f'DS-2026-{i:06d}'; status='paid_off' if paid_off else ('disputed' if disputed else ('delinquent' if arrears>0 else 'current'))
        snapshots.append(dict(snapshot_id=snap_id,loan_id=lid,snapshot_date=iso(AS_OF),days_past_due=dpd,arrears_amount=arrears,oldest_unpaid_due_date=iso(oldest),snapshot_status=status))
        risk=acct['risk_band']; score=min(100, round(min(arrears/5000,30)+min(dpd/3,40)+({'low':5,'medium':15,'high':25}[risk]),2))
        band='urgent' if score>=75 else ('high' if score>=55 else ('medium' if score>=30 else 'low'))
        if paid_off or arrears<=0: cstatus='closed_paid'; next_action=''
        elif disputed: cstatus='paused_dispute'; next_action=''
        elif hardship: cstatus='paused_hardship'; next_action=''
        elif pref['do_not_contact']=='true': cstatus='open'; next_action=''
        else: cstatus='open'; next_action=iso(AS_OF+timedelta(days=1 if dpd>=30 else 3))
        reason='PAID_OFF' if paid_off or arrears<=0 else ('DISPUTE_REVIEW_REQUIRED' if disputed else ('HARDSHIP_REVIEW_REQUIRED' if hardship else ('CONTACT_RESTRICTED' if pref['do_not_contact']=='true' else f'SCORE_ARREARS_DPD_RISK:{band.upper()}')))
        cases.append(dict(case_id=f'COL-2026-{i:06d}',loan_id=lid,snapshot_id=snap_id,case_status=cstatus,priority_score=score,priority_band=band,dispute_flag=str(disputed).lower(),hardship_flag=str(hardship).lower(),next_action_date=next_action,decision_reason=reason))
    # Contact events and promise records generated only for eligible open cases.
    case_by_id={c['case_id']:c for c in cases}; loan_by_id={l['loan_id']:l for l in loans}; snap_by_loan={s['loan_id']:s for s in snapshots}; pref_by_customer={p['customer_id']:p for p in prefs}
    for idx,c in enumerate(cases,1):
        if c['case_status']!='open' or not c['next_action_date']: continue
        loan=loan_by_id[c['loan_id']]; acct=account_by_id[loan['account_id']]; pref=pref_by_customer[acct['customer_id']]
        if pref['do_not_contact']=='true': continue
        n_attempts=1 if rng.random()<.65 else 2
        for j in range(1,n_attempts+1):
            day=AS_OF-timedelta(days=rng.randint(0,25)); start=int(pref['allowed_start_local'][:2]); end=int(pref['allowed_end_local'][:2]); hour=rng.randint(start,end-1); minute=pick(rng,[0,15,30,45]); at=datetime.combine(day,time(hour,minute))
            outcome=pick(rng,['reached','no_answer','voicemail','promise_made','hardship','dispute','wrong_number'])
            # Contact outcomes that imply an exception are represented as workflow flags, not free text.
            attempt_id=f'CTP-{c["case_id"]}-{j:03d}'
            attempts.append(dict(contact_attempt_id=attempt_id,case_id=c['case_id'],attempt_at=dtiso(at),channel=pref['channel'],outcome=outcome,agent_id=f'AGT-{rng.randint(1,30):03d}',notes_code={'promise_made':'payment_plan','hardship':'financial_difficulty','dispute':'dispute_raised'}.get(outcome,'none')))
            if outcome=='promise_made':
                arrears=float(snap_by_loan[loan['loan_id']]['arrears_amount']); amount=money(min(arrears, max(100,rng.uniform(.15,.7)*arrears))) if arrears>0 else 0
                if amount>0:
                    pdate=day+timedelta(days=rng.randint(1,14)); due=pdate+timedelta(days=rng.randint(0,14))
                    promises.append(dict(promise_id=f'PTP-2026-{len(promises)+1:06d}',case_id=c['case_id'],contact_attempt_id=attempt_id,promised_amount=amount,promise_date=iso(pdate),due_date=iso(due),promise_status='pending'))
    # Reconcile promise status from settled payments to the promise due date.
    pay_by_loan={}
    for p in payments:
        if p['payment_status']=='settled': pay_by_loan.setdefault(p['loan_id'],[]).append(p)
    for promise in promises:
        c=case_by_id[promise['case_id']]; due=date.fromisoformat(promise['due_date']); pdate=date.fromisoformat(promise['promise_date']); loan_id=c['loan_id']
        # Only payments dated on/after promise date and through due date count as fulfilment.
        eligible=[p for p in pay_by_loan.get(loan_id,[]) if pdate<=date.fromisoformat(p['payment_date'])<=due]
        paid=sum(float(p['amount']) for p in eligible); target=float(promise['promised_amount'])
        if paid>=target-.009: status='kept'
        elif AS_OF>due: status='partial' if paid>0 else 'broken'
        else: status='pending'
        promise['promise_status']=status
    # Deliberately inject labelled anomalies into otherwise valid data.
    if inject_anomalies and n_loans>=10:
        # Paid account remains in collection: make a paid-off loan's case open.
        idx=next((i for i,s in enumerate(snapshots) if s['snapshot_status']=='paid_off'),0)
        if idx < len(cases):
            cases[idx]['case_status']='open'; cases[idx]['next_action_date']=iso(AS_OF+timedelta(days=1)); cases[idx]['decision_reason']='ANOMALY_PAID_ACCOUNT_IN_COLLECTION'
            truth.append(dict(issue_id='ANOM-001',issue_type='paid_account_remains_in_collection',entity_type='CollectionCase',entity_id=cases[idx]['case_id'],ground_truth='should_be_closed_paid',expected_decision='suppress_collection_and_close_case',severity='high'))
        # Contact outside allowed window: one attempt at 22:15.
        if attempts:
            a=attempts[0]; a['attempt_at']=a['attempt_at'].split('T')[0]+'T22:15'; truth.append(dict(issue_id='ANOM-002',issue_type='contact_outside_allowed_window',entity_type='ContactAttempt',entity_id=a['contact_attempt_id'],ground_truth='prohibited_contact_time',expected_decision='flag_and_prevent_contact',severity='high'))
       

    # Payment allocated to a different installment from its loan.
    if len(payments) >= 2:
        p = payments[0]
        other = next(
            (x for x in installments if x['loan_id'] != p['loan_id']),
            None
        )
        if other:
            p['original_installment_id'] = p['installment_id']
            p['installment_id'] = other['installment_id']
            truth.append(dict(
                issue_id='ANOM-003',
                issue_type='payment_allocated_to_wrong_installment',
                entity_type='Payment',
                entity_id=p['payment_id'],
                ground_truth='foreign_parent_mismatch',
                expected_decision='quarantine_and_reconcile_allocation',
                severity='high'
            ))


        # Promise amount exceeds arrears at the time of promise.
        if promises:
            pr=promises[0]; snap=snap_by_loan[case_by_id[pr['case_id']]['loan_id']]; pr['promised_amount']=money(float(snap['arrears_amount'])+500); truth.append(dict(issue_id='ANOM-004',issue_type='promise_amount_exceeds_arrears',entity_type='PromiseToPay',entity_id=pr['promise_id'],ground_truth='promise_amount_above_arrears',expected_decision='reject_or_reconfirm_promise',severity='medium'))
        # Disputed debt treated as confirmed: turn a case with dispute flag on into an open collection case.
        disputed_case=next((c for c in cases if c['dispute_flag']=='true'),None)
        if disputed_case:
            disputed_case['case_status']='open'; disputed_case['decision_reason']='ANOMALY_DISPUTED_DEBT_TREATED_AS_CONFIRMED'; disputed_case['next_action_date']=iso(AS_OF+timedelta(days=1))
            truth.append(dict(issue_id='ANOM-005',issue_type='disputed_debt_treated_as_confirmed',entity_type='CollectionCase',entity_id=disputed_case['case_id'],ground_truth='must_pause_for_dispute_review',expected_decision='pause_collection_until_reviewed',severity='high'))
    # Write all tables as CSV and JSON.
    tables={'Customer':customers,'Account':accounts,'Loan':loans,'Installment':installments,'DelinquencySnapshot':snapshots,'ContactPreference':prefs,'ContactAttempt':attempts,'PromiseToPay':promises,'Payment':payments,'CollectionCase':cases}
    for name, rows in tables.items():
        write_csv(out/f'{name}.csv', rows)
        with (out/f'{name}.json').open('w',encoding='utf-8') as f: json.dump(rows,f,indent=2,ensure_ascii=False)
    write_csv(out/'ground_truth.csv',truth)
    (out/'ground_truth.json').write_text(json.dumps(truth,indent=2),encoding='utf-8')
    (out/'data_dictionary.json').write_text(json.dumps(DATA_DICTIONARY,indent=2),encoding='utf-8')
    # SQL schema + seed inserts in a portable SQLite script.
    db_path=out/'collections_seed.sqlite';
    if db_path.exists(): db_path.unlink()
    conn=sqlite3.connect(db_path); cur=conn.cursor()
    schemas={
    'Customer':'customer_id TEXT PRIMARY KEY, first_name TEXT NOT NULL, last_name TEXT NOT NULL, created_date TEXT NOT NULL, customer_segment TEXT NOT NULL, preferred_language TEXT NOT NULL',
    'Account':'account_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES Customer(customer_id), opened_date TEXT NOT NULL, account_status TEXT NOT NULL, hardship_flag TEXT NOT NULL, risk_band TEXT NOT NULL',
    'Loan':'loan_id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES Account(account_id), principal_amount REAL NOT NULL, annual_interest_rate REAL NOT NULL, term_months INTEGER NOT NULL, origination_date TEXT NOT NULL, loan_status TEXT NOT NULL, currency TEXT NOT NULL',
    'Installment':'installment_id TEXT PRIMARY KEY, loan_id TEXT NOT NULL REFERENCES Loan(loan_id), installment_number INTEGER NOT NULL, due_date TEXT NOT NULL, scheduled_amount REAL NOT NULL, paid_amount REAL NOT NULL, outstanding_amount REAL NOT NULL, installment_status TEXT NOT NULL, UNIQUE(loan_id, installment_number)',
    'DelinquencySnapshot':'snapshot_id TEXT PRIMARY KEY, loan_id TEXT NOT NULL REFERENCES Loan(loan_id), snapshot_date TEXT NOT NULL, days_past_due INTEGER NOT NULL, arrears_amount REAL NOT NULL, oldest_unpaid_due_date TEXT, snapshot_status TEXT NOT NULL',
    'ContactPreference':'preference_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES Customer(customer_id), effective_from TEXT NOT NULL, effective_to TEXT, timezone TEXT NOT NULL, allowed_start_local TEXT NOT NULL, allowed_end_local TEXT NOT NULL, channel TEXT NOT NULL, do_not_contact TEXT NOT NULL',
    'ContactAttempt':'contact_attempt_id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES CollectionCase(case_id), attempt_at TEXT NOT NULL, channel TEXT NOT NULL, outcome TEXT NOT NULL, agent_id TEXT NOT NULL, notes_code TEXT NOT NULL',
    'PromiseToPay':'promise_id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES CollectionCase(case_id), contact_attempt_id TEXT NOT NULL REFERENCES ContactAttempt(contact_attempt_id), promised_amount REAL NOT NULL, promise_date TEXT NOT NULL, due_date TEXT NOT NULL, promise_status TEXT NOT NULL',
    'Payment':'payment_id TEXT PRIMARY KEY, loan_id TEXT NOT NULL REFERENCES Loan(loan_id), installment_id TEXT NOT NULL REFERENCES Installment(installment_id), payment_date TEXT NOT NULL, amount REAL NOT NULL, payment_status TEXT NOT NULL, source TEXT NOT NULL',
    'CollectionCase':'case_id TEXT PRIMARY KEY, loan_id TEXT NOT NULL REFERENCES Loan(loan_id), snapshot_id TEXT NOT NULL REFERENCES DelinquencySnapshot(snapshot_id), case_status TEXT NOT NULL, priority_score REAL NOT NULL, priority_band TEXT NOT NULL, dispute_flag TEXT NOT NULL, hardship_flag TEXT NOT NULL, next_action_date TEXT, decision_reason TEXT NOT NULL'}
    # Create case before child events; foreign keys are checked after all inserts.
    order=['Customer','Account','Loan','Installment','DelinquencySnapshot','ContactPreference','CollectionCase','ContactAttempt','PromiseToPay','Payment']
    for name in order: cur.execute(f'CREATE TABLE "{name}" ({schemas[name]})')
    for name in order:
        rows = tables[name]
        if not rows:
            continue

        if name == 'Payment':
            rows = [
                {k: v for k, v in r.items()
                 if k != 'original_installment_id'}
                for r in rows
            ]
            tables[name] = rows

        cols = list(rows[0].keys())
        placeholders = ','.join(['?'] * len(cols))
        sql = f'INSERT INTO "{name}" ({",".join(chr(34)+c+chr(34) for c in cols)}) VALUES ({placeholders})'
        cur.executemany(
            sql,
            [[r.get(c) if r.get(c) != '' else None for c in cols]
             for r in rows]
        )

    # SQL text seed artifact from SQLite DB, including DDL and data.
    conn=sqlite3.connect(db_path); sql_dump='\n'.join(conn.iterdump()); conn.close(); (out/'seed.sql').write_text(sql_dump,encoding='utf-8')
    # Validation: anomalies expected only when labelled; report counts and integrity checks.
    report=[]
    def check(name, ok, detail): report.append({'check':name,'status':'PASS' if ok else 'FAIL','detail':detail})
    for name, rows in tables.items():
        pk=DATA_DICTIONARY[name]['pk']; vals=[r[pk] for r in rows]; check(f'{name}.primary_key_unique',len(vals)==len(set(vals)),f'{len(vals)} rows; {len(vals)-len(set(vals))} duplicate keys')
    ids={name:{r[DATA_DICTIONARY[name]['pk']] for r in rows} for name,rows in tables.items()}
    fk_checks=[('Account.customer_id','Account','customer_id','Customer'),('Loan.account_id','Loan','account_id','Account'),('Installment.loan_id','Installment','loan_id','Loan'),('DelinquencySnapshot.loan_id','DelinquencySnapshot','loan_id','Loan'),('ContactPreference.customer_id','ContactPreference','customer_id','Customer'),('CollectionCase.loan_id','CollectionCase','loan_id','Loan'),('CollectionCase.snapshot_id','CollectionCase','snapshot_id','DelinquencySnapshot'),('ContactAttempt.case_id','ContactAttempt','case_id','CollectionCase'),('PromiseToPay.case_id','PromiseToPay','case_id','CollectionCase'),('PromiseToPay.contact_attempt_id','PromiseToPay','contact_attempt_id','ContactAttempt'),('Payment.loan_id','Payment','loan_id','Loan'),('Payment.installment_id','Payment','installment_id','Installment')]
    for label,table,col,parent in fk_checks:
        bad=[r for r in tables[table] if r[col] not in ids[parent]]; check(label,len(bad)==0,f'{len(bad)} missing references (some may be labelled anomaly)')
    installment_loan={r['installment_id']:r['loan_id'] for r in installments}
    cross_parent=[p for p in payments if p['installment_id'] in installment_loan and p['loan_id'] != installment_loan[p['installment_id']]]
    labelled_payment_ids={x['entity_id'] for x in truth if x['issue_type']=='payment_allocated_to_wrong_installment'}
    unexpected_cross=[p for p in cross_parent if p['payment_id'] not in labelled_payment_ids]
    check('Payment.loan_matches_Installment.loan',len(unexpected_cross)==0,f'{len(cross_parent)} cross-parent mismatches; {len(unexpected_cross)} are unlabelled')
    # Derived arithmetic is validated against source payments; injected allocation mismatch is reported as exception.
   
    mismatch = []
    for inst in installments:
        actual = money(sum(
            float(p['amount'])
            for p in payments
            if p['installment_id'] == inst['installment_id']
        ))
        if abs(actual - float(inst['paid_amount'])) > 0.011:
            mismatch.append(inst['installment_id'])

    wrong_allocation_ids = {
        x['entity_id']
        for x in truth
        if x['issue_type'] == 'payment_allocated_to_wrong_installment'
    }
    wrong_allocation_payments = {
        p['payment_id']
        for p in payments
        if p['payment_id'] in wrong_allocation_ids
    }
    
    affected_installments = set()
    for p in payments:
        if p['payment_id'] in wrong_allocation_payments:
            affected_installments.add(p['installment_id'])
            original_inst = p.get('original_installment_id')
            if original_inst:
                affected_installments.add(original_inst)


    unexplained_mismatches = [
        iid for iid in mismatch
        if iid not in affected_installments
    ]

    check(
        'installment_payment_reconciliation',
        len(unexplained_mismatches) == 0,
        f'{len(mismatch)} total mismatches; '
        f'{len(unexplained_mismatches)} unexplained'
    )


    anomaly_types={x['issue_type'] for x in truth}
    check('required_anomaly_labels',set(['paid_account_remains_in_collection','contact_outside_allowed_window','payment_allocated_to_wrong_installment','promise_amount_exceeds_arrears','disputed_debt_treated_as_confirmed']).issubset(anomaly_types),f'{len(truth)} labelled ground-truth cases')
    # Counts, checksums, seed and manifest.
    manifest={'generator':'generate_data.py','seed':seed,'as_of_date':iso(AS_OF),'loans_requested':n_loans,'table_row_counts':{k:len(v) for k,v in tables.items()},'ground_truth_rows':len(truth),'external_data_used':False,'source_manifest':[{'source':'synthetic_generator','url':None,'license':'not applicable; wholly synthetic','retrieval_date':None,'transformations':'seeded generation; deterministic derived fields'}]}
    (out/'source_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    # Checksums exclude manifest/report to avoid recursive hashes.
    files=sorted([p for p in out.iterdir() if p.is_file() and p.name not in ('checksums.json','validation_summary.json')])
    (out/'checksums.json').write_text(json.dumps({p.name:digest(p) for p in files},indent=2),encoding='utf-8')
    summary={'seed':seed,'as_of_date':iso(AS_OF),'row_counts':manifest['table_row_counts'],'checks':report,'failed_checks':sum(x['status']=='FAIL' for x in report),'ground_truth_issue_types':dict(Counter(x['issue_type'] for x in truth))}
    (out/'validation_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    (out/'README.md').write_text(f'''# Synthetic Collections Workflow Dataset\n\n## Purpose\nA deterministic, wholly synthetic dataset for testing fair, explainable delinquency prioritization, contact scheduling, promise tracking and payment reconciliation. No real personal or financial data is used.\n\n## Reproduce\n```bash\npython generate_data.py --loans 10000 --seed 20261022 --out output\n```\nFor a quick starter set: `python generate_data.py --loans 100 --seed 20261022 --out starter_output`. The same seed and scale produce byte-identical logical rows; SQLite file bytes may vary by runtime version.\n\n## Files\n- One CSV and JSON file per entity: Customer, Account, Loan, Installment, DelinquencySnapshot, ContactPreference, ContactAttempt, PromiseToPay, Payment, CollectionCase.\n- `ground_truth.csv/json`: labelled injected exceptions and expected safe decisions; **exclude from model features**.\n- `data_dictionary.json`: field types, requirements, enums, units and validation guidance.\n- `collections_seed.sqlite` and `seed.sql`: SQLite schema and seed data.\n- `source_manifest.json`, `checksums.json`, `validation_summary.json`: provenance, integrity evidence and row counts.\n\n## Core decisions\n- DPD = days from the oldest unpaid due installment to the snapshot date, floored at zero.\n- Arrears = sum of outstanding amounts on due installments.\n- Score = capped combination of arrears (0–30), DPD (0–40) and risk band (5/15/25), capped at 100. This is an operational prioritization aid, not a creditworthiness or legal decision.\n- Disputed cases and hardship cases are paused for review; do-not-contact preferences suppress proactive scheduling. No threats, repeated-contact escalation, or legal-status assumptions are encoded.\n- Contact window is local time in Asia/Kolkata, with customer-specific allowed start/end values.\n- Promise status is reconciled from settled payments between promise date and due date.\n\n## Known limitations / review notes\n- A 3-installment-per-loan schedule gives exactly 30,000 installments for 10,000 loans and spans up to 12 months.\n- `ground_truth` anomalies are intentionally injected after baseline generation; related reconciliation checks can therefore fail by design. Treat these as exception-path test fixtures, not clean production records.\n- This starter uses one account per customer and one loan per account. The schema supports extension to multiple loans/accounts with bridge tables if the business needs many-to-many relationships.\n- Review local consumer-protection, privacy, contact-time and debt-collection requirements before any real-world deployment.\n''',encoding='utf-8')
    return summary

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--loans',type=int,default=10000); ap.add_argument('--seed',type=int,default=SEED_DEFAULT); ap.add_argument('--out',default=str(OUT_DEFAULT)); ap.add_argument('--no-anomalies',action='store_true'); args=ap.parse_args()
    print(json.dumps(generate(args.loans,args.seed,args.out,not args.no_anomalies),indent=2))
