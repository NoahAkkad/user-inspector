import streamlit as st
import pandas as pd
from urllib.parse import parse_qs, urlparse
from typing import List, Dict
from datetime import datetime


def normalize_id_columns(df: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
    for col in columns:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()
    return df


def clean_value(val):
    """Safely clean extracted URL parameter values."""
    if val is None:
        return None
    val_str = str(val).strip()
    if val_str == "" or val_str.lower() == "none":
        return None
    return val_str


def extract_ids(value):
    if not isinstance(value, str):
        return None, None

    value = value.strip()
    if "-" not in value:
        return None, None

    parts = value.split("-", 1)
    if len(parts) != 2:
        return None, None

    return parts[0], parts[1]


def load_my_chips(df: pd.DataFrame) -> pd.DataFrame:
    if "UserID" not in df.columns:
        raise ValueError("Missing required column: UserID")

    df = df.copy()
    df["app_id"], df["user_id"] = zip(*df["UserID"].apply(extract_ids))

    df = normalize_id_columns(df, ["app_id", "user_id"])
    df = df[(df["app_id"] != "") & (df["user_id"] != "")]
    return df


def extract_user_info(postback_url: str) -> Dict[str, str]:
    parsed = urlparse(str(postback_url))
    params = parse_qs(parsed.query)

    raw_user = params.get("user", [""])[0]
    raw_user = str(raw_user).strip()

    app_id = ""
    user_id = ""
    if "-" in raw_user:
        parts = raw_user.split("-", 1)
        app_id = parts[0].strip()
        user_id = parts[1].strip()
    else:
        user_id = raw_user

    offer_name = clean_value(params.get("offer_name", [""])[0])
    task_name = clean_value(params.get("task_name", [""])[0])

    return {
        "app_id": app_id,
        "user_id": user_id,
        "raw_user": raw_user,
        "offer_name": offer_name,
        "task_name": task_name,
    }


def load_prime(df: pd.DataFrame) -> pd.DataFrame:
    if "Postback URL" not in df.columns:
        raise ValueError("Missing required column: Postback URL")

    df = df.copy()
    parsed = df["Postback URL"].apply(extract_user_info).apply(pd.Series)
    df = pd.concat([df, parsed], axis=1)

    df = normalize_id_columns(df, ["app_id", "user_id"])
    df = df[(df["app_id"] != "") & (df["user_id"] != "")]
    
    # Clean and normalize offer_name and task_name
    if "offer_name" in df.columns:
        df["offer_name"] = df["offer_name"].fillna("—")
    if "task_name" in df.columns:
        df["task_name"] = df["task_name"].fillna("—")
    
    return df




def run_search(
    df: pd.DataFrame,
    user_id_query: str,
    app_filter: str,
) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    filtered = df.copy()

    if user_id_query:
        val = str(user_id_query).strip()
        filtered["user_id"] = filtered.get("user_id", pd.Series(dtype=str)).astype(str).str.strip()
        filtered = filtered[filtered["user_id"] == val]

    if app_filter and app_filter != "All":
        val = str(app_filter).strip()
        filtered["app_id"] = filtered.get("app_id", pd.Series(dtype=str)).astype(str).str.strip()
        filtered = filtered[filtered["app_id"] == val]

    return filtered


def render_header() -> None:
    """Render a compact top header for tool-style UX."""
    st.markdown(
        """
        <div style="padding: 0.02rem 0 0.18rem 0; text-align: left; margin-top: 0;">
            <h1 style="margin: 0; font-size: 1.35rem; color: #1f2937; font-weight: 700; line-height: 1.2;">
                🔍 User Inspector
            </h1>
            <p style="margin: 0.12rem 0 0 0; font-size: 0.84rem; color: #6b7280; line-height: 1.3;">
                Analyze user activity from your uploaded data
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_search_controls(app_options: List[str]) -> tuple:
    """Render search controls. Returns (user_id, app_filter, search_clicked, reset_clicked)."""
    st.markdown("### 🔎 Step 2: Search & Filter")
    
    with st.container():
        col1, col2 = st.columns(2)
        
        with col1:
            user_id_input = st.text_input(
                label="User ID",
                placeholder="e.g., 264195",
                help="Enter the user ID to search for"
            )
        
        with col2:
            app_choice = st.selectbox(
                label="App",
                options=app_options,
                help="Filter results by app (optional)"
            )
        
        col_search, col_reset, col_spacer = st.columns([1, 1, 3])
        
        with col_search:
            search_button = st.button(
                "🔍 Search",
                use_container_width=True,
                type="primary",
                key="search_button_main"
            )
        
        with col_reset:
            reset_button = st.button(
                "↻ Reset",
                use_container_width=True,
                key="reset_button_main"
            )
        
        return user_id_input, app_choice, search_button, reset_button


def get_display_df(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare dataframe for display based on dataset type."""
    display_df = df.copy()
    display_df.columns = display_df.columns.str.strip()
    
    # Check if this is Prime data (has Postback URL column)
    is_prime = "Postback URL" in display_df.columns
    
    if is_prime:
        # Define visible columns for Prime dataset
        visible_columns = [
            "App",
            "user_id",
            "app_id",
            "Datetime",
            "Reward",
            "Payout",
            "Type",
            "offer_name",
            "task_name"
        ]
        
        # Filter only existing columns
        display_df = display_df[[col for col in visible_columns if col in display_df.columns]]
        
        # Reindex to ensure correct order (fill missing columns)
        display_df = display_df.reindex(columns=visible_columns, fill_value="")
    else:
        # My Chips dataset - use column mapping for variations
        column_mapping = {
            "DateTime": ["DateTime", "Datetime", "date"],
            "Payout": ["Payout", "payout"],
            "Country": ["Country", "country"],
            "EventName": ["EventName", "event_name", "type"],
            "AppName": ["AppName", "app", "App"]
        }
        
        def get_column(df, possible_names):
            for name in possible_names:
                if name in df.columns:
                    return name
            return None
        
        # Build display columns with fallback mapping
        display_columns = {
            "user_id": "user_id" if "user_id" in display_df.columns else None,
            "app_id": "app_id" if "app_id" in display_df.columns else None,
            "DateTime": get_column(display_df, column_mapping["DateTime"]),
            "Payout": get_column(display_df, column_mapping["Payout"]),
            "Country": get_column(display_df, column_mapping["Country"]),
            "EventName": get_column(display_df, column_mapping["EventName"]),
            "AppName": get_column(display_df, column_mapping["AppName"]),
        }
        
        # Create display dataframe with only mapped columns
        my_chips_display = pd.DataFrame()
        for key, col in display_columns.items():
            if col and col in display_df.columns:
                my_chips_display[key] = display_df[col]
            else:
                my_chips_display[key] = ""
        
        display_df = my_chips_display
    
    return display_df


def render_results(filtered_df: pd.DataFrame, original_df: pd.DataFrame, user_id_query: str, app_filter: str) -> None:
    """Render the results section."""
    st.markdown("### 📈 Step 3: Analysis Results")
    
    # Show active filters
    if user_id_query or (app_filter and app_filter != "All"):
        filter_text = []
        if user_id_query:
            filter_text.append(f"<strong>User ID</strong> = {user_id_query}")
        if app_filter and app_filter != "All":
            filter_text.append(f"<strong>App</strong> = {app_filter}")
        
        st.markdown(
            f"""
            <div style="background: #eff6ff; border-left: 4px solid #3b82f6; padding: 0.75rem; margin: 0.5rem 0; border-radius: 0.375rem;">
                <small style="color: #1e40af;">Active Filters: {' • '.join(filter_text)}</small>
            </div>
            """,
            unsafe_allow_html=True,
        )
    
    # Show statistics
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Matching Rows", f"{len(filtered_df):,}")
    with col2:
        match_pct = (len(filtered_df) / len(original_df) * 100) if len(original_df) > 0 else 0
        st.metric("Match %", f"{match_pct:.1f}%")
    with col3:
        st.metric("Total Dataset", f"{len(original_df):,}")
    
    # Display results
    if filtered_df.empty:
        st.markdown(
            """
            <div style="background: #fef2f2; border-left: 4px solid #ef4444; padding: 0.85rem; margin: 0.65rem 0; border-radius: 0.375rem; text-align: left; color: #7f1d1d;">
                <strong>No results found</strong>
                <br>
                <small>Try adjusting your search filters</small>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown("**Data Table** (scroll right for more columns)")
        
        # Prepare display dataframe
        display_df = get_display_df(filtered_df)
        
        # Display with custom styling
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            height=400
        )
        
        # Download option
        csv = display_df.to_csv(index=False)
        st.download_button(
            label="📥 Download Results (CSV)",
            data=csv,
            file_name=f"user_inspector_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv"
        )


def configure_page() -> None:
    """Configure Streamlit page settings."""
    st.set_page_config(
        page_title="User Inspector",
        page_icon="🔍",
        layout="centered",
        initial_sidebar_state="collapsed"
    )
    
    # Single neutral light-theme CSS for consistent readability.
    st.markdown(
        """
        <style>
        /* Global Styles */
        :root {
            --primary-color: #3b82f6;
            --success-color: #22c55e;
            --error-color: #ef4444;
            --warning-color: #f59e0b;
            --background: #f9fafb;
            --text-primary: #1f2937;
            --text-secondary: #6b7280;
            --border: #e5e7eb;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Helvetica Neue', sans-serif;
            color: var(--text-primary);
            background-color: var(--background);
        }

        /* Keep content readable and left-aligned without full-width stretching */
        .block-container {
            max-width: 1080px;
            padding-top: 0.05rem !important;
            padding-bottom: 1.25rem;
        }

        [data-testid="stAppViewContainer"] .main .block-container {
            padding-top: 0.05rem !important;
            margin-top: 0 !important;
        }

        [data-testid="stAppViewContainer"] .main {
            padding-top: 0 !important;
        }
        
        /* Remove top padding */
        .main {
            padding-top: 0 !important;
        }

        .block-container > div:first-child,
        .block-container > div:first-child > div:first-child {
            margin-top: 0 !important;
            padding-top: 0 !important;
        }
        
        /* Card styling */
        [data-testid="stContainer"] {
            background-color: white;
            border-radius: 0.5rem;
            box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
            padding: 1rem;
            margin-bottom: 0.9rem;
        }
        
        /* Button styling */
        .stButton > button {
            border-radius: 0.375rem;
            font-weight: 500;
            transition: all 0.2s ease;
            border: none;
            padding: 0.5rem 1rem;
        }
        
        .stButton > button:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        
        .stButton > button[kind="primary"] {
            background-color: var(--primary-color) !important;
            color: white !important;
        }
        
        .stButton > button[kind="secondary"] {
            background-color: var(--text-secondary) !important;
            color: white !important;
        }
        
        /* Input field styling */
        .stTextInput > div > div > input,
        .stSelectbox > div > div > select {
            border: 1px solid var(--border);
            background-color: #ffffff;
            color: var(--text-primary);
            border-radius: 0.375rem;
            padding: 0.5rem 0.75rem;
            font-size: 0.95rem;
        }

        /* Keep BaseWeb select controls readable in Streamlit */
        div[data-baseweb="select"] > div {
            background-color: #ffffff !important;
            color: var(--text-primary) !important;
            border-color: var(--border) !important;
        }

        div[data-baseweb="popover"] div,
        div[data-baseweb="menu"] div {
            background-color: #ffffff !important;
            color: var(--text-primary) !important;
        }
        
        .stTextInput > div > div > input:focus,
        .stSelectbox > div > div > select:focus {
            border-color: var(--primary-color);
            box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
        }
        
        /* Metric styling */
        [data-testid="metric-container"] {
            background-color: #f3f4f6;
            border-radius: 0.375rem;
            padding: 1rem;
        }
        
        /* Dataframe styling */
        [data-testid="stDataFrame"] {
            border-radius: 0.375rem;
            border: 1px solid var(--border);
            background-color: #ffffff;
            color: var(--text-primary);
        }

        [data-testid="stDataFrame"] table,
        [data-testid="stDataFrame"] th,
        [data-testid="stDataFrame"] td {
            color: var(--text-primary) !important;
            background-color: #ffffff !important;
        }
        
        /* Headers */
        h1, h2, h3 {
            color: var(--text-primary);
            font-weight: 700;
        }
        
        h3 {
            margin-top: 0.7rem;
            margin-bottom: 0.6rem;
            font-size: 1.05rem;
        }
        
        /* Divider */
        hr {
            border: none;
            border-top: 1px solid var(--border);
            margin: 0.65rem 0;
        }
        
        /* Info/Warning/Error boxes */
        .stAlert {
            border-radius: 0.375rem;
            border-left: 4px solid;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    """Main application entry point."""
    configure_page()
    
    # Initialize session state
    if "original_df" not in st.session_state:
        st.session_state.original_df = pd.DataFrame()
    if "filtered_df" not in st.session_state:
        st.session_state.filtered_df = pd.DataFrame()
    if "file_loaded" not in st.session_state:
        st.session_state.file_loaded = False
    if "current_file_name" not in st.session_state:
        st.session_state.current_file_name = None
    
    # Render header
    render_header()
    
    # Step 1: Upload
    with st.container():
        st.markdown("### 📤 Step 1: Upload Data")
        
        uploaded_file = st.file_uploader(
            label="Drop or select .xlsx or .csv file",
            type=["xlsx", "csv"],
            key="file_uploader_main"
        )
        
        if uploaded_file is not None:
            # Display file info
            file_size_kb = uploaded_file.size / 1024
            st.markdown(
                f"""
                <div style="background: #f0fdf4; border-left: 4px solid #22c55e; padding: 0.75rem; margin: 0.5rem 0; border-radius: 0.375rem;">
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                        <span style="color: #22c55e; font-size: 1.2rem;">✓</span>
                        <div>
                            <strong style="color: #166534;">{uploaded_file.name}</strong>
                            <br>
                            <small style="color: #4ade80;">{file_size_kb:.1f} KB</small>
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                """
                <div style="background: #fef3c7; border-left: 4px solid #f59e0b; padding: 0.85rem; margin: 0.65rem 0; border-radius: 0.375rem; text-align: left; color: #92400e;">
                    <p style="margin: 0;"><strong>Upload a file to begin</strong></p>
                    <small>Supports Excel (.xlsx) and CSV (.csv) formats</small>
                </div>
                """,
                unsafe_allow_html=True,
            )
            return
    
    # File has been uploaded
    file_name = uploaded_file.name.lower()
    
    # Load file if not already loaded or file changed
    if (not st.session_state.file_loaded or 
        st.session_state.current_file_name != file_name):
        try:
            with st.spinner("Loading file..."):
                if file_name.endswith(".csv"):
                    df_raw = pd.read_csv(uploaded_file)
                    df = load_prime(df_raw)
                elif file_name.endswith(".xlsx"):
                    df_raw = pd.read_excel(uploaded_file, engine="openpyxl")
                    df = load_my_chips(df_raw)
                else:
                    st.error("Unsupported file type")
                    return
                
                st.session_state.original_df = df
                st.session_state.filtered_df = df
                st.session_state.file_loaded = True
                st.session_state.current_file_name = file_name
            
            # Show success message
            st.success(f"✓ File loaded successfully! Ready to search.")
        
        except Exception as e:
            st.error(f"❌ Error loading file: {str(e)}")
            st.session_state.original_df = pd.DataFrame()
            st.session_state.filtered_df = pd.DataFrame()
            st.session_state.file_loaded = False
            return
    
    if st.session_state.original_df.empty:
        st.info("No data available after parsing.")
        return
    
    # Step 2: Search Controls
    app_options = ["All"] + sorted(
        st.session_state.original_df["app_id"].dropna().astype(str).unique().tolist()
    )
    user_id_input, app_choice, search_button, reset_button = render_search_controls(app_options)
    
    # Handle search/reset
    if reset_button:
        st.session_state.filtered_df = st.session_state.original_df.copy()
        st.rerun()
    
    if search_button:
        st.session_state.filtered_df = run_search(
            st.session_state.original_df,
            user_id_query=user_id_input,
            app_filter=app_choice,
        )
        st.rerun()
    
    # Step 3: Results and summary
    render_results(
        st.session_state.filtered_df,
        st.session_state.original_df,
        user_id_input,
        app_choice
    )


if __name__ == "__main__":
    main()
