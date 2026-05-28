import streamlit as st
import pandas as pd
import sqlite3 
from ortools.sat.python import cp_model
from streamlit_calendar import calendar
from datetime import datetime, timedelta
from fpdf import FPDF
import time

# --- 1. PAGE CONFIG & CUSTOM CSS ---
st.set_page_config(page_title="AI Powered Class Scheduler", page_icon="📅", layout="wide")

st.markdown("""
    <style>
    .stStatusWidget { visibility: hidden; } /* Hide running icon */
    .main { background-color: #f8f9fa; }
    .stButton>button { width: 100%; border-radius: 8px; font-weight: bold; }
    .header-style {
        background: linear-gradient(90deg, #4b6cb7 0%, #182848 100%);
        padding: 1.5rem; border-radius: 10px; color: white; text-align: center;
        margin-bottom: 2rem; box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .custom-footer {
        width: 100%;
        text-align: center;
        padding: 20px;
        margin-top: 50px;
        border-top: 1px solid #e0e0e0;
        color: #666;
        font-family: 'Arial', sans-serif;
        font-size: 14px;
        font-weight: 500;
    }
    </style>
""", unsafe_allow_html=True)

# --- 2. DATABASE CONFIGURATION (SQLITE) ---
DB_FILE = 'school_db.db'

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

# ==========================================
#        🔒 AUTHENTICATION LOGIC
# ==========================================

def init_user_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                password TEXT,
                role TEXT DEFAULT 'user',
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("SELECT * FROM users WHERE username = 'admin'")
        if not cursor.fetchone():
            cursor.execute("INSERT INTO users (username, password, role, status) VALUES ('admin', 'admin123', 'admin', 'approved')")
            conn.commit()
        conn.close()
    except Exception as e: st.error(f"DB Init Error: {e}")

def register_user(username, password):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (username, password, role, status) VALUES (?, ?, 'user', 'pending')", (username, password))
        conn.commit()
        conn.close()
        return True, "Registered! Status: PENDING Admin Approval."
    except sqlite3.IntegrityError: return False, "Username taken."
    except Exception as e: return False, str(e)

def login_user(username, password):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, password))
        user = cursor.fetchone()
        conn.close()
        if user:
            if user['status'] == 'approved': return True, user, "Success"
            else: return False, None, "🚫 Account PENDING Approval."
        return False, None, "❌ Invalid Credentials"
    except Exception as e: return False, None, str(e)

def get_pending_users():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username FROM users WHERE status = 'pending'")
        rows = cursor.fetchall()
        conn.close()
        return rows
    except: return []

