import streamlit as st
import sqlite3
import smtplib
import random
import os
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ============================================================
# 1. DATABASE SETUP & WHITELIST
# ============================================================
DB_FILE = os.path.join(os.path.dirname(__file__), "users.db")

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS authorized_users (
            email TEXT PRIMARY KEY
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def is_authorized(email):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT email FROM authorized_users WHERE email=?", (email,))
    result = c.fetchone()
    conn.close()
    return result is not None

def add_email(email):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO authorized_users (email) VALUES (?)", (email,))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    finally:
        conn.close()

# ============================================================
# 2. EMAIL DISPATCH LOGIC
# ============================================================
def send_otp_email(receiver_email, otp):
    try:
        sender_email = st.secrets["email_config"]["CAMPEX_EMAIL"]
        sender_password = st.secrets["email_config"]["CAMPEX_PASSWORD"]
        
        if sender_email == "ENTER_YOUR_EMAIL_HERE@gmail.com" or sender_password == "ENTER_YOUR_16_LETTER_APP_PASSWORD_HERE":
            st.error("⚠️ Please configure your `.streamlit/secrets.toml` file with your real email and app password.")
            print(f"\n[DEBUG] MAGIC OTP FOR {receiver_email}: {otp}\n")
            return False
            
    except Exception as e:
        st.error("⚠️ SMTP Credentials missing! Please configure the `.streamlit/secrets.toml` file.")
        print(f"\n[DEBUG] MAGIC OTP FOR {receiver_email}: {otp}\n")
        return False

    try:
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = receiver_email
        msg['Subject'] = "CAMPEX System - Authentication OTP"

        body = f"""
        Hello,

        Your one-time password (OTP) for CAMPEX access is: {otp}

        This code is valid for your current session. Please do not share it.
        """
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, sender_password)
        text = msg.as_string()
        server.sendmail(sender_email, receiver_email, text)
        server.quit()
        return True
    except Exception as e:
        st.error(f"Failed to send email: {e}")
        print(f"\n[DEBUG] MAGIC OTP FOR {receiver_email}: {otp}\n")
        return False

# ============================================================
# 3. STATE MANAGEMENT
# ============================================================
if "auth_status" not in st.session_state:
    st.session_state.auth_status = "unauthenticated"
if "current_user" not in st.session_state:
    st.session_state.current_user = None
if "current_email" not in st.session_state:
    st.session_state.current_email = None
if "generated_otp" not in st.session_state:
    st.session_state.generated_otp = None
if "email_failed" not in st.session_state:
    st.session_state.email_failed = False

# ============================================================
# 4. UI & FLOW (Authentication Pages)
# ============================================================
def render_auth_page():
    st.title("CAMPEX Secure Login")
    
    # --- State: Unauthenticated ---
    if st.session_state.auth_status == "unauthenticated":
        email_input = st.text_input("Enter your Email Address", value=st.session_state.current_email or "")
        
        if st.button("Send Magic OTP", type="primary"):
            if not email_input or "@" not in email_input:
                st.error("Please enter a valid email address.")
            else:
                otp = str(random.randint(100000, 999999))
                st.session_state.generated_otp = otp
                st.session_state.current_email = email_input
                st.session_state.current_user = email_input.split("@")[0]
                
                # Instantly decide if they are registering or just logging in
                if not is_authorized(email_input):
                    st.session_state.auth_status = "awaiting_otp_register"
                else:
                    st.session_state.auth_status = "awaiting_otp"
                
                with st.spinner("Dispatching OTP to your email..."):
                    # Send the email (or print to console if it fails)
                    if not send_otp_email(email_input, otp):
                        st.session_state.email_failed = True
                    else:
                        st.session_state.email_failed = False
                        
                    st.success(f"OTP process complete for {email_input}")
                    time.sleep(1)
                    st.rerun()

    # --- State: Awaiting OTP ---
    elif st.session_state.auth_status in ["awaiting_otp", "awaiting_otp_register"]:
        if st.session_state.email_failed:
            st.warning("⚠️ Email dispatch failed. The developer OTP was printed to the terminal console.")
        else:
            st.info(f"An OTP has been dispatched to **{st.session_state.current_email}**.")
            
        entered_otp = st.text_input("Enter 6-digit OTP", max_chars=6)
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Verify OTP", type="primary"):
                if entered_otp == st.session_state.generated_otp:
                    if st.session_state.auth_status == "awaiting_otp_register":
                        add_email(st.session_state.current_email)
                        st.success("Account successfully registered!")
                        time.sleep(1)
                        
                    st.session_state.auth_status = "authenticated"
                    st.rerun()
                else:
                    st.error("Invalid OTP Code.")
        with col2:
            if st.button("Cancel"):
                st.session_state.auth_status = "unauthenticated"
                st.session_state.current_user = None
                st.session_state.generated_otp = None
                st.session_state.email_failed = False
                st.rerun()

# ============================================================
# 5. PROTECTION & ROUTING
# ============================================================
def render_main_dashboard():
    st.title(f"Welcome to the Dashboard, {st.session_state.current_user}!")
    st.write("This is the protected area.")
    
    if st.button("Logout"):
        st.session_state.auth_status = "unauthenticated"
        st.session_state.current_user = None
        st.session_state.generated_otp = None
        st.session_state.email_failed = False
        st.rerun()

# Application Entry Point
if st.session_state.auth_status == "authenticated":
    render_main_dashboard()
else:
    render_auth_page()