def approve_user(user_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET status = 'approved' WHERE id = ?", (user_id,))
        conn.commit()
        conn.close()
        return True
    except: return False

def delete_user_db(user_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        conn.close()
        return True
    except: return False

init_user_db()

# ==========================================
#        🔐 SESSION PERSISTENCE (AUTO-LOGIN)
# ==========================================
# Check URL params BEFORE initializing defaults to prevent logout on refresh
if "logged_user" in st.query_params and "logged_role" in st.query_params:
    st.session_state.authenticated = True
    st.session_state.username = st.query_params["logged_user"]
    st.session_state.user_role = st.query_params["logged_role"]

if 'authenticated' not in st.session_state: st.session_state.authenticated = False
if 'user_role' not in st.session_state: st.session_state.user_role = None
if 'username' not in st.session_state: st.session_state.username = None

# ==========================================
#        🔐 LOGIN SCREEN
# ==========================================

if not st.session_state.authenticated:
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.markdown('<div class="header-style"><h2>🔒 Secure Login</h2></div>', unsafe_allow_html=True)
        t1, t2 = st.tabs(["Login", "Sign Up"])
        with t1:
            with st.form("log"):
                u = st.text_input("Username")
                p = st.text_input("Password", type="password")
                if st.form_submit_button("Login", type="primary"):
                    ok, d, m = login_user(u,p)
                    if ok:
                        st.session_state.authenticated = True
                        st.session_state.user_role = d['role']
                        st.session_state.username = d['username']
                        
                        # --- SAVE TO URL FOR PERSISTENCE ---
                        st.query_params["logged_user"] = d['username']
                        st.query_params["logged_role"] = d['role']
                        
                        st.rerun()
                    else: st.error(m)
        with t2:
            with st.form("reg"):
                nu = st.text_input("New User")
                np = st.text_input("New Pass", type="password")
                if st.form_submit_button("Sign Up"):
                    if not nu.strip() or not np.strip():
                        st.warning("⚠️ Please enter both a Username and a Password.")
                    else:
                        ok, m = register_user(nu, np)
                        if ok: st.success(m)
                        else: st.error(m)
    st.stop()

# ==========================================
#      🚀 MAIN APP 
# ==========================================

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
TIMESLOTS = []
TIME_OBJECTS = [] 
current = datetime(2024, 1, 1, 7, 30)
limit = datetime(2024, 1, 1, 20, 0)
while current < limit:
    TIMESLOTS.append(current.strftime("%I:%M %p").lstrip("0"))
    TIME_OBJECTS.append(current)
    current += timedelta(minutes=30)

SLOT_INDICES = range(len(TIMESLOTS))
DAY_INDICES = range(len(DAYS))

# INIT SESSION
if "rooms" not in st.session_state: st.session_state.rooms = ["Room 101", "Room 102", "ComLab 1"] 
if "sections" not in st.session_state: st.session_state.sections = ["BSCS-1A", "BSIT-1A"] 
if "teachers" not in st.session_state: st.session_state.teachers = {} 
if "classes" not in st.session_state: st.session_state.classes = [] 
if "final_schedule" not in st.session_state: st.session_state.final_schedule = []
if "calendar_events" not in st.session_state: st.session_state.calendar_events = [] 

# HELPERS
def get_end_time(start_str):
    t = datetime.strptime(start_str, "%I:%M %p")
    return (t + timedelta(minutes=90)).strftime("%I:%M %p").lstrip("0")

def get_slots(start, end):
    try:
        s = next(i for i, t in enumerate(TIMESLOTS) if t == start)
        e = next(i for i, t in enumerate(TIMESLOTS) if t == end)
        return list(range(s, e))
    except: return []

def fmt_time(v, pm=False):
    h = v + 12 if pm and v < 12 else (12 if pm else v)
    return datetime(2024,1,1,h,0).strftime("%I:%M %p").lstrip("0")

# --- PDF GENERATOR ---
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 16)
        self.cell(0, 10, 'Official Class Schedule', 0, 1, 'C')
        self.ln(5)
    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

def generate_pdf(dataframe):
    pdf = PDF(orientation='L') 
    pdf.add_page()
    pdf.set_font("Arial", size=10)
    pdf.set_fill_color(200, 220, 255)
    pdf.set_font("Arial", 'B', 10)
    cols = [("Day", 25), ("Time", 45), ("Subject", 55), ("Professor", 50), ("Section", 30), ("Room", 30)]
    for col_name, width in cols: pdf.cell(width, 10, col_name, 1, 0, 'C', 1)
    pdf.ln()
    pdf.set_font("Arial", size=9)
    for _, row in dataframe.iterrows():
        pdf.cell(25, 10, str(row['Day']), 1, 0, 'C')
        pdf.cell(45, 10, str(row['Time']), 1, 0, 'C')
        pdf.cell(55, 10, str(row['Subject'])[:28], 1, 0, 'L') 
        pdf.cell(50, 10, str(row['Professor'])[:25], 1, 0, 'L')
        pdf.cell(30, 10, str(row['Section']), 1, 0, 'C')
        pdf.cell(30, 10, str(row['Room']), 1, 1, 'C')
    return pdf.output(dest='S').encode('latin-1', 'ignore')

# --- DATABASE & LOADERS ---
def save_db(sched):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS generated_schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT, generation_id INTEGER, day_of_week TEXT,
            time_slot TEXT, subject_name TEXT, professor TEXT,
            section_name TEXT, room_name TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        
        c.execute("SELECT MAX(generation_id) FROM generated_schedule")
        r = c.fetchone()
        current_max = r[0] if r and r[0] is not None else 0
        nxt = current_max + 1
        
        vals = [(nxt, x['Day'], x['Time'], x['Subject'], x.get('Professor', x.get('Teacher')), x['Section'], x['Room']) for x in sched]
        c.executemany("INSERT INTO generated_schedule (generation_id, day_of_week, time_slot, subject_name, professor, section_name, room_name) VALUES (?,?,?,?,?,?,?)", vals)
        conn.commit(); conn.close()
        return True, f"Saved Gen {nxt}"
    except Exception as e: return False, str(e)

def get_gens():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT generation_id, MIN(created_at) FROM generated_schedule GROUP BY generation_id ORDER BY generation_id DESC")
        data = c.fetchall()
        conn.close()
        return data
    except: return []

def delete_generation(gen_id):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("DELETE FROM generated_schedule WHERE generation_id = ?", (gen_id,))
        conn.commit()
        conn.close()
        return True
    except: return False

def load_gen(gid):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute(f"SELECT * FROM generated_schedule WHERE generation_id = ?", (gid,))
        rows = c.fetchall()
        conn.close()
        res = []
        for r in rows:
            st_str = r['time_slot'].split(' - ')[0]
            try: 
                idx = TIMESLOTS.index(st_str)
                h, m = TIME_OBJECTS[idx].hour, TIME_OBJECTS[idx].minute
            except: h, m = 8, 0
            res.append({"Day":r['day_of_week'],"Time":r['time_slot'],"Subject":r['subject_name'],
                        "Professor":r['professor'],"Section":r['section_name'],"Room":r['room_name'],
                        "day_idx":DAYS.index(r['day_of_week']) if r['day_of_week'] in DAYS else 0, "h_24":h,"m":m})
        return res
    except: return []

def build_calendar_events(schedule_data):
    evts = []
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    for x in schedule_data:
        base = monday + timedelta(days=x['day_idx'])
        s = base.replace(hour=x['h_24'], minute=x['m'], second=0)
        e = s + timedelta(minutes=90)
        clr = "#3498DB" 
        if "Lab" in x['Room']: clr = "#E67E22"
        evts.append({
            "title": f"{x['Subject']}\n{x['Room']}", "start": s.isoformat(), "end": e.isoformat(),
            "backgroundColor": clr, "borderColor": "#ffffff",
            "extendedProps": {"desc": f"Prof: {x['Professor']} | Sec: {x['Section']}"}
        })
    return evts

# --- SOLVER ---
def solve():
    model = cp_model.CpModel()
    classes = st.session_state.classes
    rooms = st.session_state.rooms
    if not classes or not rooms: return None
    vars_ = {}
    
    for c in range(len(classes)):
        for r in range(len(rooms)):
            for d in DAY_INDICES:
                for t in SLOT_INDICES:
                    if t+3 <= len(TIMESLOTS): vars_[(c,r,d,t)] = model.NewBoolVar(f"{c}_{r}_{d}_{t}")
    
    for c in range(len(classes)):
        opts = [vars_[(c,r,d,t)] for r in range(len(rooms)) for d in DAY_INDICES for t in SLOT_INDICES if (c,r,d,t) in vars_]
        if opts: model.Add(sum(opts) == 1)
        else: return None
        
    for d in DAY_INDICES:
        for t in SLOT_INDICES:
            active = []
            for off in range(3):
                ts = t - off
                if ts >= 0:
                    for c in range(len(classes)):
                        for r in range(len(rooms)):
                            if (c,r,d,ts) in vars_: active.append((c,r,vars_[(c,r,d,ts)]))
            for r in range(len(rooms)):
                if (acts := [v for (ci, ri, v) in active if ri == r]): model.Add(sum(acts) <= 1)
            for tn in st.session_state.teachers:
                t_idxs = [i for i,x in enumerate(classes) if x['Teacher'] == tn]
                if (acts := [v for (ci, ri, v) in active if ci in t_idxs]): model.Add(sum(acts) <= 1)
            for sn in st.session_state.sections:
                s_idxs = [i for i,x in enumerate(classes) if x['Section'] == sn]
                if (acts := [v for (ci, ri, v) in active if ci in s_idxs]): model.Add(sum(acts) <= 1)

    for c, item in enumerate(classes):
        allowed = item['Allowed_Rooms']
        for ri, rname in enumerate(rooms):
            if rname not in allowed:
                for key in vars_:
                    if key[0]==c and key[1]==ri: model.Add(vars_[key]==0)
        tsched = st.session_state.teachers.get(item['Teacher'], {})
        for d in DAY_INDICES:
            ok_slots = tsched.get(DAYS[d], [])
            for t in SLOT_INDICES:
                if t not in ok_slots:
                    for ri in range(len(rooms)):
                        if (c,ri,d,t) in vars_: model.Add(vars_[(c,ri,d,t)]==0)

    solver = cp_model.CpSolver()
    if solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        final = []
        for k, v in vars_.items():
            if solver.Value(v):
                c,r,d,t = k
                final.append({"Day": DAYS[d], "Time": f"{TIMESLOTS[t]} - {get_end_time(TIMESLOTS[t])}",
                              "Subject": classes[c]['Subject'], "Professor": classes[c]['Teacher'],
                              "Section": classes[c]['Section'], "Room": rooms[r],
                              "day_idx": d, "h_24": TIME_OBJECTS[t].hour, "m": TIME_OBJECTS[t].minute})
        return final
    return None

# --- SIDEBAR ---
with st.sidebar:
    st.write(f"👤 **{st.session_state.username}**")
    if st.button("🚪 Logout"):
        st.session_state.authenticated = False
        st.query_params.clear() # CLEAR URL PARAMS ON LOGOUT
        st.rerun()
    st.divider()

    # --- ADMIN EXCLUSIVE SECTION ---
    if st.session_state.user_role == 'admin':
        st.markdown("### 👑 Admin Panel")
        
        # 1. USER APPROVAL (UPDATED)
        with st.expander("🔔 User Approvals", expanded=False):
            pend = get_pending_users()
            if pend:
                for u in pend:
                    c1, c2, c3 = st.columns([2, 1, 1])
                    c1.write(f"{u['username']}")
                    
                    if c2.button("✅", key=f"acc_{u['id']}", help="Accept User"):
                        approve_user(u['id'])
                        st.success(f"Approved {u['username']}")
                        time.sleep(0.5)
                        st.rerun()
                    
                    if c3.button("❌", key=f"del_usr_{u['id']}", help="Delete User"):
                        delete_user_db(u['id'])
                        st.error(f"Deleted {u['username']}")
                        time.sleep(0.5)
                        st.rerun()
            else: st.caption("No pending users.")
            
        # 2. MANAGE SCHEDULES
        with st.expander("🗄️ Database History", expanded=True):
            all_gens = get_gens()
            if all_gens:
                with st.form("load_history_form"):
                    g_opts = {g[0]: f"Gen {g[0]} ({datetime.strptime(g[1], '%Y-%m-%d %H:%M:%S').strftime('%m-%d %H:%M') if isinstance(g[1], str) else g[1].strftime('%m-%d %H:%M')})" for g in all_gens}
                    sel = st.selectbox("Load Version", list(g_opts.keys()), format_func=lambda x: g_opts[x])
                    if st.form_submit_button("📂 Load Selected"):
                        loaded = load_gen(sel)
                        if loaded:
                            st.session_state.final_schedule = loaded
                            st.session_state.calendar_events = build_calendar_events(loaded)
                            st.rerun()
                
                st.markdown("---")
                st.caption("Delete Old Records:")
                for g in all_gens:
                    c1, c2 = st.columns([3,1])
                    c1.text(f"Gen {g[0]}")
                    if c2.button("🗑️", key=f"del_{g[0]}"):
                        delete_generation(g[0])
                        st.success(f"Deleted Gen {g[0]}")
                        time.sleep(0.5); st.rerun()
            else:
                st.caption("No saved schedules.")
        st.divider()

    # --- SHARED INPUT FORMS (Admin & User) ---
    with st.expander("🏠 Rooms"):
        for r in st.session_state.rooms: st.caption(f"🔹 {r}")
        with st.form("rm_f"):
            if st.form_submit_button("Add") and (nr:=st.text_input("Name")):
                st.session_state.rooms.append(nr); st.rerun()
        if st.button("Clear Rooms"): st.session_state.rooms = []; st.rerun()

    with st.expander("👥 Sections"):
        for s in st.session_state.sections: st.caption(f"🎓 {s}")
        with st.form("sc_f"):
            if st.form_submit_button("Add") and (ns:=st.text_input("Name")):
                st.session_state.sections.append(ns); st.rerun()
        if st.button("Clear Sections"): 
            st.session_state.sections = []
            st.rerun()

    with st.expander("👨‍🏫 Teachers"):
        with st.form("tc_f"):
            tn = st.text_input("Name")
            md = st.multiselect("AM Days", DAYS)
            mr = st.slider("AM", 7.5, 12.0, (7.5, 12.0), 0.5, "%g")
            ad = st.multiselect("PM Days", DAYS)
            ar = st.slider("PM", 1.0, 8.0, (1.0, 8.0), 0.5, "%g")
        
            if st.form_submit_button("Save"):
                # Gi-convert ug gihimong INT ang tibuok numero para dili na mag-error ang datetime()
                ms = f"{int(mr[0])}:30 AM" if mr[0] % 1 else fmt_time(int(mr[0]))
                me = f"{int(mr[1])}:30 AM" if mr[1] % 1 else fmt_time(int(mr[1]))
                as_ = f"{int(ar[0])}:30 PM" if ar[0] % 1 else fmt_time(int(ar[0]), True)
                ae = f"{int(ar[1])}:30 PM" if ar[1] % 1 else fmt_time(int(ar[1]), True)

                avail = {d: [] for d in DAYS}
                for d in md: avail[d].extend(get_slots(ms,me))
                for d in ad: avail[d].extend(get_slots(as_,ae))
                st.session_state.teachers[tn] = avail
                st.success("Saved"); st.rerun()

    st.divider()
    with st.form("cl_f"):
        sb = st.text_input("Subject")
        sc = st.selectbox("Section", st.session_state.sections)
        pr = st.selectbox("Prof", list(st.session_state.teachers.keys()) if st.session_state.teachers else ["None"])
        rm = st.multiselect("Rooms", st.session_state.rooms, default=st.session_state.rooms)
        if st.form_submit_button("Add to Queue") and sb:
            st.session_state.classes.append({"Subject":sb,"Section":sc,"Teacher":pr,"Allowed_Rooms":rm})
            st.success("Added"); st.rerun()
    if st.button("Clear Queue"): st.session_state.classes = []; st.rerun()

# --- DASHBOARD ---
st.markdown('<div class="header-style"><h1>📅 AI Powered Class Scheduler Developed by: LUIS PURAL</h1></div>', unsafe_allow_html=True)
c1,c2,c3,c4 = st.columns(4)
c1.metric("Queue", len(st.session_state.classes))
c2.metric("Rooms", len(st.session_state.rooms))
c3.metric("Teachers", len(st.session_state.teachers))
gens = get_gens()
c4.metric("Saved Gens", len(gens))

st.markdown("---")
col_l, col_r = st.columns([1, 2.5])

with col_l:
    st.subheader("📋 Queue")
    if st.session_state.classes:
        for i,c in enumerate(st.session_state.classes):
            with st.container(border=True):
                st.markdown(f"**{c['Subject']}**")
                st.caption(f"👨‍🏫 {c['Teacher']} | 🎓 {c['Section']}")
                if st.button("❌ Remove", key=f"queue_del_{i}"): 
                    st.session_state.classes.pop(i)
                    st.rerun()
        
        if st.button("🚀 AUTO-SCHEDULE", type="primary", use_container_width=True):
            with st.spinner("Solving..."):
                res = solve()
                if res:
                    st.session_state.final_schedule = res
                    st.session_state.calendar_events = build_calendar_events(res)
                    st.success("Done!")
                    time.sleep(1)
                    st.rerun()
                else: st.error("Conflict!")
    else: st.info("Empty Queue")

with col_r:
    st.subheader("🗓️ Official Schedule")
    
    if st.session_state.final_schedule:
        if st.button("💾 Save to DB", use_container_width=True):
            ok, m = save_db(st.session_state.final_schedule)
            if ok: st.success(m)
            else: st.error(m)
            
        t1, t2 = st.tabs(["Calendar", "List & Print"])
        
        with t1:
            calendar(
                events=st.session_state.calendar_events, 
                options={"editable": False, "headerToolbar": {"left": "title", "right": "timeGridWeek,listWeek"}, "initialView": "timeGridWeek", "slotMinTime": "07:00:00", "slotMaxTime": "21:00:00", "height": "700px"}, 
                key="stable_calendar"
            )
            
        with t2:
            st.markdown("### 🖨️ Print & Download")
            df = pd.DataFrame(st.session_state.final_schedule)
            st.dataframe(df[['Day','Time','Subject','Professor','Section','Room']], use_container_width=True, hide_index=True)
            
            d1, d2 = st.columns(2)
            csv = df.to_csv(index=False).encode('utf-8')
            d1.download_button("📥 Download CSV", csv, "sched.csv", "text/csv", use_container_width=True)
            
            pdf_bytes = generate_pdf(df)
            d2.download_button("📄 Download PDF", pdf_bytes, "sched.pdf", "application/pdf", use_container_width=True)

st.markdown('<div class="custom-footer">AI Powered Class Scheduler All Rights Reserved | LRP 12|23|25</div>', unsafe_allow_html=True)
